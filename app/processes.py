"""Process, port, GPU VRAM, visible GUI window detection, and live health probing."""
from __future__ import annotations

import csv
import ctypes
from ctypes import wintypes
import io
import os
import pathlib
import shutil
import socket
import subprocess
import time
import urllib.request

import psutil

from .catalog import ToolSpec
from .host_apps import NO_WINDOW, _find_blender_exe

PROTECTED_EXES = {"unity.exe", "blender.exe", "code.exe", "antigravity.exe", "explorer.exe"}
_PY_HOST_EXES = {"python.exe", "pythonw.exe", "uv.exe", "uvx.exe"}

_IGNORED_WIN_TITLES = {
    "",
    "n/a",
    "yok",
    "default ime",
    "msctfime ui",
    "olemainthreadwndname",
    "pyinstaller onefile hidden window",
}


def query_gpu_vram() -> tuple[str, int, int]:
    """Return (gpu_name, used_mb, total_mb) from nvidia-smi, or ('', 0, 0) when unavailable."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2.5,
            creationflags=NO_WINDOW,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            line = proc.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                return parts[0], int(float(parts[1])), int(float(parts[2]))
    except Exception:
        pass
    return "GPU Algılanamadı", 0, 0


def _is_interactive_default_desktop() -> bool:
    """Return True when the current thread runs on the interactive Windows 'Default' desktop."""
    if os.name != "nt":
        return False
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        hdesk = u32.GetThreadDesktop(k32.GetCurrentThreadId())
        if not hdesk:
            return False
        buf = ctypes.create_unicode_buffer(128)
        needed = wintypes.DWORD(0)
        if u32.GetUserObjectInformationW(hdesk, 2, buf, 256, ctypes.byref(needed)):
            return buf.value.strip().lower() == "default"
    except Exception:
        pass
    return False


def get_gui_window_titles(target_pids_by_img: dict[str, list[int]] | None = None) -> dict[int, str]:
    """Return {pid: window_title} for processes owning a visible (WS_VISIBLE) top-level window."""
    titles: dict[int, str] = {}
    if os.name != "nt":
        return titles
    if target_pids_by_img is not None and not target_pids_by_img:
        return titles

    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

        @WNDENUMPROC
        def _enum_cb(hwnd: int, _lparam: int) -> bool:
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    t_str = buf.value.strip()
                    if t_str and t_str.lower() not in _IGNORED_WIN_TITLES and "hidden window" not in t_str.lower():
                        pid = wintypes.DWORD(0)
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        if pid.value and int(pid.value) not in titles:
                            titles[int(pid.value)] = t_str
            return True

        user32.EnumWindows(_enum_cb, 0)
    except Exception:
        pass

    if _is_interactive_default_desktop():
        return titles

    imgs = set(target_pids_by_img.keys()) if target_pids_by_img is not None else {"blender.exe", "Unity.exe"}
    for img in imgs:
        try:
            proc = subprocess.run(
                ["tasklist", "/v", "/fo", "csv", "/nh", "/fi", f"IMAGENAME eq {img}"],
                capture_output=True,
                text=True,
                timeout=2.5,
                creationflags=NO_WINDOW,
            )
            for row in csv.reader(io.StringIO(proc.stdout)):
                if len(row) >= 9 and row[1].isdigit():
                    w_title = row[8].strip()
                    if w_title and w_title.lower() not in _IGNORED_WIN_TITLES and "hidden window" not in w_title.lower():
                        titles[int(row[1])] = w_title
        except Exception:
            pass
    return titles


def detect_running_dcc_apps() -> dict[str, bool]:
    """Detect whether Unity Editor, Blender (visible GUI window), or TRELLIS server is running."""
    running = {"unity": False, "blender": False, "trellis_server": False}
    pids_by_img: dict[str, list[int]] = {}
    candidates: list[tuple[int, str, str]] = []
    try:
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            nm = (proc.info.get("name") or "").lower()
            pid = int(proc.info.get("pid") or 0)
            exe = (proc.info.get("exe") or "").lower()
            if nm == "unity.exe" and "unity hub" not in exe:
                pids_by_img.setdefault("Unity.exe", []).append(pid)
                candidates.append((pid, "unity", exe))
            elif nm == "blender.exe":
                pids_by_img.setdefault("blender.exe", []).append(pid)
                candidates.append((pid, "blender", exe))
            elif nm == "trellis-server.exe":
                running["trellis_server"] = True
    except Exception:
        pass

    if pids_by_img:
        win_titles = get_gui_window_titles(pids_by_img)
        for pid, kind, _exe in candidates:
            if pid in win_titles:
                running[kind] = True
    return running


def scan_live_process_locations() -> dict[str, str]:
    """Inspect active managed and DCC processes to determine live project paths and window states."""
    live: dict[str, str] = {}
    dcc_procs: list[tuple[int, str, str, list[str]]] = []
    pids_by_img: dict[str, list[int]] = {}

    for proc in psutil.process_iter():
        try:
            nm = (proc.name() or "").lower()
            if nm not in (
                "serena.exe",
                "python.exe",
                "pythonw.exe",
                "unity.exe",
                "blender.exe",
                "blender-mcp.exe",
                "trellis-server.exe",
                "qrenderdoc.exe",
            ):
                continue
            exe = proc.exe() or ""
            cmdline = proc.cmdline() or []
            pid = proc.pid
            cmd_joined = " ".join(cmdline)

            if nm == "serena.exe" or (
                "python" in nm and "serena" in cmd_joined.lower() and "start-mcp-server" in cmd_joined.lower()
            ):
                proj_val = ""
                for idx, arg in enumerate(cmdline):
                    if arg == "--project" and idx + 1 < len(cmdline):
                        proj_val = cmdline[idx + 1]
                        break
                    if arg.startswith("--project="):
                        proj_val = arg.split("=", 1)[1]
                        break
                if proj_val:
                    live["serena"] = f"🟢 Canlı Proje: {proj_val}  |  Süreç: {exe or nm} (PID {pid})"
                else:
                    live["serena"] = f"🟢 Çalışıyor: {exe or nm} (PID {pid})"

            elif nm == "unity.exe":
                if "unity hub" in exe.lower():
                    continue
                pids_by_img.setdefault("Unity.exe", []).append(pid)
                dcc_procs.append((pid, "unity", exe, cmdline))

            elif nm == "blender.exe":
                pids_by_img.setdefault("blender.exe", []).append(pid)
                dcc_procs.append((pid, "blender", exe, cmdline))

            elif nm == "blender-mcp.exe":
                live["blender_mcp_bridge_pid"] = str(pid)

            elif nm == "trellis-server.exe":
                live["trellis"] = f"🟢 GPU Sunucu Aktif: {exe} (PID {pid})"

            elif nm == "qrenderdoc.exe":
                live["renderdoc_open"] = "1"
                live["renderdoc"] = f"🟢 RenderDoc Açık: {exe} (PID {pid})"
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue

    win_titles = get_gui_window_titles(pids_by_img) if pids_by_img else {}

    for pid, kind, exe, cmdline in dcc_procs:
        w_title = win_titles.get(pid, "")
        if kind == "unity":
            proj_val = ""
            for idx, arg in enumerate(cmdline):
                if arg.lower() == "-projectpath" and idx + 1 < len(cmdline):
                    proj_val = cmdline[idx + 1]
                    break
            if w_title or proj_val:
                live["unity_open"] = "1"
                if proj_val:
                    live["unity"] = f"🟢 Açık Unity Projesi: {proj_val} (PID {pid})"
                else:
                    live["unity"] = f"🟢 Unity Editör Açık: {w_title} (PID {pid})"

        elif kind == "blender":
            blend_files = [a for a in cmdline if a.lower().endswith(".blend")]
            if w_title:
                live["blender_open"] = "1"
                live["blender_pid"] = str(pid)
                live["blender_title"] = w_title
                if blend_files:
                    live["blender"] = f"🟢 Açık Sahne: {blend_files[0]}  |  {w_title} (PID {pid})"
                else:
                    live["blender"] = f"🟢 Blender Açık: {w_title} (PID {pid})"
            elif "blender_open" not in live:
                live["blender_zombie_pid"] = str(pid)
                live["blender"] = (
                    f"⚠️ Penceresiz Asılı Süreç: blender.exe (PID {pid}) — Blender kapalı ama arka planda asılı kalmış!"
                )

    return live


def find_port_owner(port: int) -> tuple[int | None, str]:
    """Return (pid, process_name) for the TCP listener bound to ``port``, or (None, '')."""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                pid = conn.pid
                if pid:
                    try:
                        p = psutil.Process(pid)
                        return pid, p.name()
                    except Exception:
                        return pid, "bilinmeyen-süreç"
    except Exception:
        pass
    return None, ""


def kill_zombie_port_process(port: int) -> tuple[bool, str]:
    """Terminate a stuck background server holding ``port`` while protecting visible GUI editors."""
    cleaned_extra: list[str] = []
    if port == 9876:
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                nm = (p.info.get("name") or "").lower()
                cmd_s = " ".join(str(x).lower() for x in (p.info.get("cmdline") or []))
                if nm == "blender-mcp.exe" or (nm in ("uv.exe", "uvx.exe") and "blender-mcp" in cmd_s):
                    p.terminate()
                    cleaned_extra.append(f"{nm} (PID {p.info['pid']})")
            except Exception:
                pass

    pid, name = find_port_owner(port)
    if not pid:
        if cleaned_extra:
            return True, f"Asılı köprü temizlendi: {', '.join(cleaned_extra)}."
        return False, f"Port {port} üzerinde dinleyen aktif bir süreç bulunamadı."

    win_titles = get_gui_window_titles({name: [pid]}) if name.lower() in PROTECTED_EXES else {}
    if name.lower() in PROTECTED_EXES and pid in win_titles:
        return (
            False,
            f"Port {port} şu an ekranda açık olan '{win_titles[pid]}' (PID {pid}) tarafından kullanılıyor. Sahne kaybını önlemek için açık editör kapatılmadı.",
        )
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except psutil.TimeoutExpired:
            proc.kill()
        extra_note = f" + {', '.join(cleaned_extra)}" if cleaned_extra else ""
        return True, f"Port {port} üzerindeki penceresiz/asılı süreç ({name}, PID {pid}{extra_note}) temizlendi."
    except Exception as exc:
        return False, f"PID {pid} ({name}) sonlandırılamadı: {exc}"


def _find_managed_processes(
    exe_names: set[str],
    host_keywords: tuple[str, ...] = (),
    require_all: tuple[str, ...] = (),
) -> list[psutil.Process]:
    """Find only processes explicitly managed by AIconomy (by executable name or Python/uv cmdline).

    Never matches by port ownership alone so unrelated user servers (e.g. Vite/Tomcat on :8080)
    are never targeted.
    """
    out: list[psutil.Process] = []
    self_pid = os.getpid()
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info.get("pid") == self_pid:
                continue
            nm = (p.info.get("name") or "").lower()
            if nm in exe_names:
                out.append(p)
                continue
            if nm in _PY_HOST_EXES and host_keywords:
                cmd_s = " ".join(str(x).lower() for x in (p.info.get("cmdline") or []))
                if any(k in cmd_s for k in host_keywords) and all(k in cmd_s for k in require_all):
                    out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return out


def _terminate_all(procs: list[psutil.Process], label: str) -> list[str]:
    stopped: list[str] = []
    for p in procs:
        try:
            p.terminate()
            stopped.append(f"{label} (PID {p.pid})")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return stopped


def enforce_tool_runtime_state(tool: ToolSpec, projects_map: dict[str, str], allow_stop: bool = True) -> str:
    """Align managed background bridge processes with a tool's enabled state.

    When ``allow_stop=False`` (e.g. app startup), no process is terminated; only enabled bridges
    are started if needed. Stop actions strictly target managed bridge executables/cmdlines.
    """
    if tool.id == "blender_mcp" and not tool.enabled:
        if not allow_stop:
            return ""
        killed = _terminate_all(
            _find_managed_processes({"blender-mcp.exe"}, host_keywords=("blender-mcp",)),
            "blender-mcp",
        )
        owner_pid, owner_name = find_port_owner(int(tool.port or 9876))
        if owner_pid and owner_name.lower() == "blender.exe":
            try:
                bproc = psutil.Process(owner_pid)
                cmd = [str(x).lower() for x in (bproc.cmdline() or [])]
                is_batch_job = "-b" in cmd or "--background" in cmd
                has_window = owner_pid in get_gui_window_titles({"blender.exe": [owner_pid]})
                if not is_batch_job and not has_window:
                    bproc.terminate()
                    killed.append(f"asılı blender.exe (PID {owner_pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return f" ({', '.join(killed)} durduruldu)" if killed else ""

    if tool.id == "trellis" and not tool.enabled:
        if not allow_stop:
            return ""
        ok, msg = free_trellis_vram()
        return f" ({msg})" if ok and "PID" in msg else ""

    if tool.id == "unity_mcp":
        port = int(tool.port or 8080)
        if not tool.enabled:
            if not allow_stop:
                return ""
            killed = _terminate_all(
                _find_managed_processes(
                    {"mcp-for-unity.exe", "unity-mcp.exe"},
                    host_keywords=("mcp-for-unity", "mcpforunityserver", "unity-mcp"),
                ),
                "Unity MCP",
            )
            return f" ({', '.join(killed)} durduruldu)" if killed else ""
        owner_pid, _owner_name = find_port_owner(port)
        if not owner_pid:
            local_bin = pathlib.Path.home() / ".local" / "bin"
            cmd: list[str] | None = None
            for exe_name in ("mcp-for-unity.exe", "unity-mcp.exe"):
                cand = local_bin / exe_name
                if cand.is_file():
                    cmd = [str(cand), "--transport", "http", "--http-host", "127.0.0.1", "--http-port", str(port)]
                    break
            if cmd is None:
                which_exe = shutil.which("mcp-for-unity") or shutil.which("unity-mcp")
                if which_exe:
                    cmd = [which_exe, "--transport", "http", "--http-host", "127.0.0.1", "--http-port", str(port)]
                elif shutil.which("uvx"):
                    cmd = [
                        "uvx",
                        "--python",
                        "3.12",
                        "mcpforunityserver",
                        "--transport",
                        "http",
                        "--http-host",
                        "127.0.0.1",
                        "--http-port",
                        str(port),
                    ]
            if cmd:
                try:
                    subprocess.Popen(cmd, creationflags=NO_WINDOW)
                    return f" (Unity MCP :{port} otomatik başlatıldı)"
                except Exception:
                    return ""

    if tool.id == "serena":
        port = int(tool.port or 9121)
        if not tool.enabled:
            if not allow_stop:
                return ""
            killed = _terminate_all(
                _find_managed_processes(
                    {"serena.exe", "serena-agent.exe"},
                    host_keywords=("serena",),
                    require_all=("start-mcp-server",),
                ),
                "Serena",
            )
            return f" ({', '.join(killed)} durduruldu)" if killed else ""
        owner_pid, _ = find_port_owner(port)
        if not owner_pid:
            serena_exe = pathlib.Path.home() / ".local" / "bin" / "serena.exe"
            if serena_exe.is_file():
                cmd = [
                    str(serena_exe),
                    "start-mcp-server",
                    "--transport",
                    "streamable-http",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ]
                proj_dir = projects_map.get(tool.project_scope, "")
                if tool.project_scope != "GLOBAL" and proj_dir and pathlib.Path(proj_dir).is_dir():
                    cmd.extend(["--project", proj_dir])
                opt_map = {o.key: o.enabled for o in tool.options}
                if opt_map.get("no_dashboard", True):
                    cmd.extend(["--open-web-dashboard", "False", "--enable-gui-log-window", "False"])
                try:
                    subprocess.Popen(cmd, creationflags=NO_WINDOW)
                    return f" (Serena :{port} başlatıldı)"
                except Exception:
                    return ""
    return ""


def free_trellis_vram() -> tuple[bool, str]:
    """Terminate trellis-server.exe to release GPU VRAM."""
    stopped: list[int] = []
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            if (proc.info.get("name") or "").lower() == "trellis-server.exe":
                proc.terminate()
                stopped.append(proc.info["pid"])
    except Exception as exc:
        return False, f"Trellis kontrol hatası: {exc}"

    if not stopped:
        return True, "Trellis arka plan sunucusu zaten kapalı (VRAM boşta)."
    return True, f"Trellis sunucusu (PID {', '.join(map(str, stopped))}) kapatıldı ve GPU VRAM boşaltıldı."


def resolve_disk_location(tool: ToolSpec, projects_map: dict[str, str], live_map: dict[str, str]) -> str:
    """Resolve the active disk path or live process location string for a tool."""
    if tool.id == "serena":
        if "serena" in live_map:
            return live_map["serena"]
        exe = pathlib.Path.home() / ".local" / "bin" / "serena.exe"
        proj_dir = projects_map.get(tool.project_scope, "Global")
        return f"Kurulu: {exe if exe.is_file() else 'serena'}  |  Hedef: {proj_dir}"

    if tool.id in ("unity_mcp", "unity_pipeline"):
        if "unity" in live_map:
            return live_map["unity"]
        proj_dir = projects_map.get(tool.project_scope, tool.param_value)
        return f"Hedef Unity Klasörü: {proj_dir}"

    if tool.id == "blender_mcp":
        if "blender" in live_map:
            return live_map["blender"]
        b_exe = _find_blender_exe()
        return f"Kurulu: {b_exe}" if b_exe else "Blender köprüsü (:9876)"

    if tool.id == "trellis":
        if "trellis" in live_map:
            return live_map["trellis"]
        return f"Kurulum Konumu: {tool.param_value}"

    if tool.id == "blender_skills":
        if tool.project_scope != "GLOBAL" and tool.project_scope in projects_map:
            return f"Proje Skill Dizini: {pathlib.Path(projects_map[tool.project_scope]) / '.agents' / 'skills'}"
        return f"Global Plugin Dizini: {pathlib.Path.home() / '.gemini' / 'config' / 'plugins' / 'blender-skills'}"

    if tool.id == "caveman":
        skill_md = pathlib.Path.home() / ".agents" / "skills" / "caveman" / "SKILL.md"
        return f"Dosya Konumu: {skill_md}" if skill_md.is_file() else "Global Kural / Skill"

    if tool.scope_selectable and tool.project_scope != "GLOBAL" and tool.project_scope in projects_map:
        return f"Proje Klasörü: {projects_map[tool.project_scope]}"

    return "Kapsam: Tüm Projeler (Global Yapılandırma)"


def probe_tool_health(
    tool: ToolSpec,
    active_skills_count: int,
    projects_map: dict[str, str],
    live_map: dict[str, str],
) -> tuple[bool, str, int, str, str]:
    """Return (is_healthy, short_ping_str, latency_ms, detail_msg, location_detail)."""
    now_str = time.strftime("%H:%M:%S")
    loc_detail = resolve_disk_location(tool, projects_map, live_map)

    if tool.id == "blender_skills":
        plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
        installed = (plugin_dir / "skills").is_dir() or (plugin_dir / "skills_disabled").is_dir()
        tag = f"Aktif ({active_skills_count}/94)" if tool.enabled else "Paket Kapalı"
        if not installed:
            return tool.enabled, f"{tag} · Kurulmadı", 1, "Eklentiler sekmesinden tek tıkla indirilebilir.", loc_detail
        return tool.enabled, tag, 2, f"Disk üzerinde {active_skills_count} skill aktif.", loc_detail

    if tool.id == "caveman":
        skill_md = pathlib.Path.home() / ".agents" / "skills" / "caveman" / "SKILL.md"
        ok = skill_md.is_file()
        status = f"Aktif ({tool.modes[tool.mode_index].split()[0]})" if tool.enabled else "Kapalı"
        return ok and tool.enabled, status if ok else "Kurulu (Yerel)", 1, str(skill_md), loc_detail

    if tool.id == "blender_mcp":
        port = int(tool.port or 9876)
        blender_window_open = live_map.get("blender_open") == "1"
        blender_pid = live_map.get("blender_pid", "")
        zombie_pid = live_map.get("blender_zombie_pid", "")
        if not tool.enabled:
            if blender_window_open and blender_pid:
                state_lbl = f"Devre Dışı (Blender PID {blender_pid} Açık)"
            elif zombie_pid:
                state_lbl = f"Devre Dışı (Asılı PID {zombie_pid})"
            else:
                state_lbl = "Devre Dışı"
            return False, state_lbl, -1, "Panelde KAPALI durumda (AI yapılandırmasından çıkarıldı ve köprü durduruldu).", loc_detail

        if not blender_window_open:
            if zombie_pid:
                return (
                    False,
                    f"⚠️ Blender Kapalı (Asılı PID {zombie_pid})",
                    -1,
                    f"Blender penceresi kapalı; ancak arka planda asılı kalan blender.exe (PID {zombie_pid}) port :{port} tutuyor. Port Kurtarıcı ile temizleyebilirsiniz.",
                    loc_detail,
                )
            return False, f"⏸️ Blender Kapalı (:{port})", -1, "Açık bir Blender penceresi bulunamadı.", loc_detail

        t0 = time.perf_counter()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.65):
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                return True, f"Çalışıyor ({ms}ms)", ms, f"Blender açık ({live_map.get('blender_title', '')}) ve 127.0.0.1:{port} soketi aktif.", loc_detail
        except OSError as exc:
            return (
                False,
                f"Blender Açık · Soket Kapalı (:{port})",
                -1,
                f"Blender açık ama N yan menüsünden BlenderMCP sunucusu başlatılmamış ({exc}).",
                loc_detail,
            )

    if tool.port:
        if not tool.enabled:
            try:
                with socket.create_connection(("127.0.0.1", int(tool.port)), timeout=0.4):
                    return (
                        False,
                        f"Devre Dışı (:{tool.port} Açık)",
                        -1,
                        f"AI için KAPALI tutuldu; arka planda 127.0.0.1:{tool.port} portu açık.",
                        loc_detail,
                    )
            except OSError:
                return False, "Devre Dışı", -1, "Kullanıcı tarafından kapalı tutuldu.", loc_detail

        t0 = time.perf_counter()
        try:
            with socket.create_connection(("127.0.0.1", int(tool.port)), timeout=0.65):
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                if tool.health_url:
                    try:
                        with urllib.request.urlopen(tool.health_url, timeout=1.2) as resp:
                            body = resp.read(64).decode("utf-8", errors="replace").strip()
                            return True, f"{now_str} ({ms}ms)", ms, f"HTTP 200: {body}", loc_detail
                    except Exception as exc:
                        return False, f"Port Açık / HTTP Hata (:{tool.port})", ms, str(exc), loc_detail
                return True, f"{now_str} ({ms}ms)", ms, f"127.0.0.1:{tool.port} TCP bağlantı başarılı.", loc_detail
        except OSError as exc:
            if tool.id == "trellis":
                cli_exe = pathlib.Path(tool.param_value) / "runtime" / "trellis-cli.exe"
                if cli_exe.is_file():
                    return False, f"Uyku Modu (:{tool.port})", -1, "Trellis CLI kurulu; yerel GPU sunucusu uykuda.", loc_detail
            return False, f"Kapalı (:{tool.port})", -1, f"127.0.0.1:{tool.port} yanıt vermiyor ({exc}).", loc_detail

    if tool.id == "unity_pipeline":
        target_proj = projects_map.get(tool.project_scope, tool.param_value)
        manifest = pathlib.Path(target_proj) / "Packages" / "manifest.json"
        if manifest.is_file() and "com.unity.pipeline" in manifest.read_text(encoding="utf-8", errors="ignore"):
            return tool.enabled, "Kurulu (Unity 6)" if tool.enabled else "Devre Dışı", 3, "com.unity.pipeline doğrulandı.", loc_detail
        return False, "Paket Yok", -1, f"Manifest kontrol edilemedi: {manifest}", loc_detail

    if not tool.enabled:
        return False, "Devre Dışı", -1, "Kullanıcı tarafından kapalı tutuldu (0 şema token).", loc_detail

    return True, "Hazır (stdio)", 4, f"Komut: {tool.mcp_command or tool.install_cmd or 'Hazır'}", loc_detail
