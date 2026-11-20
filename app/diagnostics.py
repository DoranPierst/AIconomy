"""End-to-end live MCP connection diagnostics (HTTP JSON-RPC, Blender socket, stdio handshake; EN & TR)."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import subprocess
import threading
import time
import tomllib
from typing import Any
import urllib.error
import urllib.request

import psutil

from .catalog import ToolSpec
from .host_apps import NO_WINDOW
from .mcp_config import build_effective_stdio_spec, is_tool_credential_ready
from .oauth import get_oauth_spec, supports_oauth
from .security import build_isolated_child_env
from .storage import WindowsDpapiVault
from .tokens import estimate_tokens_from_tools_payload
from .updater import get_current_app_version


def _terminate_proc_tree(proc: subprocess.Popen[Any], wait_timeout: float = 1.2) -> None:
    """Terminate a spawned subprocess AND all recursive child processes (prevents orphaned node.exe/uvx.exe on Windows)."""
    children: list[psutil.Process] = []
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []

    for ch in children:
        try:
            ch.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        proc.terminate()
    except Exception:
        pass

    try:
        proc.wait(timeout=wait_timeout)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    if children:
        _gone, alive = psutil.wait_procs(children, timeout=0.8)
        for ch in alive:
            try:
                ch.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass


def _is_custom_skill_tool(tool: ToolSpec) -> bool:
    return bool(
        tool.id not in ("blender_skills", "caveman")
        and not tool.mcp_server_key
        and (tool.kind in ("skill_pack", "rule") or (tool.install_cmd or "").strip().startswith("git clone "))
    )


def _has_agy_skill_mirror_on_disk(home: pathlib.Path, tool_id: str) -> bool:
    agy_root = home / ".gemini" / "config" / "skills"
    if not agy_root.is_dir():
        return False
    if (agy_root / tool_id / "SKILL.md").is_file() or (agy_root / tool_id).is_dir():
        return True
    return any(c.is_dir() and c.name.startswith(f"{tool_id}__") for c in agy_root.iterdir())


def test_tool_connection_e2e(
    tool: ToolSpec,
    vault: WindowsDpapiVault,
    projects_map: dict[str, str],
    active_skills_count: int = 0,
    lang: str = "en",
) -> tuple[bool, int, str, str]:
    """Run an end-to-end connection probe even when AI IDEs are closed.

    Returns (ok, latency_ms, short_summary, technical_detail).
    """
    is_tr = lang == "tr"
    t0 = time.perf_counter()
    cfg_note = ""
    if tool.mcp_server_key:
        agy_cfg = pathlib.Path.home() / ".gemini" / "config" / "mcp_config.json"
        if agy_cfg.is_file():
            try:
                servers = json.loads(agy_cfg.read_text(encoding="utf-8") or "{}").get("mcpServers", {})
                in_agy = tool.mcp_server_key in servers
                if tool.enabled and tool.clients.get("AGY") and not in_agy:
                    cfg_note = " | AGY config eksik" if is_tr else " | Missing in AGY config"
                elif in_agy:
                    cfg_note = " | AGY config OK"
            except Exception:
                pass

    if not tool.enabled:
        return (
            False,
            -1,
            "Devre dışı (atlandı)" if is_tr else "Disabled (skipped)",
            "Araç kapalı; önce etkinleştirin." if is_tr else "Tool is disabled; enable it first.",
        )

    app_ver = get_current_app_version()

    if tool.id in ("serena", "unity_mcp") and tool.port:
        port = int(tool.port)
        url = f"http://127.0.0.1:{port}/mcp"
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "aiconomy-diagnostics", "version": app_ver},
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                body = resp.read(2048).decode("utf-8", errors="replace")
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                if "result" in body or "serverInfo" in body or resp.status == 200:
                    return True, ms, f"MCP Initialize OK ({ms}ms){cfg_note}", f"POST {url} -> HTTP {resp.status}\n{body[:400]}"
                return False, ms, f"HTTP {resp.status}", body[:400]
        except urllib.error.HTTPError as exc:
            ms = max(1, int((time.perf_counter() - t0) * 1000))
            err_b = exc.read(512).decode("utf-8", errors="replace")
            if exc.code in (400, 405, 406):
                lbl = f"HTTP sunucu aktif ({ms}ms, HTTP {exc.code}){cfg_note}" if is_tr else f"HTTP server reachable ({ms}ms, HTTP {exc.code}){cfg_note}"
                return True, ms, lbl, f"{url}: {err_b}"
            return False, -1, f"HTTP {exc.code}", err_b
        except Exception as exc:
            lbl = f"Bağlantı yok (:{port})" if is_tr else f"No connection (:{port})"
            return False, -1, lbl, f"{url}: {exc}"

    if tool.id == "blender_mcp":
        port = int(tool.port or 9876)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5) as s:
                s.settimeout(2.5)
                s.sendall(b'{"type":"get_scene_info","params":{}}')
                resp = s.recv(4096).decode("utf-8", errors="replace")
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                if "result" in resp or "status" in resp or "name" in resp:
                    lbl = f"Blender sahne yanıtı OK ({ms}ms){cfg_note}" if is_tr else f"Blender scene response OK ({ms}ms){cfg_note}"
                    return True, ms, lbl, resp[:400]
                return False, ms, ("Boş soket yanıtı" if is_tr else "Empty socket response"), resp[:300]
        except Exception as exc:
            lbl = f"Blender :{port} bağlanamadı" if is_tr else f"Blender :{port} unreachable"
            return False, -1, lbl, str(exc)

    if tool.id == "trellis":
        port = int(tool.port or 8790)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                lbl = f"TRELLIS GPU sunucusu açık ({ms}ms)" if is_tr else f"TRELLIS GPU server running ({ms}ms)"
                return True, ms, lbl, f"127.0.0.1:{port} TCP OK"
        except OSError:
            cli_exe = pathlib.Path(tool.param_value) / "runtime" / "trellis-cli.exe"
            if cli_exe.is_file():
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                lbl = f"CLI hazır, sunucu uykuda ({ms}ms)" if is_tr else f"CLI ready, server standby ({ms}ms)"
                return True, ms, lbl, str(cli_exe)
            return False, -1, ("TRELLIS kurulumu bulunamadı" if is_tr else "TRELLIS install not found"), str(cli_exe)

    if tool.mcp_command or getattr(tool, "auth_mode", "key") == "oauth":
        if not is_tool_credential_ready(tool, vault):
            lbl = f"Kimlik doğrulama eksik ({tool.vault_key_name or 'OAuth'})" if is_tr else f"Missing credential ({tool.vault_key_name or 'OAuth'})"
            det = "Ayarlar > API Anahtarları veya OAuth girişi yapın." if is_tr else "Configure in Settings > API Keys or sign in via OAuth."
            return False, -1, lbl, det

        spec = build_effective_stdio_spec(tool, vault, wrap_windows_npx=False)
        if spec is None:
            return False, -1, ("Yapılandırma eksik" if is_tr else "Configuration missing"), tool.name
        raw_bin, eff_args, eff_env = spec
        cmd_bin = shutil.which(f"{raw_bin}.cmd") or shutil.which(raw_bin)
        if not cmd_bin:
            lbl = f"Komut bulunamadı: {raw_bin}" if is_tr else f"Command not found: {raw_bin}"
            return False, -1, lbl, f"'{raw_bin}' is not on PATH."
        env = build_isolated_child_env(eff_env, allowed_secret_key=tool.vault_key_name)

        return _run_stdio_handshake(cmd_bin, eff_args, env, t0, cfg_note, app_ver, lang=lang)

    if tool.id == "blender_skills":
        plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
        ok = (plugin_dir / "skills").is_dir()
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        lbl = (
            f"{active_skills_count}/94 skill hazır" if ok else "Kurulu değil"
        ) if is_tr else (
            f"{active_skills_count}/94 skills ready" if ok else "Not installed"
        )
        return ok, ms, lbl, str(plugin_dir)

    if tool.id == "caveman":
        skill_md = pathlib.Path.home() / ".agents" / "skills" / "caveman" / "SKILL.md"
        agy_md = pathlib.Path.home() / ".gemini" / "config" / "skills" / "caveman" / "SKILL.md"
        want_agy = bool(tool.clients.get("AGY", False))
        want_agents = bool(tool.clients.get("CDX", False) or tool.clients.get("CLD", False) or tool.clients.get("CUR", False))
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        if want_agy and not agy_md.is_file():
            lbl = "AGY skill senkronu eksik" if is_tr else "AGY skill mirror missing"
            return False, ms, lbl, f"{skill_md} -> {agy_md}"
        if want_agents and not skill_md.is_file():
            lbl = "SKILL.md eksik (~/.agents/skills)" if is_tr else "SKILL.md missing (~/.agents/skills)"
            return False, ms, lbl, str(skill_md)
        ok = (want_agy and agy_md.is_file()) or (want_agents and skill_md.is_file())
        lbl = ("SKILL.md doğrulandı" if ok else "SKILL.md eksik") if is_tr else ("SKILL.md verified" if ok else "SKILL.md missing")
        parts = [p for p, cond in ((str(skill_md), skill_md.is_file()), (f"AGY: {agy_md}", agy_md.is_file())) if cond]
        return ok, ms, lbl, " | ".join(parts) or str(skill_md)

    if tool.id == "unity_pipeline":
        target_proj = projects_map.get(tool.project_scope, tool.param_value)
        manifest = pathlib.Path(target_proj) / "Packages" / "manifest.json"
        ok = manifest.is_file() and "com.unity.pipeline" in manifest.read_text(encoding="utf-8", errors="ignore")
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        lbl = ("Paket doğrulandı" if ok else "Paket eksik") if is_tr else ("Package verified" if ok else "Package missing")
        return ok, ms, lbl, str(manifest)

    if _is_custom_skill_tool(tool):
        home = pathlib.Path.home()
        act_dir = home / ".agents" / "skills" / tool.id
        has_agy = _has_agy_skill_mirror_on_disk(home, tool.id)
        want_agy = bool(tool.clients.get("AGY", False))
        want_agents = bool(tool.clients.get("CDX", False) or tool.clients.get("CLD", False) or tool.clients.get("CUR", False))
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        if want_agy and not has_agy:
            lbl = "AGY skill senkronu eksik" if is_tr else "AGY skill mirror missing"
            return False, -1, lbl, str(home / ".gemini" / "config" / "skills" / tool.id)
        if want_agents and not act_dir.is_dir():
            lbl = "Skill dizini eksik (~/.agents/skills)" if is_tr else "Skill directory missing (~/.agents/skills)"
            return False, -1, lbl, str(act_dir)
        ok = (want_agy and has_agy) or (want_agents and act_dir.is_dir())
        lbl = ("Skill doğrulandı" if ok else "Skill kurulu değil") if is_tr else ("Skill verified" if ok else "Skill not installed")
        return (ok, ms if ok else -1, lbl, str(act_dir))

    return True, 1, ("Hazır" if is_tr else "Ready"), tool.summary


def _run_stdio_handshake(
    cmd_bin: str,
    args: list[str],
    env: dict[str, str],
    t0: float,
    cfg_note: str,
    app_ver: str = "1.0.0",
    lang: str = "en",
) -> tuple[bool, int, str, str]:
    """Send a JSON-RPC initialize message over stdio and read the response with timeout."""
    is_tr = lang == "tr"
    init_msg = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "aiconomy-diagnostics", "version": app_ver},
                },
            }
        )
        + "\n"
    )
    proc = subprocess.Popen(
        [cmd_bin, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        creationflags=NO_WINDOW,
    )
    out_lines: list[str] = []

    def _reader() -> None:
        if proc.stdout:
            for line in proc.stdout:
                out_lines.append(line.strip())
                if '"result"' in line or '"serverInfo"' in line:
                    break

    rt = threading.Thread(target=_reader, daemon=True)
    rt.start()
    try:
        if proc.stdin:
            proc.stdin.write(init_msg)
            proc.stdin.flush()
        rt.join(timeout=7.5)
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        joined = "\n".join(out_lines)
        if '"result"' in joined or '"serverInfo"' in joined:
            return True, ms, f"stdio MCP Handshake OK ({ms}ms){cfg_note}", joined[:400]
        rc = proc.poll()
        err_txt = ""
        if proc.stderr and rc is not None:
            err_txt = proc.stderr.read(400).strip()
        if rc is None:
            lbl = f"stdio süreç başladı ({ms}ms){cfg_note}" if is_tr else f"stdio process started ({ms}ms){cfg_note}"
            det = "Süreç ayakta; ilk yanıt beklenenden uzun sürdü." if is_tr else "Process is running; initial reply timed out."
            return True, ms, lbl, det
        lbl = f"stdio çıkış kodu {rc}" if is_tr else f"stdio exit code {rc}"
        return False, -1, lbl, err_txt or joined or ("Süreç erken kapandı." if is_tr else "Process exited early.")
    finally:
        _terminate_proc_tree(proc, wait_timeout=1.5)


def _extract_tools_from_jsonrpc_text(raw_body: str) -> list[dict] | None:
    """Parse either a direct JSON-RPC reply or SSE `data: {...}` lines to extract `result.tools`."""
    candidates: list[str] = []
    stripped = raw_body.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    for line in raw_body.splitlines():
        ls = line.strip()
        if ls.startswith("data:"):
            payload = ls[5:].strip()
            if payload.startswith("{"):
                candidates.append(payload)
        elif ls.startswith("{"):
            candidates.append(ls)
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                res = obj.get("result")
                if isinstance(res, dict) and isinstance(res.get("tools"), list):
                    return res["tools"]
        except Exception:
            continue
    return None


def measure_tool_schema_tokens(
    tool: ToolSpec,
    vault: WindowsDpapiVault,
) -> int | None:
    """Query live MCP `tools/list` (HTTP or stdio) and compute exact schema token footprint, or None if unreachable."""
    app_ver = get_current_app_version()

    # 1. Local HTTP Streamable MCP servers (Serena, Unity MCP)
    if tool.id in ("serena", "unity_mcp") and tool.port:
        url = f"http://127.0.0.1:{int(tool.port)}/mcp"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        init_payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "aiconomy-schema-meter", "version": app_ver},
                },
            }
        ).encode("utf-8")
        try:
            req1 = urllib.request.Request(url, data=init_payload, method="POST", headers=headers)
            session_id = ""
            with urllib.request.urlopen(req1, timeout=3.5) as r1:
                session_id = str(r1.headers.get("Mcp-Session-Id") or r1.headers.get("mcp-session-id") or "").strip()
                _ = r1.read(8192)
            req_headers = dict(headers)
            if session_id:
                req_headers["Mcp-Session-Id"] = session_id
            try:
                notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
                with urllib.request.urlopen(
                    urllib.request.Request(url, data=notif, method="POST", headers=req_headers), timeout=2.0
                ):
                    pass
            except Exception:
                pass
            list_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8")
            with urllib.request.urlopen(
                urllib.request.Request(url, data=list_payload, method="POST", headers=req_headers), timeout=4.5
            ) as r2:
                body2 = r2.read(524288).decode("utf-8", errors="replace")
            tools_arr = _extract_tools_from_jsonrpc_text(body2)
            if tools_arr is not None:
                return estimate_tokens_from_tools_payload(tools_arr)
        except Exception:
            return None
        return None

    # 2. Stdio MCP servers
    if not (tool.mcp_command or getattr(tool, "auth_mode", "key") == "oauth"):
        return None
    if not is_tool_credential_ready(tool, vault):
        return None
    spec = build_effective_stdio_spec(tool, vault, wrap_windows_npx=False)
    if spec is None:
        return None
    raw_bin, eff_args, eff_env = spec
    cmd_bin = shutil.which(f"{raw_bin}.cmd") or shutil.which(raw_bin)
    if not cmd_bin:
        return None
    env = build_isolated_child_env(eff_env, allowed_secret_key=tool.vault_key_name)

    try:
        proc = subprocess.Popen(
            [cmd_bin, *eff_args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
            creationflags=NO_WINDOW,
        )
    except Exception:
        return None

    found_tools: list[dict] | None = None
    init_done = threading.Event()
    list_done = threading.Event()

    def _reader() -> None:
        nonlocal found_tools
        if not proc.stdout:
            return
        for raw_line in proc.stdout:
            ls = raw_line.strip()
            if not ls.startswith("{"):
                continue
            try:
                msg = json.loads(ls)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == 1 and "result" in msg:
                init_done.set()
            elif msg.get("id") == 2 and isinstance(msg.get("result"), dict):
                t_arr = msg["result"].get("tools")
                if isinstance(t_arr, list):
                    found_tools = t_arr
                list_done.set()
                break

    rt = threading.Thread(target=_reader, daemon=True)
    rt.start()
    try:
        if proc.stdin:
            init_line = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "aiconomy-schema-meter", "version": app_ver},
                    },
                }
            )
            proc.stdin.write(init_line + "\n")
            proc.stdin.flush()
            if init_done.wait(timeout=5.5):
                proc.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
                proc.stdin.write('{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n')
                proc.stdin.flush()
                list_done.wait(timeout=5.5)
        if found_tools is not None:
            return estimate_tokens_from_tools_payload(found_tools)
    except Exception:
        return None
    finally:
        _terminate_proc_tree(proc, wait_timeout=1.2)
    return None


def inspect_client_config_file(
    client_code: str,
    projects_map: dict[str, str] | None = None,
    lang: str = "en",
) -> tuple[bool, str, dict[str, dict[str, Any]], set[str], pathlib.Path]:
    """Parse a real AI client's config file and return (parse_ok, summary_msg, active_servers, disabled_keys, path)."""
    is_tr = lang == "tr"
    home = pathlib.Path.home()
    code = (client_code or "AGY").upper()

    if code == "CDX":
        cfg_path = home / ".codex" / "config.toml"
        if not cfg_path.is_file():
            msg = (
                f"Codex config.toml bulunamadı ({cfg_path})"
                if is_tr
                else f"Codex config.toml not found ({cfg_path})"
            )
            return True, msg, {}, set(), cfg_path
        try:
            raw = cfg_path.read_text(encoding="utf-8-sig")
            data = tomllib.loads(raw) if raw.strip() else {}
        except Exception as exc:
            msg = (
                f"TOML sözdizimi hatası ({cfg_path.name}): {exc}"
                if is_tr
                else f"TOML syntax error ({cfg_path.name}): {exc}"
            )
            return False, msg, {}, set(), cfg_path
        all_srv = data.get("mcp_servers") if isinstance(data.get("mcp_servers"), dict) else {}
        active: dict[str, dict[str, Any]] = {}
        disabled: set[str] = set()
        for k, v in all_srv.items():
            if not isinstance(v, dict):
                continue
            if v.get("enabled") is False:
                disabled.add(str(k))
            else:
                active[str(k)] = v
        msg = (
            f"TOML geçerli: {len(active)} aktif MCP ({cfg_path})"
            if is_tr
            else f"Valid TOML: {len(active)} active MCP(s) ({cfg_path})"
        )
        return True, msg, active, disabled, cfg_path

    cfg_map = {
        "AGY": home / ".gemini" / "config" / "mcp_config.json",
        "CLD": home / ".claude.json",
        "CUR": home / ".cursor" / "mcp.json",
    }
    cfg_path = cfg_map.get(code, cfg_map["AGY"])
    active = {}
    if cfg_path.is_file():
        try:
            raw = cfg_path.read_text(encoding="utf-8-sig")
            data = json.loads(raw) if raw.strip() else {}
            if not isinstance(data, dict):
                raise ValueError("JSON root must be an object")
        except Exception as exc:
            msg = (
                f"JSON sözdizimi hatası ({cfg_path.name}): {exc}"
                if is_tr
                else f"JSON syntax error ({cfg_path.name}): {exc}"
            )
            return False, msg, {}, set(), cfg_path
        srv = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
        for k, v in srv.items():
            if isinstance(v, dict):
                active[str(k)] = v

    # Also merge project-scoped .mcp.json / .cursor/mcp.json for CLD / CUR
    if code in ("CLD", "CUR") and projects_map:
        rel_name = ".mcp.json" if code == "CLD" else ".cursor/mcp.json"
        for proj_dir_s in projects_map.values():
            p_cfg = pathlib.Path(proj_dir_s) / rel_name
            if not p_cfg.is_file():
                continue
            try:
                p_data = json.loads(p_cfg.read_text(encoding="utf-8-sig") or "{}")
                p_srv = p_data.get("mcpServers") if isinstance(p_data, dict) and isinstance(p_data.get("mcpServers"), dict) else {}
                for k, v in p_srv.items():
                    if isinstance(v, dict):
                        active[str(k)] = v
            except Exception as exc:
                msg = (
                    f"Proje JSON hatası ({p_cfg}): {exc}"
                    if is_tr
                    else f"Project JSON error ({p_cfg}): {exc}"
                )
                return False, msg, active, set(), p_cfg

    if not cfg_path.is_file() and not active:
        msg = (
            f"{code} config dosyası henüz yok ({cfg_path})"
            if is_tr
            else f"{code} config file not created yet ({cfg_path})"
        )
        return True, msg, {}, set(), cfg_path

    msg = (
        f"JSON geçerli: {len(active)} MCP ({cfg_path})"
        if is_tr
        else f"Valid JSON: {len(active)} MCP(s) ({cfg_path})"
    )
    return True, msg, active, set(), cfg_path


