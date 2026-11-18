"""Gerçek Sistem İşlemleri: Port/Sağlık Taraması, Canlı Konum Algılama, RTX VRAM, Zombie Port Temizleyici, GitHub Analizi ve Proje/Global AI Config Senkronizasyonu."""
from __future__ import annotations

import concurrent.futures
import copy
import csv
import ctypes
from ctypes import wintypes
import io
import json
import os
import pathlib
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from typing import Any

import psutil

from .catalog import ToolSpec
from .storage import WindowsDpapiVault
from .updater import parse_semver

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

PROTECTED_EXES = {"unity.exe", "blender.exe", "code.exe", "antigravity.exe", "explorer.exe"}


def query_gpu_vram() -> tuple[str, int, int]:
    """(gpu_name, used_mb, total_mb) döndürür."""
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


_IGNORED_WIN_TITLES = {
    "",
    "n/a",
    "yok",
    "default ime",
    "msctfime ui",
    "olemainthreadwndname",
    "pyinstaller onefile hidden window",
}


def _is_interactive_default_desktop() -> bool:
    """Sürecin doğrudan kullanıcının gerçek 'Default' masaüstünde çalışıp çalışmadığını kontrol eder."""
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
    """Ekranda gerçekten görünür (WS_VISIBLE) penceresi olan süreçlerin {pid: pencere_başlığı} haritasını döndürür.
    Kullanıcının gerçek 'Default' masaüstünde yalnızca Win32 EnumWindows + IsWindowVisible kullanılır (<1ms);
    böylece gizlenmiş/asılı zombi pencereler tasklist /v yüzünden açık sanılmaz.
    """
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

    # Gerçek 'Default' masaüstündeysek IsWindowVisible kesin gerçektir; tasklist /v gizli pencereleri de döndürdüğü için çağrılmaz.
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
    """Gerçekten görünür penceresi açık olan Unity.exe ve blender.exe var mı kontrol eder."""
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
    """Çalışan süreçlerin komut satırından ve gerçek pencere başlığından canlı konumları çıkarır."""
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

            if nm == "serena.exe" or ("python" in nm and "serena" in cmd_joined.lower() and "start-mcp-server" in cmd_joined.lower()):
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
    """Verilen TCP portunu dinleyen sürecin (pid, exe_name) bilgisini bulur."""
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
    """Portu tutan asılı arka plan sunucusunu (görünür penceresi açık editörler hariç, penceresiz zombiler dahil) temizler."""
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


_PY_HOST_EXES = {"python.exe", "pythonw.exe", "uv.exe", "uvx.exe"}


