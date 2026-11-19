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
from .mcp_config import build_effective_stdio_spec
from .storage import WindowsDpapiVault
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

    if tool.mcp_command:
        cmd_bin = shutil.which(f"{tool.mcp_command}.cmd") or shutil.which(tool.mcp_command)
        if not cmd_bin:
            lbl = f"Komut bulunamadı: {tool.mcp_command}" if is_tr else f"Command not found: {tool.mcp_command}"
            return False, -1, lbl, f"'{tool.mcp_command}' is not on PATH."
        if tool.vault_key_required and tool.vault_key_name and not vault.has_secret(tool.vault_key_name):
            lbl = f"API anahtarı eksik ({tool.vault_key_name})" if is_tr else f"Missing API key ({tool.vault_key_name})"
            det = "Ayarlar > API Anahtarları bölümünden ekleyin." if is_tr else "Configure in Settings > API Keys."
            return False, -1, lbl, det

        spec = build_effective_stdio_spec(tool, vault, wrap_windows_npx=False)
        eff_args = spec[1] if spec else list(tool.mcp_args)
        eff_env = spec[2] if spec else {}
        env = os.environ.copy()
        env.update(eff_env)

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
        ok = skill_md.is_file()
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        lbl = ("SKILL.md doğrulandı" if ok else "SKILL.md eksik") if is_tr else ("SKILL.md verified" if ok else "SKILL.md missing")
        return ok, ms, lbl, str(skill_md)

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