def _run_http_mcp_init(
    url: str,
    t0: float,
    cfg_note: str,
    app_ver: str = "1.0.0",
    lang: str = "en",
) -> tuple[bool, int, str, str]:
    is_tr = lang == "tr"
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "aiconomy-diagnostics", "version": app_ver},
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            body = resp.read(2048).decode("utf-8", errors="replace")
            ms = max(1, int((time.perf_counter() - t0) * 1000))
            if "result" in body or "serverInfo" in body or resp.status == 200:
                return True, ms, f"MCP Initialize OK ({ms}ms){cfg_note}", f"POST {url} -> HTTP {resp.status}\n{body[:400]}"
            return False, ms, f"HTTP {resp.status}", body[:400]
    except urllib.error.HTTPError as exc:
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        err_b = exc.read(512).decode("utf-8", errors="replace")
        if exc.code in (400, 405, 406):
            lbl = (
                f"HTTP sunucu aktif ({ms}ms, HTTP {exc.code}){cfg_note}"
                if is_tr
                else f"HTTP server reachable ({ms}ms, HTTP {exc.code}){cfg_note}"
            )
            return True, ms, lbl, f"{url}: {err_b}"
        return False, -1, f"HTTP {exc.code}", err_b
    except Exception as exc:
        lbl = f"Bağlantı yok ({url})" if is_tr else f"No connection ({url})"
        return False, -1, lbl, f"{url}: {exc}"