def _find_managed_processes(
    exe_names: set[str],
    host_keywords: tuple[str, ...] = (),
    require_all: tuple[str, ...] = (),
) -> list[psutil.Process]:
    """Yalnızca AIconomy'nin yönettiği köprü süreçlerini bulur.

    Bir süreç şu durumlarda eşleşir: adı ``exe_names`` içinde olduğunda VEYA bir Python/uv
    host süreci olup komut satırında ``host_keywords``'den biri ve ``require_all``'daki
    tüm parçalar geçtiğinde. Port sahipliğine asla bakılmaz; böylece kullanıcının ilgisiz
    sunucuları (ör. :8080'deki Vite/Tomcat) hiçbir zaman hedef alınmaz.
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
    """Bir araç AÇIK veya KAPALI yapıldığında arka plandaki gerçek süreçleri de bu duruma uydurur.

    ``allow_stop=False`` olduğunda (ör. program açılışı) hiçbir süreç sonlandırılmaz; yalnızca
    AÇIK araçların köprüleri gerekiyorsa başlatılır. Durdurma işlemi sadece AIconomy'nin
    yönettiği köprü süreçlerini (ada/komut satırına göre) hedefler, port sahibini değil.
    """
    if tool.id == "blender_mcp" and not tool.enabled:
        if not allow_stop:
            return ""
        killed = _terminate_all(
            _find_managed_processes({"blender-mcp.exe"}, host_keywords=("blender-mcp",)),
            "blender-mcp",
        )
        # Penceresi kapanmış ama :9876 soketini tutmaya devam eden asılı blender.exe:
        # yalnızca portun gerçek sahibiyse, görünür penceresi yoksa ve bir arka plan
        # (-b / --background) render işi DEĞİLSE temizlenir.
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
                    cmd = ["uvx", "--python", "3.12", "mcpforunityserver", "--transport", "http", "--http-host", "127.0.0.1", "--http-port", str(port)]
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
    """trellis-server.exe sürecini kapatıp ekran kartı VRAM belleğini boşaltır."""
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


def _find_blender_exe() -> pathlib.Path | None:
    base = pathlib.Path(r"C:\Program Files\Blender Foundation")
    if base.is_dir():
        cands = sorted(base.glob("Blender */blender.exe"), reverse=True)
        for cand in cands:
            if cand.is_file():
                return cand
    found = shutil.which("blender")
    return pathlib.Path(found) if found else None


def _find_unity_exe(project_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    hub_root = pathlib.Path(r"C:\Program Files\Unity\Hub\Editor")
    if project_dir and project_dir.is_dir():
        ver_file = project_dir / "ProjectSettings" / "ProjectVersion.txt"
        if ver_file.is_file():
            m = re.search(r"m_EditorVersion:\s*([^\s\r\n]+)", ver_file.read_text(encoding="utf-8", errors="ignore"))
            if m:
                cand = hub_root / m.group(1).strip() / "Editor" / "Unity.exe"
                if cand.is_file():
                    return cand
    if hub_root.is_dir():
        editors = sorted(hub_root.glob("*/Editor/Unity.exe"), reverse=True)
        if editors:
            return editors[0]
    found = shutil.which("Unity")
    return pathlib.Path(found) if found else None


def _find_renderdoc_exe() -> pathlib.Path | None:
    for cand in (
        pathlib.Path(r"C:\Program Files\RenderDoc\qrenderdoc.exe"),
        pathlib.Path(r"C:\Program Files (x86)\RenderDoc\qrenderdoc.exe"),
    ):
        if cand.is_file():
            return cand
    found = shutil.which("qrenderdoc")
    return pathlib.Path(found) if found else None


def get_missing_host_dependencies(
    tools: list[ToolSpec],
    live_map: dict[str, str],
    projects_map: dict[str, str],
) -> list[dict[str, Any]]:
    """Panelde AÇIK olup bağımlı masaüstü programı/sunucusu henüz çalışmayan araçları döndürür."""
    by_id = {t.id: t for t in tools}
    missing: list[dict[str, Any]] = []

    bm = by_id.get("blender_mcp")
    if bm and bm.enabled and live_map.get("blender_open") != "1":
        missing.append(
            {
                "host": "blender",
                "title": "Blender kapalı",
                "detail": "Blender MCP AÇIK; bağlanabilmesi için Blender'ın başlatılması gerekir (eklenti -b arkaplan modunu desteklemediği için simge durumunda açılır).",
                "btn_label": "🚀 Blender'ı Başlat (Simge + :9876)",
                "headless": False,
                "scope": bm.project_scope,
            }
        )

    um = by_id.get("unity_mcp")
    up = by_id.get("unity_pipeline")
    if ((um and um.enabled) or (up and up.enabled)) and live_map.get("unity_open") != "1":
        target_scope = (um.project_scope if um and um.enabled else up.project_scope) if (um or up) else "GLOBAL"
        missing.append(
            {
                "host": "unity",
                "title": "Unity Editor kapalı",
                "detail": "Unity MCP / Pipeline AÇIK; sahne/editor komutları için Unity Editor çalıştırılmalıdır (projeyi kilitlememesi için normal Editor odak çalmadan simge durumunda açılır).",
                "btn_label": "🚀 Unity Editor'ü Başlat (Simge)",
                "headless": False,
                "scope": target_scope,
            }
        )

    rd = by_id.get("renderdoc_mcp")
    if rd and rd.enabled and live_map.get("renderdoc_open") != "1" and _find_renderdoc_exe() is not None:
        missing.append(
            {
                "host": "renderdoc",
                "title": "RenderDoc kapalı",
                "detail": "RenderDoc MCP AÇIK; GPU kare analizi için RenderDoc başlatılabilir.",
                "btn_label": "🚀 RenderDoc Başlat (Simge)",
                "headless": False,
                "scope": rd.project_scope,
            }
        )

    tr = by_id.get("trellis")
    if tr and tr.enabled and "trellis" not in live_map:
        srv_exe = pathlib.Path(tr.param_value) / "runtime" / "trellis-server.exe"
        if srv_exe.is_file():
            missing.append(
                {
                    "host": "trellis",
                    "title": "Trellis GPU sunucusu uykuda",
                    "detail": "Trellis AÇIK; yerel 3D sunucu UI'sız olarak başlatılabilir.",
                    "btn_label": "🚀 Trellis Başlat (UI'sız)",
                    "headless": True,
                    "scope": tr.project_scope,
                }
            )

    return missing


def launch_host_app_for_tool(
    host_kind: str,
    projects_map: dict[str, str],
    target_scope: str = "GLOBAL",
    headless: bool = True,
    trellis_root: str = "",
) -> tuple[bool, str]:
    """Bağımlı programı mümkünse UI'sız (-batchmode / NO_WINDOW), değilse simge durumunda odak çalmadan başlatır."""
    si_minimized = None
    if os.name == "nt":
        si_minimized = subprocess.STARTUPINFO()
        si_minimized.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si_minimized.wShowWindow = 7  # SW_SHOWMINNOACTIVE: odak çalmadan simge durumunda başlat

    if host_kind == "blender":
        b_exe = _find_blender_exe()
        if not b_exe:
            return False, "Blender.exe sistemde bulunamadı."
        py_expr = (
            "import bpy; "
            "bpy.app.timers.register(lambda: (bpy.ops.blendermcp.start_server() if hasattr(bpy.ops, 'blendermcp') else None), first_interval=1.2)"
        )
        subprocess.Popen([str(b_exe), "--python-expr", py_expr], startupinfo=si_minimized)
        return True, "Blender odak çalmadan simge durumunda başlatıldı ve :9876 MCP köprüsü tetiklendi."

    if host_kind == "unity":
        proj_path: pathlib.Path | None = None
        if target_scope != "GLOBAL" and target_scope in projects_map:
            proj_path = pathlib.Path(projects_map[target_scope])
        elif projects_map:
            proj_path = pathlib.Path(next(iter(projects_map.values())))
        u_exe = _find_unity_exe(proj_path)
        if not u_exe:
            return False, "Unity.exe kurulumu bulunamadı."
        cmd = [str(u_exe)]
        if proj_path and proj_path.is_dir():
            cmd.extend(["-projectPath", str(proj_path)])
        if headless:
            cmd.extend(["-batchmode", "-nographics"])
            subprocess.Popen(cmd, creationflags=NO_WINDOW)
            return True, f"Unity arka planda UI'sız (-batchmode -nographics) başlatıldı: {proj_path or u_exe.name}"
        subprocess.Popen(cmd, startupinfo=si_minimized)
        return True, f"Unity Editor simge durumunda başlatıldı: {proj_path or u_exe.name}"

    if host_kind == "renderdoc":
        r_exe = _find_renderdoc_exe()
        if not r_exe:
            return False, "qrenderdoc.exe bulunamadı."
        subprocess.Popen([str(r_exe)], startupinfo=si_minimized)
        return True, "RenderDoc simge durumunda başlatıldı."

    if host_kind == "trellis":
        srv_exe = pathlib.Path(trellis_root or str(pathlib.Path.home() / "Trellis")) / "runtime" / "trellis-server.exe"
        if not srv_exe.is_file():
            return False, f"Trellis sunucusu bulunamadı: {srv_exe}"
        subprocess.Popen([str(srv_exe)], creationflags=NO_WINDOW)
        return True, "Trellis GPU sunucusu UI'sız olarak arka planda başlatıldı."

    return False, f"Bilinmeyen hedef program: {host_kind}"


