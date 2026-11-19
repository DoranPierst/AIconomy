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
import urllib.error
import urllib.request

from .catalog import ToolSpec
from .host_apps import NO_WINDOW
from .mcp_config import build_effective_stdio_spec, is_tool_credential_ready
from .security import build_isolated_child_env
from .storage import WindowsDpapiVault
from .tokens import estimate_tokens_from_tools_payload
from .updater import get_current_app_version


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
        ok = skill_md.is_file() and (not tool.clients.get("AGY", True) or agy_md.is_file())
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        if skill_md.is_file() and tool.clients.get("AGY", True) and not agy_md.is_file():
            lbl = "AGY skill senkronu eksik" if is_tr else "AGY skill mirror missing"
            return False, ms, lbl, f"{skill_md} -> {agy_md}"
        lbl = ("SKILL.md doğrulandı" if ok else "SKILL.md eksik") if is_tr else ("SKILL.md verified" if ok else "SKILL.md missing")
        det = f"{skill_md} | AGY: {agy_md}" if agy_md.is_file() else str(skill_md)
        return ok, ms, lbl, det

    if tool.id == "unity_pipeline":
        target_proj = projects_map.get(tool.project_scope, tool.param_value)
        manifest = pathlib.Path(target_proj) / "Packages" / "manifest.json"
        ok = manifest.is_file() and "com.unity.pipeline" in manifest.read_text(encoding="utf-8", errors="ignore")
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        lbl = ("Paket doğrulandı" if ok else "Paket eksik") if is_tr else ("Package verified" if ok else "Package missing")
        return ok, ms, lbl, str(manifest)

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
        rt.join(timeout=5.5)
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
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


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
        try:
            proc.terminate()
            proc.wait(timeout=1.2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return None