def _test_config_entry_live(
    entry: dict[str, Any],
    t0: float,
    cfg_note: str,
    app_ver: str,
    lang: str = "en",
) -> tuple[bool, int, str, str]:
    """Execute the exact HTTP URL or stdio command+args+env stored in a client's config file."""
    is_tr = lang == "tr"
    url = str(entry.get("url") or entry.get("serverUrl") or "").strip()
    if url:
        return _run_http_mcp_init(url, t0, cfg_note, app_ver=app_ver, lang=lang)

    raw_cmd = str(entry.get("command") or "").strip()
    raw_args = [str(a) for a in (entry.get("args") or [])]
    raw_env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    if not raw_cmd:
        return (
            False,
            -1,
            "Config girdisinde komut/URL eksik" if is_tr else "Config entry missing command/URL",
            json.dumps(entry, ensure_ascii=False),
        )
    cmd_bin = raw_cmd if pathlib.Path(raw_cmd).is_file() else (shutil.which(f"{raw_cmd}.cmd") or shutil.which(raw_cmd))
    if not cmd_bin:
        lbl = f"Komut bulunamadı: {raw_cmd}" if is_tr else f"Command not found: {raw_cmd}"
        return False, -1, lbl, f"command={raw_cmd!r}, args={raw_args!r}"

    clean_raw_env = {str(k): str(v) for k, v in raw_env.items()}
    env = build_isolated_child_env(clean_raw_env)
    return _run_stdio_handshake(cmd_bin, raw_args, env, t0, cfg_note, app_ver=app_ver, lang=lang)


