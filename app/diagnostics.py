"""End-to-end live MCP connection diagnostics (HTTP JSON-RPC, Blender socket, stdio handshake)."""
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
from .storage import WindowsDpapiVault
from .updater import get_current_app_version


def test_tool_connection_e2e(
    tool: ToolSpec,
    vault: WindowsDpapiVault,
    projects_map: dict[str, str],
    active_skills_count: int = 0,
) -> tuple[bool, int, str, str]:
    """Run an end-to-end connection probe even when AI IDEs are closed.

    Returns (ok, latency_ms, short_summary, technical_detail).
    """
    t0 = time.perf_counter()
    cfg_note = ""
    if tool.mcp_server_key:
        agy_cfg = pathlib.Path.home() / ".gemini" / "config" / "mcp_config.json"
        if agy_cfg.is_file():
            try:
                servers = json.loads(agy_cfg.read_text(encoding="utf-8") or "{}").get("mcpServers", {})
                in_agy = tool.mcp_server_key in servers
                if tool.enabled and tool.clients.get("AGY") and not in_agy:
                    cfg_note = " | AGY mcp_config.json missing"
                elif in_agy:
                    cfg_note = " | AGY Config OK"
            except Exception:
                pass

    if not tool.enabled:
        return False, -1, "Panelde KAPALI (Test atlandı)", "Araç devre dışı bırakılmış; önce AÇIK yapın."

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
                return False, ms, f"Beklenmeyen yanıt (HTTP {resp.status})", body[:400]
        except urllib.error.HTTPError as exc:
            ms = max(1, int((time.perf_counter() - t0) * 1000))
            err_b = exc.read(512).decode("utf-8", errors="replace")
            if exc.code in (400, 405, 406):
                return True, ms, f"HTTP Sunucu Aktif ({ms}ms, HTTP {exc.code}){cfg_note}", f"{url} ayakta: {err_b}"
            return False, -1, f"HTTP Hata {exc.code}", err_b
        except Exception as exc:
            return False, -1, f"Bağlantı Yok (:{port})", f"{url} yanıt vermiyor: {exc}"

    if tool.id == "blender_mcp":
        port = int(tool.port or 9876)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5) as s:
                s.settimeout(2.5)
                s.sendall(b'{"type":"get_scene_info","params":{}}')
                resp = s.recv(4096).decode("utf-8", errors="replace")
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                if "result" in resp or "status" in resp or "name" in resp:
                    return True, ms, f"Blender Sahne Yanıtı OK ({ms}ms){cfg_note}", resp[:400]
                return False, ms, "Soket açık ama sahne yanıtı boş", resp[:300]
        except Exception as exc:
            return False, -1, f"Blender :{port} Bağlanamadı", f"Blender açık ve BlenderMCP bağlı değil: {exc}"

    if tool.id == "trellis":
        port = int(tool.port or 8790)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                return True, ms, f"Trellis GPU Sunucusu Açık ({ms}ms)", f"127.0.0.1:{port} bağlantısı başarılı."
        except OSError:
            cli_exe = pathlib.Path(tool.param_value) / "runtime" / "trellis-cli.exe"
            if cli_exe.is_file():
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                return True, ms, f"CLI Hazır · Sunucu Uykuda ({ms}ms)", f"{cli_exe} doğrulandı."
            return False, -1, "Trellis kurulumu bulunamadı", f"Kontrol edilen yol: {cli_exe}"

    if tool.mcp_command:
        cmd_bin = shutil.which(f"{tool.mcp_command}.cmd") or shutil.which(tool.mcp_command)
        if not cmd_bin:
            return False, -1, f"Komut bulunamadı: {tool.mcp_command}", f"PATH üzerinde '{tool.mcp_command}' yok."
        if tool.vault_key_name and not vault.has_secret(tool.vault_key_name):
            return False, -1, f"API Anahtarı Eksik ({tool.vault_key_name})", "API Keys ayarlarından anahtarı ekleyin."

        env = os.environ.copy()
        if tool.vault_key_name:
            sec = vault.get_secret(tool.vault_key_name)
            if sec:
                env[tool.vault_key_name] = sec

        return _run_stdio_handshake(cmd_bin, tool.mcp_args, env, t0, cfg_note, app_ver)

    if tool.id == "blender_skills":
        plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
        ok = (plugin_dir / "skills").is_dir()
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        return ok, ms, f"{active_skills_count}/94 Skill Diskte Hazır" if ok else "Kurulmamış", str(plugin_dir)

    if tool.id == "caveman":
        skill_md = pathlib.Path.home() / ".agents" / "skills" / "caveman" / "SKILL.md"
        ok = skill_md.is_file()
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        return ok, ms, "SKILL.md Doğrulandı" if ok else "SKILL.md Eksik", str(skill_md)

    if tool.id == "unity_pipeline":
        target_proj = projects_map.get(tool.project_scope, tool.param_value)
        manifest = pathlib.Path(target_proj) / "Packages" / "manifest.json"
        ok = manifest.is_file() and "com.unity.pipeline" in manifest.read_text(encoding="utf-8", errors="ignore")
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        return ok, ms, "Unity Pipeline Paketi Doğrulandı" if ok else "Paket Eksik", str(manifest)

    return True, 1, "Hazır", tool.summary


def _run_stdio_handshake(
    cmd_bin: str,
    args: list[str],
    env: dict[str, str],
    t0: float,
    cfg_note: str,
    app_ver: str = "1.0.0",
) -> tuple[bool, int, str, str]:
    """Send a JSON-RPC initialize message over stdio and read the response with timeout."""
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
            return True, ms, f"stdio Süreç Başladı ({ms}ms){cfg_note}", "Süreç ayakta; ilk yanıt beklenenden uzun sürdü."
        return False, -1, f"stdio Çıkış Kodu {rc}", err_txt or joined or "Süreç erken kapandı."
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