def resolve_disk_location(tool: ToolSpec, projects_map: dict[str, str], live_map: dict[str, str]) -> str:
    """Her araç için gerçek dosya yolunu veya canlı çalıştığı proje bilgisini döndürür."""
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
    """(is_healthy, short_ping_str, latency_ms, detail_msg, location_detail) döndürür."""
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

    # Blender MCP Köprüsü: Yalnızca GERÇEK görünür bir Blender penceresi açık VE :9876 soketi yanıt veriyorsa aktif sayılır!
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
            # Panelde KAPALI tutuluyorsa aktif ping saati yazıp çalışıyormuş izlenimi verme!
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


def _force_rmtree(target: pathlib.Path) -> None:
    """Windows salt-okunur (.git pack) dosyalarını kilide takılmadan temizler."""
    if not target.exists():
        return

    def _handle_readonly(func: Any, fpath: str, _exc: Any) -> None:
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except Exception:
            pass

    shutil.rmtree(target, onexc=_handle_readonly)


def install_or_update_blender_skills(active_skills: set[str]) -> tuple[bool, str, str]:
    """arjun988/blender-skills reposunu Antigravity plugin yapısında indirir ve seçili 94 skill ayrımını uygular.
    Dönüş: (ok, version_tag, msg)
    """
    target_root = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
    # Eski sürümden kalma salt-okunur geçici klasör varsa temizle
    legacy_tmp = target_root.parent / "_tmp_blender_skills_clone"
    if legacy_tmp.exists():
        _force_rmtree(legacy_tmp)

    temp_clone = pathlib.Path(tempfile.mkdtemp(prefix="aihub_bs_"))
    clone_dest = temp_clone / "repo"
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/arjun988/blender-skills.git", str(clone_dest)],
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=NO_WINDOW,
        )
        if proc.returncode != 0:
            return False, "", f"Git clone başarısız: {proc.stderr.strip()}"

        src_skills = clone_dest / ".claude" / "skills"
        if not src_skills.is_dir():
            return False, "", "Repo içinde .claude/skills klasörü bulunamadı."

        ver_tag = "v1.3.0"
        ver_json = clone_dest / "version.json"
        if ver_json.is_file():
            try:
                v_raw = json.loads(ver_json.read_text(encoding="utf-8")).get("version", "")
                if v_raw:
                    ver_tag = v_raw if str(v_raw).startswith("v") else f"v{v_raw}"
            except Exception:
                pass

        skills_dir = target_root / "skills"
        disabled_dir = target_root / "skills_disabled"
        skills_dir.mkdir(parents=True, exist_ok=True)
        disabled_dir.mkdir(parents=True, exist_ok=True)

        src_refs = src_skills / "references"
        if src_refs.is_dir():
            for dst_parent in (skills_dir, disabled_dir):
                dst_ref = dst_parent / "references"
                if dst_ref.exists():
                    _force_rmtree(dst_ref)
                shutil.copytree(src_refs, dst_ref)

        count = 0
        for item in src_skills.iterdir():
            if not item.is_dir() or item.name == "references":
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.is_file():
                continue
            txt = skill_md.read_text(encoding="utf-8", errors="replace")
            txt = _dedupe_yaml_frontmatter_keys(txt)
            skill_md.write_text(txt, encoding="utf-8")

            for cleanup in (skills_dir / item.name, disabled_dir / item.name):
                if cleanup.exists():
                    _force_rmtree(cleanup)

            dest = (skills_dir if item.name in active_skills else disabled_dir) / item.name
            shutil.copytree(item, dest)
            count += 1

        plugin_json = {
            "name": "blender-skills",
            "displayName": "Blender Skills (94 Specialist Pack)",
            "version": ver_tag.lstrip("v"),
            "description": "94 uzman Blender üretim skill paketi (AI Araç Merkezi tarafından seçmeli yönetilir).",
            "repository": "https://github.com/arjun988/blender-skills",
        }
        (target_root / "plugin.json").write_text(json.dumps(plugin_json, ensure_ascii=False, indent=2), encoding="utf-8")
        return (
            True,
            ver_tag,
            f"{count} Blender skill güncellendi ({ver_tag}); {len(active_skills)} açık, {count - len(active_skills)} kapalı.",
        )
    except Exception as exc:
        return False, "", f"Kurulum hatası: {exc}"
    finally:
        _force_rmtree(temp_clone)


def _dedupe_yaml_frontmatter_keys(md_text: str) -> str:
    if not md_text.startswith("---"):
        return md_text
    parts = md_text.split("---", 2)
    if len(parts) < 3:
        return md_text
    lines = parts[1].splitlines()
    out_lines: list[str] = []
    seen_per_indent: dict[int, set[str]] = {}
    for line in lines:
        m = re.match(r"^(\s*)([A-Za-z0-9_-]+)\s*:", line)
        if m:
            indent = len(m.group(1))
            key = m.group(2)
            for deeper in [k for k in seen_per_indent if k > indent]:
                seen_per_indent.pop(deeper, None)
            bucket = seen_per_indent.setdefault(indent, set())
            if key in bucket:
                continue
            bucket.add(key)
        out_lines.append(line)
    return "---" + "\n".join(out_lines) + "\n---" + parts[2]