def _check_dry_run_readiness(
    tool: ToolSpec,
    vault: WindowsDpapiVault,
    projects_map: dict[str, str],
    active_skills_count: int,
    lang: str = "en",
) -> tuple[bool, int, str, str, str]:
    """Run an honest readiness dry-run while tools are stopped (never pretends HTTP servers are running)."""
    is_tr = lang == "tr"
    t0 = time.perf_counter()
    app_ver = get_current_app_version()

    if tool.id in ("serena", "unity_mcp") and tool.port:
        port = int(tool.port)
        local_bin = pathlib.Path.home() / ".local" / "bin"
        if tool.id == "serena":
            found = (local_bin / "serena.exe").is_file() or bool(shutil.which("serena"))
            bin_lbl = str(local_bin / "serena.exe")
        else:
            found = (
                (local_bin / "mcp-for-unity.exe").is_file()
                or (local_bin / "unity-mcp.exe").is_file()
                or bool(shutil.which("mcp-for-unity") or shutil.which("unity-mcp") or shutil.which("uvx"))
            )
            bin_lbl = str(local_bin / "mcp-for-unity.exe")
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        if found:
            lbl = (
                f"Durduruldu — başlatılmaya hazır (:{port} kapalı)"
                if is_tr
                else f"Stopped — binary ready (:{port} closed)"
            )
            return True, ms, lbl, f"Binary OK ({bin_lbl}); HTTP :{port} stopped as expected.", "ready_stopped"
        lbl = (
            "Kurulu değil (ikili bulunamadı)" if is_tr else "Not installed (executable missing)"
        )
        return False, -1, lbl, f"Missing executable: {bin_lbl}", "fail"

    if tool.id == "blender_mcp":
        port = int(tool.port or 9876)
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        has_uvx = bool(shutil.which("uvx") or shutil.which("blender-mcp"))
        if not has_uvx:
            return False, -1, ("uvx / blender-mcp bulunamadı" if is_tr else "uvx / blender-mcp not found"), "PATH check failed", "fail"
        lbl = (
            f"Durduruldu — köprü hazır (:{port})" if is_tr else f"Stopped — bridge ready (:{port})"
        )
        return True, ms, lbl, f"Blender bridge binary verified; tools currently stopped.", "ready_stopped"

    if tool.id == "caveman":
        home = pathlib.Path.home()
        act_md = home / ".agents" / "skills" / "caveman" / "SKILL.md"
        dis_md = home / ".agents" / "skills_disabled" / "caveman" / "SKILL.md"
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        if act_md.is_file() or dis_md.is_file():
            src = act_md if act_md.is_file() else dis_md
            lbl = "Durduruldu — SKILL.md diskte hazır" if is_tr else "Stopped — SKILL.md ready on disk"
            return True, ms, lbl, str(src), "ready_stopped"
        return False, -1, ("SKILL.md eksik (kurulu değil)" if is_tr else "SKILL.md missing (not installed)"), str(act_md), "fail"

    if tool.id == "blender_skills":
        plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
        ok = (plugin_dir / "skills").is_dir() or (plugin_dir / "skills_disabled").is_dir()
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        if ok:
            lbl = (
                f"Durduruldu — {active_skills_count}/94 skill diskte hazır"
                if is_tr
                else f"Stopped — {active_skills_count}/94 skills ready on disk"
            )
            return True, ms, lbl, str(plugin_dir), "ready_stopped"
        return False, -1, ("Blender Skills kurulu değil" if is_tr else "Blender Skills not installed"), str(plugin_dir), "fail"

    if _is_custom_skill_tool(tool):
        home = pathlib.Path.home()
        act_dir = home / ".agents" / "skills" / tool.id
        dis_dir = home / ".agents" / "skills_disabled" / tool.id
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        if act_dir.is_dir() or dis_dir.is_dir():
            src = act_dir if act_dir.is_dir() else dis_dir
            lbl = "Durduruldu — skill diskte hazır" if is_tr else "Stopped — skill ready on disk"
            return True, ms, lbl, str(src), "ready_stopped"
        lbl = "Skill kurulu değil (eksik)" if is_tr else "Skill not installed (missing)"
        return False, -1, lbl, str(act_dir), "fail"

    if tool.mcp_command or getattr(tool, "auth_mode", "key") == "oauth":
        is_oauth = getattr(tool, "auth_mode", "key") == "oauth" and supports_oauth(tool.id)
        if (
            not is_oauth
            and tool.vault_key_name
            and vault.is_locked()
            and (tool.vault_key_required or vault.has_key_entry(tool.vault_key_name))
        ):
            lbl = "Kasa kilitli (PIN girin)" if is_tr else "Vault is locked (enter Master Passphrase)"
            return False, -1, lbl, f"Vault locked for {tool.vault_key_name}", "fail"

        if not is_tool_credential_ready(tool, vault):
            lbl = (
                f"Kimlik doğrulama eksik ({tool.vault_key_name or 'OAuth'})"
                if is_tr
                else f"Missing credential ({tool.vault_key_name or 'OAuth'})"
            )
            return False, -1, lbl, "Configure API key or OAuth first.", "fail"

        ospec = get_oauth_spec(tool.id) if is_oauth else None
        if ospec is not None and ospec.kind == "remote_mcp":
            npx_bin = shutil.which("npx.cmd") or shutil.which("npx")
            ms = max(1, int((time.perf_counter() - t0) * 1000))
            if not npx_bin:
                lbl = "Komut bulunamadı: npx" if is_tr else "Command not found: npx"
                return False, -1, lbl, "Node.js (npx) is required for mcp-remote OAuth.", "fail"
            lbl = (
                f"Ön kontrol OK — OAuth köprüsü hazır ({ms}ms — durduruldu)"
                if is_tr
                else f"Dry-run OK — OAuth bridge ready ({ms}ms — stopped)"
            )
            return True, ms, lbl, f"npx={npx_bin} | url={ospec.remote_mcp_url} (side-effect-free dry-run)", "ready_stopped"

        spec = build_effective_stdio_spec(tool, vault, wrap_windows_npx=False)
        if spec is None:
            return False, -1, ("Yapılandırma eksik" if is_tr else "Configuration missing"), tool.name, "fail"
        raw_bin, eff_args, _eff_env = spec
        cmd_bin = raw_bin if pathlib.Path(raw_bin).is_file() else (shutil.which(f"{raw_bin}.cmd") or shutil.which(raw_bin))
        if not cmd_bin:
            lbl = f"Komut bulunamadı: {raw_bin}" if is_tr else f"Command not found: {raw_bin}"
            return False, -1, lbl, f"'{raw_bin}' is not on PATH.", "fail"
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        dry_lbl = (
            f"Ön kontrol OK — ikili hazır ({ms}ms — durduruldu)"
            if is_tr
            else f"Dry-run OK — binary & auth ready ({ms}ms — stopped)"
        )
        return True, ms, dry_lbl, f"binary={cmd_bin} | args={eff_args} (side-effect-free dry-run)", "ready_stopped"

    ok, ms, msg, raw = test_tool_connection_e2e(tool, vault, projects_map, active_skills_count, lang=lang)
    return ok, ms, (f"{msg} (durduruldu)" if (ok and is_tr) else (f"{msg} (stopped)" if ok else msg)), raw, (
        "ready_stopped" if ok else "fail"
    )


def test_tool_for_client_e2e(
    tool: ToolSpec,
    client_code: str,
    vault: WindowsDpapiVault,
    projects_map: dict[str, str],
    active_skills_count: int = 0,
    runtime_active: bool = True,
    lang: str = "en",
) -> tuple[bool, int, str, str, str]:
    """Run live or dry-run diagnostics either globally ('ALL') or strictly against one client ('AGY'/'CDX'/'CLD'/'CUR').

    Returns (ok, latency_ms, short_summary, technical_detail, badge_state).
    ``badge_state`` is one of: 'pass', 'ready_stopped', 'stopped', 'off_client', 'fail'.
    """
    is_tr = lang == "tr"
    code = (client_code or "ALL").upper()
    t0 = time.perf_counter()
    app_ver = get_current_app_version()

    if code == "ALL":
        if not runtime_active:
            return _check_dry_run_readiness(tool, vault, projects_map, active_skills_count, lang=lang)
        ok, ms, msg, raw = test_tool_connection_e2e(tool, vault, projects_map, active_skills_count, lang=lang)
        return ok, ms, msg, raw, ("pass" if ok else "fail")

    # Per-client verification (AGY / CDX / CLD / CUR)
    parse_ok, cfg_msg, active_servers, disabled_keys, cfg_path = inspect_client_config_file(
        code, projects_map=projects_map, lang=lang
    )
    if not parse_ok:
        return False, -1, cfg_msg, f"File: {cfg_path}\n{cfg_msg}", "fail"

    client_allowed = bool(tool.clients.get(code, False))
    home = pathlib.Path.home()

    # Skill / Rule per-client checks
    if tool.id == "caveman":
        target_md = (
            home / ".gemini" / "config" / "skills" / "caveman" / "SKILL.md"
            if code == "AGY"
            else home / ".agents" / "skills" / "caveman" / "SKILL.md"
        )
        exists_for_client = target_md.is_file()
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        if not client_allowed:
            if exists_for_client:
                lbl = (
                    f"Sızıntı: {code} kapalı ama SKILL.md hâlâ aktif!"
                    if is_tr
                    else f"Leak: {code} disabled but SKILL.md is still active!"
                )
                return False, ms, lbl, str(target_md), "fail"
            lbl = (
                f"{code} için kapalı (doğrulandı)" if is_tr else f"Disabled for {code} (verified)"
            )
            return True, ms, lbl, f"Verified absent: {target_md}", "off_client"
        if not runtime_active:
            if exists_for_client:
                lbl = (
                    f"Uyarı: Durduruldu ama {code} SKILL.md hâlâ aktif"
                    if is_tr
                    else f"Warning: Stopped but {code} SKILL.md still active"
                )
                return False, ms, lbl, str(target_md), "fail"
            return _check_dry_run_readiness(tool, vault, projects_map, active_skills_count, lang=lang)
        if exists_for_client:
            lbl = (
                f"{code} SKILL.md doğrulandı" if is_tr else f"{code} SKILL.md verified"
            )
            return True, ms, lbl, str(target_md), "pass"
        lbl = (
            f"{code} skill dizininde eksik!" if is_tr else f"Missing in {code} skills directory!"
        )
        return False, -1, lbl, f"Expected: {target_md}", "fail"

    if tool.id == "blender_skills":
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        is_global = tool.project_scope == "GLOBAL" or not projects_map or tool.project_scope not in projects_map
        if is_global:
            if code == "AGY":
                plugin_skills = home / ".gemini" / "config" / "plugins" / "blender-skills" / "skills"
                exists_for_client = plugin_skills.is_dir() and any(
                    d.is_dir() and d.name != "references" for d in plugin_skills.iterdir()
                )
                target_path_str = str(plugin_skills)
            else:
                ag_root = home / ".agents" / "skills"
                exists_for_client = ag_root.is_dir() and any(
                    d.is_dir() and d.name.startswith("blender-skills__") for d in ag_root.iterdir()
                )
                target_path_str = str(ag_root / "blender-skills__*")
        else:
            p_skills = pathlib.Path(projects_map[tool.project_scope]) / ".agents" / "skills"
            exists_for_client = p_skills.is_dir() and any(
                d.is_dir() and (d / ".aiconomy_managed").is_file() for d in p_skills.iterdir()
            )
            target_path_str = str(p_skills)

        if not client_allowed:
            if exists_for_client and is_global:
                lbl = (
                    f"Sızıntı: {code} kapalı ama Blender skill'leri hâlâ aktif!"
                    if is_tr
                    else f"Leak: {code} disabled but Blender skills are still active!"
                )
                return False, ms, lbl, target_path_str, "fail"
            lbl = f"{code} için kapalı (doğrulandı)" if is_tr else f"Disabled for {code} (verified)"
            return True, ms, lbl, target_path_str, "off_client"
        if not runtime_active:
            if exists_for_client:
                lbl = (
                    f"Uyarı: Durduruldu ama {code} Blender skill'leri hâlâ aktif!"
                    if is_tr
                    else f"Warning: Stopped but {code} Blender skills still active!"
                )
                return False, ms, lbl, target_path_str, "fail"
            return _check_dry_run_readiness(tool, vault, projects_map, active_skills_count, lang=lang)
        if exists_for_client:
            lbl = (
                f"{code} için {active_skills_count}/94 skill aktif"
                if is_tr
                else f"{active_skills_count}/94 skills active for {code}"
            )
            return True, ms, lbl, target_path_str, "pass"
        return False, -1, ("Aktif Blender skill bulunamadı" if is_tr else "No active Blender skills found"), target_path_str, "fail"

    if _is_custom_skill_tool(tool):
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        if code == "AGY":
            exists_for_client = _has_agy_skill_mirror_on_disk(home, tool.id)
            target_desc = str(home / ".gemini" / "config" / "skills" / tool.id)
        else:
            act_dir = home / ".agents" / "skills" / tool.id
            exists_for_client = act_dir.is_dir()
            target_desc = str(act_dir)

        if not client_allowed:
            if exists_for_client:
                lbl = (
                    f"Sızıntı: {code} kapalı ama skill dizini hâlâ aktif!"
                    if is_tr
                    else f"Leak: {code} disabled but skill folder is still active!"
                )
                return False, ms, lbl, target_desc, "fail"
            return True, ms, (f"{code} için kapalı (doğrulandı)" if is_tr else f"Disabled for {code} (verified)"), target_desc, "off_client"
        if not runtime_active:
            if exists_for_client:
                lbl = (
                    f"Uyarı: Durduruldu ama {code} skill dizini hâlâ aktif!"
                    if is_tr
                    else f"Warning: Stopped but {code} skill folder still active!"
                )
                return False, ms, lbl, target_desc, "fail"
            return _check_dry_run_readiness(tool, vault, projects_map, active_skills_count, lang=lang)
        if exists_for_client:
            return True, ms, (f"{code} skill doğrulandı" if is_tr else f"{code} skill verified"), target_desc, "pass"
        return False, -1, (f"{code} skill dizininde eksik!" if is_tr else f"Missing in {code} skills directory!"), target_desc, "fail"

    # CLI-only tools (no MCP server key)
    if not tool.mcp_server_key:
        if not client_allowed:
            return True, 1, (f"{code} için kapalı" if is_tr else f"Disabled for {code}"), tool.name, "off_client"
        if not runtime_active:
            return _check_dry_run_readiness(tool, vault, projects_map, active_skills_count, lang=lang)
        ok, ms, msg, raw = test_tool_connection_e2e(tool, vault, projects_map, active_skills_count, lang=lang)
        return ok, ms, msg, raw, ("pass" if ok else "fail")

    # MCP tool per-client check (AGY / CDX / CLD / CUR)
    lookup_keys = [tool.mcp_server_key]
    if tool.id == "unity_mcp" and "unityMCP" not in lookup_keys:
        lookup_keys.append("unityMCP")

    found_key = next((k for k in lookup_keys if k in active_servers), "")
    is_disabled_in_cfg = any(k in disabled_keys for k in lookup_keys)
    ms_now = max(1, int((time.perf_counter() - t0) * 1000))

    if not client_allowed:
        if found_key:
            lbl = (
                f"Sızıntı: {code} kapalı ama {cfg_path.name} içinde hâlâ kayıtlı!"
                if is_tr
                else f"Leak: {code} disabled but still registered in {cfg_path.name}!"
            )
            return False, ms_now, lbl, f"{cfg_path}\nentry={active_servers[found_key]}", "fail"
        lbl = f"{code} için kapalı (config temiz)" if is_tr else f"Disabled for {code} (config clean)"
        return True, ms_now, lbl, f"{cfg_path}: not registered", "off_client"

    if not runtime_active:
        if found_key:
            lbl = (
                f"Uyarı: Durduruldu ama {cfg_path.name} içinde hâlâ aktif!"
                if is_tr
                else f"Warning: Stopped but still active in {cfg_path.name}!"
            )
            return False, ms_now, lbl, f"{cfg_path}\nentry={active_servers[found_key]}", "fail"
        ok_d, ms_d, msg_d, raw_d, st_d = _check_dry_run_readiness(tool, vault, projects_map, active_skills_count, lang=lang)
        note_clean = f" | {code} config temiz" if is_tr else f" | {code} config paused"
        return ok_d, ms_d, f"{msg_d}{note_clean}", f"{cfg_path}\n{raw_d}", st_d

    # Running & client allowed: entry MUST exist in client's actual config file!
    if not found_key:
        if is_disabled_in_cfg:
            lbl = (
                f"{cfg_path.name} içinde enabled = false!"
                if is_tr
                else f"Marked enabled = false in {cfg_path.name}!"
            )
        else:
            lbl = (
                f"{code} config dosyasında ({cfg_path.name}) kayıtlı değil!"
                if is_tr
                else f"Not registered in {code} config ({cfg_path.name})!"
            )
        return False, -1, lbl, f"Checked {cfg_path} for keys {lookup_keys}", "fail"

    entry = active_servers[found_key]
    cfg_note = f" | {code} config OK ({found_key})"
    ok_l, ms_l, msg_l, raw_l = _test_config_entry_live(entry, t0, cfg_note, app_ver=app_ver, lang=lang)
    return ok_l, ms_l, msg_l, f"Config: {cfg_path} [{found_key}]\n{raw_l}", ("pass" if ok_l else "fail")