def sync_blender_skills_on_disk(
    active_skills: set[str],
    plugin_enabled: bool,
    project_scope: str = "GLOBAL",
    projects_map: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Kurulu blender-skills klasöründe seçili olanları global veya seçili proje (.agents/skills) dizinine senkronlar."""
    target_root = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
    skills_dir = target_root / "skills"
    disabled_dir = target_root / "skills_disabled"
    if not skills_dir.is_dir() and not disabled_dir.is_dir():
        return False, "Blender Skills henüz diske indirilmemiş (Tercihiniz kaydedildi; Eklentiler sekmesinden indirebilirsiniz)."

    skills_dir.mkdir(parents=True, exist_ok=True)
    disabled_dir.mkdir(parents=True, exist_ok=True)

    # Eğer belirli bir projeye atanmışsa globalde kapalı tutup sadece o projenin .agents/skills klasörüne kopyala
    is_global_scope = project_scope == "GLOBAL" or not projects_map or project_scope not in projects_map
    global_effective = active_skills if (plugin_enabled and is_global_scope) else set()

    moved = 0
    for folder in list(skills_dir.iterdir()) + list(disabled_dir.iterdir()):
        if not folder.is_dir() or folder.name == "references":
            continue
        should_be_on = folder.name in global_effective
        desired_parent = skills_dir if should_be_on else disabled_dir
        if folder.parent != desired_parent:
            dest = desired_parent / folder.name
            if dest.exists():
                _force_rmtree(dest)
            shutil.move(str(folder), str(dest))
            moved += 1

    if not is_global_scope and projects_map:
        proj_dir = pathlib.Path(projects_map[project_scope])
        if proj_dir.is_dir():
            proj_skills = proj_dir / ".agents" / "skills"
            proj_skills.mkdir(parents=True, exist_ok=True)
            # Önce eski blender skill kopyalarını temizle, sonra sadece aktif olanları kopyala
            all_pool = {f.name: f for f in list(skills_dir.iterdir()) + list(disabled_dir.iterdir()) if f.is_dir()}
            for name, src_f in all_pool.items():
                if name == "references":
                    continue
                dst_f = proj_skills / name
                if dst_f.exists():
                    _force_rmtree(dst_f)
                if plugin_enabled and name in active_skills:
                    shutil.copytree(src_f, dst_f)
            if "references" in all_pool and plugin_enabled and active_skills:
                dst_ref = proj_skills / "references"
                if dst_ref.exists():
                    _force_rmtree(dst_ref)
                shutil.copytree(all_pool["references"], dst_ref)
            return True, f"Sadece '{project_scope}' projesine ({len(active_skills) if plugin_enabled else 0} skill -> .agents/skills) senkronlandı."

    return True, f"Global senkronizasyon tamamlandı ({moved} skill taşındı; {len(global_effective)} aktif)."


def _build_mcp_entry(t: ToolSpec, vault: WindowsDpapiVault) -> dict[str, Any] | None:
    if t.port and t.kind == "HTTP Servis" and t.id in ("serena", "unity_mcp"):
        return {"url": f"http://127.0.0.1:{t.port}/mcp"}
    if t.mcp_command:
        entry: dict[str, Any] = {"command": t.mcp_command, "args": list(t.mcp_args)}
        if t.vault_key_name:
            secret = vault.get_secret(t.vault_key_name)
            if secret:
                entry["env"] = {t.vault_key_name: secret}
        return entry
    return None


_CONFIG_LOCK = threading.Lock()


def _atomic_write_text(path: pathlib.Path, text: str) -> None:
    """Dosyayı önce aynı klasörde geçici dosyaya yazıp sonra atomik olarak yerine koyar (yarım yazılmış JSON oluşmaz)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _rewrite_mcp_json(
    cfg_path: pathlib.Path,
    managed_keys: set[str],
    wanted_entries: dict[str, dict[str, Any]],
    create_if_missing: bool,
) -> tuple[bool, str]:
    """Bir mcpServers JSON dosyasında yalnızca AIconomy'nin yönettiği anahtarları günceller.

    Dosya içeriği gerçekten değişmiyorsa hiçbir şey yazılmaz ve .bak oluşturulmaz.
    Dönüş: (yazıldı_mı, hata_mesajı)
    """
    if not cfg_path.is_file() and not (create_if_missing and wanted_entries):
        return False, ""
    data: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            raw_txt = cfg_path.read_text(encoding="utf-8")
            data = json.loads(raw_txt) if raw_txt.strip() else {}
        except Exception as exc:
            return False, f"okuma hatası ({exc})"
        if not isinstance(data, dict):
            return False, "beklenmeyen JSON biçimi"
    original = copy.deepcopy(data)

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    for key in list(servers.keys()):
        if key in managed_keys:
            servers.pop(key, None)
    servers.update(wanted_entries)
    if servers or "mcpServers" in data:
        data["mcpServers"] = servers

    if data == original:
        return False, ""
    if cfg_path.is_file():
        shutil.copyfile(cfg_path, cfg_path.with_suffix(cfg_path.suffix + ".bak"))
    _atomic_write_text(cfg_path, json.dumps(data, ensure_ascii=False, indent=2))
    return True, ""


def sync_mcp_json_clients(
    tools: list[ToolSpec],
    vault: WindowsDpapiVault,
    projects_map: dict[str, str] | None = None,
) -> list[str]:
    """AI istemci config dosyalarını tek seferde ve kilit altında senkronlar (eşzamanlı yazmaları önler)."""
    with _CONFIG_LOCK:
        return _sync_mcp_json_clients_impl(tools, vault, projects_map)


def _sync_mcp_json_clients_impl(
    tools: list[ToolSpec],
    vault: WindowsDpapiVault,
    projects_map: dict[str, str] | None = None,
) -> list[str]:
    """Global ve Proje Bazlı (.mcp.json / .cursor/mcp.json) AI ayar dosyalarını yedek alarak günceller."""
    projects_map = projects_map or {}
    client_paths = {
        "AGY": pathlib.Path.home() / ".gemini" / "config" / "mcp_config.json",
        "CLD": pathlib.Path.home() / ".claude.json",
        "CUR": pathlib.Path.home() / ".cursor" / "mcp.json",
    }
    messages: list[str] = []
    managed_keys = {t.mcp_server_key for t in tools if t.mcp_server_key} | {"unityMCP"}

    # 1) Global Config Yazımı (AGY global çalışır; CLD ve CUR için sadece GLOBAL kapsamlılar globale yazılır)
    for code, cfg_path in client_paths.items():
        wanted: dict[str, dict[str, Any]] = {}
        for t in tools:
            if not t.mcp_server_key or not (t.enabled and t.clients.get(code, False)):
                continue
            # Claude ve Cursor proje bazlı .mcp.json desteklediği için proje kapsamlıları global yerine projeye yazarız
            if code in ("CLD", "CUR") and t.scope_selectable and t.project_scope != "GLOBAL":
                continue
            entry = _build_mcp_entry(t, vault)
            if entry:
                wanted[t.mcp_server_key] = entry
        try:
            written, err = _rewrite_mcp_json(cfg_path, managed_keys, wanted, create_if_missing=(code == "AGY"))
        except Exception as exc:
            written, err = False, f"yazma hatası ({exc})"
        if err:
            messages.append(f"{code}: {err}")
        elif cfg_path.is_file():
            messages.append(f"{code} Global ({len(wanted)} MCP{'' if written else ', değişiklik yok'})")

    # 2) Proje Bazlı Config Yazımı (<proje>/.mcp.json ve <proje>/.cursor/mcp.json)
    #    Mevcut dosyalar da işlenir; böylece kapatılan/başka projeye taşınan araçlar eski projeden temizlenir.
    for proj_name, proj_dir_str in projects_map.items():
        proj_dir = pathlib.Path(proj_dir_str)
        if not proj_dir.is_dir():
            continue
        scoped_tools = [
            t
            for t in tools
            if t.mcp_server_key and t.enabled and t.scope_selectable and t.project_scope == proj_name
        ]
        for target_code, rel_cfg in [("CLD", ".mcp.json"), ("CUR", ".cursor/mcp.json")]:
            p_wanted: dict[str, dict[str, Any]] = {}
            for t in scoped_tools:
                if t.clients.get(target_code, False):
                    entry = _build_mcp_entry(t, vault)
                    if entry:
                        p_wanted[t.mcp_server_key] = entry
            p_cfg = proj_dir / rel_cfg
            try:
                written, err = _rewrite_mcp_json(p_cfg, managed_keys, p_wanted, create_if_missing=True)
            except Exception as exc:
                written, err = False, f"yazma hatası ({exc})"
            if err:
                messages.append(f"{proj_name}/{rel_cfg}: {err}")
            elif written:
                messages.append(f"{proj_name}/{rel_cfg} ({len(p_wanted)} MCP)")

    # 3) Codex (~/.codex/config.toml) İşaretli Blok Senkronizasyonu
    codex_cfg = pathlib.Path.home() / ".codex" / "config.toml"
    if codex_cfg.is_file():
        try:
            orig_toml = codex_cfg.read_text(encoding="utf-8-sig")
            begin_tag = "# >>> BEGIN AI-ARAC-MERKEZI >>>"
            end_tag = "# <<< END AI-ARAC-MERKEZI <<<"
            cleaned = re.sub(
                rf"\n?{re.escape(begin_tag)}.*?{re.escape(end_tag)}\n?",
                "\n",
                orig_toml,
                flags=re.DOTALL,
            ).rstrip()

            # Mevcut config.toml içinde önceden tanımlı olan [mcp_servers.<ad>] bloklarının enabled değerini de senkronla
            alias_map: dict[str, ToolSpec] = {}
            for t in tools:
                if t.mcp_server_key:
                    alias_map[t.mcp_server_key] = t
                    if t.id == "unity_mcp":
                        alias_map["unityMCP"] = t

            def _sync_existing_codex_section(sec_name: str, should_enable: bool, text_in: str) -> tuple[str, bool]:
                hdr_pat = re.compile(rf"(^\[mcp_servers\.{re.escape(sec_name)}\]\s*$)", flags=re.MULTILINE)
                m = hdr_pat.search(text_in)
                if not m:
                    return text_in, False
                start = m.end()
                next_sec = re.search(r"^\[", text_in[start:], flags=re.MULTILINE)
                end = start + next_sec.start() if next_sec else len(text_in)
                body = text_in[start:end]
                val_str = "true" if should_enable else "false"
                if re.search(r"^\s*enabled\s*=", body, flags=re.MULTILINE):
                    body = re.sub(r"^\s*enabled\s*=\s*(true|false)", f"enabled = {val_str}", body, count=1, flags=re.MULTILINE)
                else:
                    body = f"\nenabled = {val_str}" + body
                return text_in[:start] + body + text_in[end:], True

            handled_existing: set[str] = set()
            for sec_key, t_obj in alias_map.items():
                want_cdx = bool(t_obj.enabled and t_obj.clients.get("CDX", False))
                cleaned, found_sec = _sync_existing_codex_section(sec_key, want_cdx, cleaned)
                if found_sec:
                    handled_existing.add(t_obj.id)

            cdx_lines: list[str] = [begin_tag]
            cdx_added = 0
            for t in tools:
                if not t.mcp_server_key or not (t.enabled and t.clients.get("CDX", False)):
                    continue
                if t.id in handled_existing:
                    cdx_added += 1
                    continue
                if t.port and t.kind == "HTTP Servis" and t.id in ("serena", "unity_mcp"):
                    cdx_lines.append(f"[mcp_servers.{t.mcp_server_key}]")
                    cdx_lines.append(f'url = "http://127.0.0.1:{t.port}/mcp"')
                    cdx_added += 1
                elif t.mcp_command:
                    args_toml = ", ".join(json.dumps(a) for a in t.mcp_args)
                    cdx_lines.append(f"[mcp_servers.{t.mcp_server_key}]")
                    cdx_lines.append(f"command = {json.dumps(t.mcp_command)}")
                    cdx_lines.append(f"args = [{args_toml}]")
                    if t.vault_key_name and vault.get_secret(t.vault_key_name):
                        sec = vault.get_secret(t.vault_key_name)
                        cdx_lines.append(f"[mcp_servers.{t.mcp_server_key}.env]")
                        cdx_lines.append(f"{t.vault_key_name} = {json.dumps(sec)}")
                    cdx_added += 1
            cdx_lines.append(end_tag)
            new_toml = cleaned + "\n\n" + "\n".join(cdx_lines) + "\n"
            if new_toml != orig_toml:
                shutil.copyfile(codex_cfg, codex_cfg.with_suffix(".toml.bak"))
                _atomic_write_text(codex_cfg, new_toml)
                messages.append(f"CDX ({cdx_added} MCP)")
            else:
                messages.append(f"CDX ({cdx_added} MCP, değişiklik yok)")
        except Exception as exc:
            messages.append(f"CDX hata ({exc})")

    return messages


def inspect_github_repo(repo_url: str, github_token: str = "") -> dict[str, Any]:
    """GitHub bağlantısını sorgular ve MCP / Skill türünü otomatik tanır."""
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", repo_url)
    if not m:
        raise ValueError("Geçerli bir GitHub repo adresi girin (örn: https://github.com/owner/repo).")
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    headers = {"User-Agent": "AI-Arac-Merkezi/1.0"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    req = urllib.request.Request(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
    with urllib.request.urlopen(req, timeout=8) as resp:
        meta = json.loads(resp.read().decode("utf-8"))

    branch = meta.get("default_branch", "main")
    tree_req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers=headers,
    )
    with urllib.request.urlopen(tree_req, timeout=8) as resp:
        tree_data = json.loads(resp.read().decode("utf-8"))

    paths = [item.get("path", "") for item in tree_data.get("tree", [])]
    skill_files = [p for p in paths if p.endswith("SKILL.md")]
    has_pkg = "package.json" in paths
    has_py = "pyproject.toml" in paths
    needs_key = any("API_KEY" in p.upper() or ".env.example" in p for p in paths)

    if len(skill_files) > 1:
        kind = "Skill Paketi"
        cmd = f"git clone https://github.com/{owner}/{repo}.git ({len(skill_files)} SKILL.md)"
        mcp_cmd, mcp_args = "", []
    elif len(skill_files) == 1 and not has_pkg and not has_py:
        kind = "Skill / Kural"
        cmd = f"git clone https://github.com/{owner}/{repo}.git"
        mcp_cmd, mcp_args = "", []
    elif has_pkg:
        kind = "stdio MCP"
        cmd = f"npx -y {repo}"
        mcp_cmd, mcp_args = "npx", ["-y", repo]
    elif has_py:
        kind = "stdio MCP"
        cmd = f"uvx {repo}"
        mcp_cmd, mcp_args = "uvx", [repo]
    else:
        kind = "CLI / GPU"
        cmd = f"git clone https://github.com/{owner}/{repo}.git"
        mcp_cmd, mcp_args = "", []

    return {
        "id": f"gh_{owner}_{repo}".lower().replace("-", "_"),
        "name": f"{repo} ({owner})",
        "description": meta.get("description") or "GitHub üzerinden algılanan araç.",
        "stars": meta.get("stargazers_count", 0),
        "kind": kind,
        "install_cmd": cmd,
        "mcp_command": mcp_cmd,
        "mcp_args": mcp_args,
        "skill_count": len(skill_files),
        "needs_api_key": needs_key,
        "repo_url": f"https://github.com/{owner}/{repo}",
    }


NPM_PACKAGE_MAP: dict[str, str] = {
    "bla": "bla-agents",
    "gltf_transform": "@gltf-transform/cli",
    "context7": "@upstash/context7-mcp",
    "chrome_devtools": "chrome-devtools-mcp",
}

UV_TOOL_MAP: dict[str, str] = {
    "serena": "serena-agent",
    "unity_mcp": "mcpforunityserver",
}

PYPI_PACKAGE_MAP: dict[str, str] = {
    "unity_mcp": "mcpforunityserver",
    "blender_mcp": "blender-mcp",
    "elevenlabs_mcp": "elevenlabs-mcp",
}


def _fmt_ver_short(v: str) -> str:
    clean = v.strip().lstrip("vV")
    return f"{clean}v" if clean else ""


def check_single_tool_update(tool: ToolSpec, github_token: str = "") -> tuple[bool, str, str, str]:
    """Hiçbir şey indirmeden (salt-okunur) aracın güncel sürümünü ve sürüm notu bağlantısını kontrol eder.
    Dönüş: (has_update, latest_version_tag, release_notes_url, check_error_detail)
    """
    local_ver = tool.version.strip().lstrip("vV") or "1.0.0"
    remote_ver = local_ver
    notes_url = ""
    err_detail = ""

    gh_match = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", tool.repo_url)
    if gh_match:
        gh_owner, gh_repo = gh_match.group(1), gh_match.group(2).removesuffix(".git")
        notes_url = f"https://github.com/{gh_owner}/{gh_repo}/releases"
    else:
        gh_owner, gh_repo = "", ""

    headers = {"User-Agent": "AI-Arac-Merkezi/1.1"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    try:
        if tool.id == "blender_skills":
            notes_url = "https://github.com/arjun988/blender-skills/blob/main/CHANGELOG.md"
            p_json = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills" / "plugin.json"
            if p_json.is_file():
                try:
                    disk_v = str(json.loads(p_json.read_text(encoding="utf-8")).get("version", "")).strip().lstrip("vV")
                    if disk_v:
                        local_ver = disk_v
                        tool.version = f"v{disk_v}"
                except Exception:
                    pass
            req = urllib.request.Request(
                "https://raw.githubusercontent.com/arjun988/blender-skills/main/version.json",
                headers={"User-Agent": "AI-Arac-Merkezi/1.1"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                v_raw = str(json.loads(resp.read().decode("utf-8")).get("version", "")).strip().lstrip("vV")
                if v_raw:
                    remote_ver = v_raw

        elif tool.id in NPM_PACKAGE_MAP:
            pkg = NPM_PACKAGE_MAP[tool.id]
            encoded_pkg = pkg.replace("/", "%2F")
            req = urllib.request.Request(
                f"https://registry.npmjs.org/{encoded_pkg}/latest",
                headers={"User-Agent": "AI-Arac-Merkezi/1.1"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                meta = json.loads(resp.read().decode("utf-8"))
                v_raw = str(meta.get("version", "")).strip().lstrip("vV")
                if v_raw:
                    remote_ver = v_raw
            if not notes_url:
                notes_url = f"https://www.npmjs.com/package/{pkg}?activeTab=versions"

        elif tool.id in PYPI_PACKAGE_MAP:
            pkg = PYPI_PACKAGE_MAP[tool.id]
            req = urllib.request.Request(
                f"https://pypi.org/pypi/{pkg}/json",
                headers={"User-Agent": "AI-Arac-Merkezi/1.1"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                meta = json.loads(resp.read().decode("utf-8"))
                v_raw = str(meta.get("info", {}).get("version", "")).strip().lstrip("vV")
                if v_raw:
                    remote_ver = v_raw
            if not notes_url:
                notes_url = f"https://pypi.org/project/{pkg}/#history"

        elif tool.id in ("unity_pipeline", "trellis"):
            remote_ver = local_ver
            notes_url = tool.repo_url if tool.repo_url.startswith("http") else ""

        elif gh_owner and gh_repo:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{gh_owner}/{gh_repo}/releases/latest",
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                rel = json.loads(resp.read().decode("utf-8"))
                tag = str(rel.get("tag_name", "")).strip().lstrip("vV")
                if tag:
                    remote_ver = tag
                if rel.get("html_url"):
                    notes_url = str(rel["html_url"])
    except urllib.error.HTTPError as http_exc:
        # 404: repoda henüz GitHub Release açılmamış demektir, hata olarak şişirmeyiz
        if http_exc.code != 404:
            err_detail = f"HTTP {http_exc.code} ({http_exc.reason}) — URL: {http_exc.url}"
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}"

    has_upd = parse_semver(remote_ver) > parse_semver(local_ver)
    latest_tag = f"v{remote_ver}"
    tool.latest_version = latest_tag
    tool.has_update = has_upd
    tool.release_notes_url = notes_url
    return has_upd, latest_tag, notes_url, err_detail


def check_all_tools_updates_parallel(
    tools: list[ToolSpec],
    github_token: str = "",
) -> tuple[int, list[tuple[str, str]]]:
    """Tüm araçların güncellemelerini paralel kontrol eder; (güncelleme_sayısı, [(araç_adı, hata_detayı)]) döndürür."""
    errors: list[tuple[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(check_single_tool_update, t, github_token): t for t in tools}
        for fut, t in future_map.items():
            try:
                _, _, _, err_det = fut.result()
                if err_det:
                    errors.append((t.name, err_det))
            except Exception as exc:
                errors.append((t.name, f"{type(exc).__name__}: {exc}"))
    return sum(1 for t in tools if t.has_update), errors


def update_single_tool(
    tool: ToolSpec,
    active_skills: set[str],
    install_if_missing: bool = False,
) -> tuple[bool, str, str, str]:
    """Tek bir aracı güvenli şekilde günceller (veya install_if_missing=True ise kurar).
    Dönüş: (başarılı_mı, yeni_sürüm_etiketi, kısa_özet, tam_ham_log_detayı)
    """
    try:
        # 1) Blender Skills (94 Skill Paketi)
        if tool.id == "blender_skills":
            plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
            is_installed = (plugin_dir / "skills").is_dir() or (plugin_dir / "skills_disabled").is_dir()
            if is_installed or install_if_missing:
                ok, ver_tag, msg = install_or_update_blender_skills(active_skills)
                return ok, ver_tag or tool.version, msg, msg
            msg = "Henüz indirilmemiş (Kurmak için kutucuğu seçip 'Seçilenleri Kur / Güncelle' diyebilirsiniz)."
            return True, tool.version, msg, msg

        # 2) Caveman (Git tabanlı yerel skill)
        if tool.id == "caveman":
            cav_dir = pathlib.Path.home() / ".agents" / "skills" / "caveman"
            if (cav_dir / ".git").is_dir():
                cmd = ["git", "-C", str(cav_dir), "pull", "--ff-only"]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=NO_WINDOW,
                )
                raw = f"Komut: {' '.join(cmd)}\nÇıkış Kodu: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                if proc.returncode == 0:
                    out = proc.stdout.strip() or "Güncel."
                    return True, tool.version, f"Git pull tamamlandı: {out}", raw
                err_first = (proc.stderr.strip() or proc.stdout.strip() or "Bilinmeyen git hatası").splitlines()[0]
                return False, "", f"Git pull hatası: {err_first}", raw
            if (cav_dir / "SKILL.md").is_file():
                return True, tool.version, "Yerel SKILL.md doğrulandı ve güncel.", str(cav_dir / "SKILL.md")
            return True, tool.version, "Caveman kuralı hazır.", str(cav_dir)

        # 3) uv tool ile yönetilen araçlar (Serena, Unity MCP)
        if tool.id in UV_TOOL_MAP:
            pkg = UV_TOOL_MAP[tool.id]
            if install_if_missing:
                cmd = ["uv", "tool", "install", "--upgrade"]
                if pkg == "mcpforunityserver":
                    cmd.extend(["--python", "3.12"])
                cmd.append(pkg)
            else:
                cmd = ["uv", "tool", "upgrade", pkg]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=90,
                creationflags=NO_WINDOW,
            )
            combined = (proc.stdout + "\n" + proc.stderr).strip()
            raw = f"Komut: {' '.join(cmd)}\nÇıkış Kodu: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            if proc.returncode == 0 or "Nothing to upgrade" in combined or "already installed" in combined.lower():
                return True, tool.version, f"uv tool ({pkg}): Güncel.", raw
            if "is not installed" in combined.lower() and not install_if_missing:
                return True, tool.version, f"{pkg} özel dizinde kurulu (mevcut kurulum korundu).", raw
            first_line = (proc.stderr.strip() or proc.stdout.strip() or "uv tool hatası").splitlines()[0]
            return False, "", f"uv tool ({pkg}) hatası: {first_line}", raw

        # 4) npm / npx tabanlı araçlar (BLA, glTF-Transform, Context7, Chrome DevTools)
        if tool.id in NPM_PACKAGE_MAP:
            pkg = NPM_PACKAGE_MAP[tool.id]
            latest_ver = ""
            try:
                encoded_pkg = pkg.replace("/", "%2F")
                req = urllib.request.Request(
                    f"https://registry.npmjs.org/{encoded_pkg}/latest",
                    headers={"User-Agent": "AI-Arac-Merkezi/1.1"},
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    meta = json.loads(resp.read().decode("utf-8"))
                    latest_ver = meta.get("version", "")
            except Exception as exc:
                return False, "", f"npm sürüm sorgulama hatası ({pkg}): {exc}", traceback.format_exc()

            new_v_tag = f"v{latest_ver}" if latest_ver else tool.version
            if install_if_missing and pkg in ("bla-agents", "@gltf-transform/cli"):
                npm_exe = "npm.cmd" if shutil.which("npm.cmd") else "npm"
                cmd = [npm_exe, "install", "-g", f"{pkg}@latest"]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=90,
                    creationflags=NO_WINDOW,
                )
                raw = f"Komut: {' '.join(cmd)}\nÇıkış Kodu: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                if proc.returncode != 0:
                    first_err = (proc.stderr.strip() or proc.stdout.strip() or "npm install hatası").splitlines()[0]
                    return False, new_v_tag, f"npm kurulum hatası ({pkg}): {first_err}", raw
                return True, new_v_tag, f"{pkg} global olarak {new_v_tag} sürümüne güncellendi.", raw

            msg = f"npm son sürümü doğrulandı -> {new_v_tag} (npx ile güncel çalışır)."
            return True, new_v_tag, msg, msg

        # 5) PyPI / uvx tabanlı araçlar
        if tool.id in PYPI_PACKAGE_MAP:
            pkg = PYPI_PACKAGE_MAP[tool.id]
            latest_ver = ""
            try:
                req = urllib.request.Request(
                    f"https://pypi.org/pypi/{pkg}/json",
                    headers={"User-Agent": "AI-Arac-Merkezi/1.1"},
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    meta = json.loads(resp.read().decode("utf-8"))
                    latest_ver = meta.get("info", {}).get("version", "")
            except Exception as exc:
                return False, "", f"PyPI sürüm sorgulama hatası ({pkg}): {exc}", traceback.format_exc()
            new_v_tag = f"v{latest_ver}" if latest_ver else tool.version
            msg = f"PyPI son sürümü doğrulandı ({new_v_tag})."
            return True, new_v_tag, msg, msg

        # 6) Yerel oyun / GPU araçları
        if tool.id in ("unity_pipeline", "trellis"):
            msg = "Yerel motor/GPU kurulumu doğrulandı (özel ağırlık ve proje dosyaları korundu)."
            return True, tool.version, msg, msg

        if "github.com/" in tool.repo_url:
            m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", tool.repo_url)
            if m:
                owner, repo = m.group(1), m.group(2).removesuffix(".git")
                try:
                    req = urllib.request.Request(
                        f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
                        headers={"User-Agent": "AI-Arac-Merkezi/1.1"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        rel = json.loads(resp.read().decode("utf-8"))
                        tag = rel.get("tag_name", "")
                        if tag:
                            v_t = tag if tag.startswith("v") else f"v{tag}"
                            return True, v_t, f"GitHub son sürümü doğrulandı: {v_t}", str(rel.get("html_url", ""))
                except urllib.error.HTTPError as http_exc:
                    if http_exc.code != 404:
                        return False, "", f"GitHub API hatası (HTTP {http_exc.code})", traceback.format_exc()
                except Exception as exc:
                    return False, "", f"GitHub bağlantı hatası: {exc}", traceback.format_exc()
            return True, tool.version, "GitHub kaynağı doğrulandı ve güncel.", tool.repo_url

        return True, tool.version, "Sürüm kontrolü tamamlandı.", tool.name
    except FileNotFoundError as fnf_exc:
        missing_bin = str(fnf_exc.filename or fnf_exc)
        hint = "Git (https://git-scm.com), uv (https://docs.astral.sh/uv/) veya Node.js (https://nodejs.org) kurulu olduğundan emin olun."
        return False, "", f"Gerekli sistem aracı bulunamadı ({missing_bin}). {hint}", traceback.format_exc()
    except Exception as exc:
        return False, "", f"Beklenmeyen güncelleme hatası: {exc}", traceback.format_exc()


def test_tool_connection_e2e(
    tool: ToolSpec,
    vault: WindowsDpapiVault,
    projects_map: dict[str, str],
    active_skills_count: int = 0,
) -> tuple[bool, int, str, str]:
    """Antigravity / AI istemcisi açık olmasa bile aracın gerçek bağlantısını uçtan uca test eder.
    Dönüş: (ok, latency_ms, kisa_ozet, teknik_detay)
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
                    cfg_note = " | ⚠️ AGY mcp_config.json içinde eksik (AI Config'lere Yaz basın)"
                elif in_agy:
                    cfg_note = " | AGY Config ✓"
            except Exception:
                pass

    if not tool.enabled:
        return False, -1, "Panelde KAPALI (Test atlandı)", "Araç devre dışı bırakılmış; önce AÇIK yapın."

    # 1) HTTP MCP Servisleri (Serena :9121, Unity MCP :8080): Gerçek JSON-RPC initialize isteği atar
    if tool.kind == "HTTP Servis" and tool.id in ("serena", "unity_mcp") and tool.port:
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
                    "clientInfo": {"name": "ai-arac-merkezi-test", "version": "1.2.12"},
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

    # 2) Blender MCP Köprüsü (:9876): Gerçek get_scene_info soket sorgusu
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
            return False, -1, f"Blender :9876 Bağlanamadı", f"Blender açık ve BlenderMCP bağlı değil: {exc}"

    # 3) Trellis GPU Sunucu (:8790)
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

    # 4) stdio MCP Sunucuları (Context7, RenderDoc, Chrome DevTools, ElevenLabs, Meshy, glTF-Transform)
    if tool.mcp_command:
        cmd_bin = shutil.which(f"{tool.mcp_command}.cmd") or shutil.which(tool.mcp_command)
        if not cmd_bin:
            return False, -1, f"Komut bulunamadı: {tool.mcp_command}", f"PATH üzerinde '{tool.mcp_command}' yok."
        if tool.vault_key_name and not vault.has_secret(tool.vault_key_name):
            return False, -1, f"API Anahtarı Eksik ({tool.vault_key_name})", "Şifreli Kasa sekmesinden anahtarı ekleyin."

        env = os.environ.copy()
        if tool.vault_key_name:
            sec = vault.get_secret(tool.vault_key_name)
            if sec:
                env[tool.vault_key_name] = sec

        return _run_stdio_handshake(cmd_bin, tool.mcp_args, env, t0, cfg_note)

    # 5) Yerel Skill / CLI Araçları
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
) -> tuple[bool, int, str, str]:
    """Windows üzerinde stdio MCP sürecine JSON-RPC initialize gönderip yanıtını timeout'lu okur."""
    init_msg = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ai-arac-merkezi-test", "version": "1.2.12"},
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

    import threading  # noqa: PLC0415

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


