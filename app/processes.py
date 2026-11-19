"""Process, port, GPU VRAM, visible GUI window detection, and live health probing (emoji-free, EN & TR)."""
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

from .catalog import ToolSpec, localized_tool_modes
from .host_apps import NO_WINDOW, _find_blender_exe
from .i18n import tr

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


_AI_CLIENT_PROCESS_NAMES = frozenset(
    {
        "antigravity.exe",
        "cursor.exe",
        "claude.exe",
        "codex.exe",
        "windsurf.exe",
    }
)


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _NvmlVramReader:
    """In-process ctypes wrapper around Windows nvml.dll (zero subprocess overhead, <0.1ms)."""

    def __init__(self) -> None:
        self._initialized = False
        self._unavailable = False
        self._dll: Any = None
        self._handle = ctypes.c_void_p()
        self._gpu_name = ""

    def _ensure_init(self) -> bool:
        if self._initialized:
            return True
        if self._unavailable or os.name != "nt":
            return False
        candidates = ["nvml.dll"]
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        nvsmi_dll = pathlib.Path(prog_files) / "NVIDIA Corporation" / "NVSMI" / "nvml.dll"
        if nvsmi_dll.is_file():
            candidates.append(str(nvsmi_dll))
        for cand in candidates:
            try:
                dll = ctypes.WinDLL(cand)
                if dll.nvmlInit_v2() != 0:
                    continue
                handle = ctypes.c_void_p()
                if dll.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                    continue
                name_buf = ctypes.create_string_buffer(96)
                if dll.nvmlDeviceGetName(handle, name_buf, 96) == 0:
                    self._gpu_name = name_buf.value.decode("utf-8", errors="replace").strip()
                else:
                    self._gpu_name = "NVIDIA GPU"
                self._dll = dll
                self._handle = handle
                self._initialized = True
                return True
            except Exception:
                continue
        self._unavailable = True
        return False

    def read_vram_mb(self) -> tuple[str, int, int]:
        if not self._ensure_init() or self._dll is None:
            return "", 0, 0
        try:
            mem = _NvmlMemory()
            if self._dll.nvmlDeviceGetMemoryInfo(self._handle, ctypes.byref(mem)) == 0 and mem.total > 0:
                used_mb = int(mem.used // (1024 * 1024))
                total_mb = int(mem.total // (1024 * 1024))
                return self._gpu_name, used_mb, total_mb
        except Exception:
            pass
        return "", 0, 0


_NVML_READER = _NvmlVramReader()


def query_gpu_vram() -> tuple[str, int, int]:
    """Return (gpu_name, used_mb, total_mb) in-process via nvml.dll (zero subprocesses)."""
    return _NVML_READER.read_vram_mb()


def has_running_ai_client_processes() -> bool:
    """Return True when at least one AI coding client process (Antigravity, Cursor, Claude, Codex) is running."""
    for proc in psutil.process_iter(["name"]):
        try:
            nm = (proc.info.get("name") or "").lower()
            if nm in _AI_CLIENT_PROCESS_NAMES:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


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


def scan_live_process_locations(lang: str = "en") -> dict[str, str]:
    """Inspect active managed and DCC processes to determine live project paths and window states."""
    live: dict[str, str] = {}
    dcc_procs: list[tuple[int, str, str, list[str]]] = []
    pids_by_img: dict[str, list[int]] = {}
    is_tr = lang == "tr"

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
                    live["serena"] = (
                        f"Canlı proje: {proj_val}  |  {exe or nm} (PID {pid})"
                        if is_tr
                        else f"Live project: {proj_val}  |  {exe or nm} (PID {pid})"
                    )
                else:
                    live["serena"] = (
                        f"Çalışıyor: {exe or nm} (PID {pid})"
                        if is_tr
                        else f"Running: {exe or nm} (PID {pid})"
                    )

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
                live["trellis"] = (
                    f"GPU sunucusu aktif: {exe} (PID {pid})"
                    if is_tr
                    else f"GPU server active: {exe} (PID {pid})"
                )

            elif nm == "qrenderdoc.exe":
                live["renderdoc_open"] = "1"
                live["renderdoc"] = (
                    f"RenderDoc açık: {exe} (PID {pid})"
                    if is_tr
                    else f"RenderDoc open: {exe} (PID {pid})"
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue

    win_titles = get_gui_window_titles(pids_by_img) if pids_by_img else {}

    for pid, kind, _exe, cmdline in dcc_procs:
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
                    live["unity"] = (
                        f"Açık Unity projesi: {proj_val} (PID {pid})"
                        if is_tr
                        else f"Open Unity project: {proj_val} (PID {pid})"
                    )
                else:
                    live["unity"] = (
                        f"Unity Editor açık: {w_title} (PID {pid})"
                        if is_tr
                        else f"Unity Editor open: {w_title} (PID {pid})"
                    )

        elif kind == "blender":
            blend_files = [a for a in cmdline if a.lower().endswith(".blend")]
            if w_title:
                live["blender_open"] = "1"
                live["blender_pid"] = str(pid)
                live["blender_title"] = w_title
                if blend_files:
                    live["blender"] = (
                        f"Açık sahne: {blend_files[0]}  |  {w_title} (PID {pid})"
                        if is_tr
                        else f"Open scene: {blend_files[0]}  |  {w_title} (PID {pid})"
                    )
                else:
                    live["blender"] = (
                        f"Blender açık: {w_title} (PID {pid})"
                        if is_tr
                        else f"Blender open: {w_title} (PID {pid})"
                    )
            elif "blender_open" not in live:
                live["blender_zombie_pid"] = str(pid)
                live["blender"] = (
                    f"Penceresiz asılı süreç: blender.exe (PID {pid})"
                    if is_tr
                    else f"Windowless stuck process: blender.exe (PID {pid})"
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
                        return pid, "unknown"
    except Exception:
        pass
    return None, ""


def kill_zombie_port_process(port: int, lang: str = "en") -> tuple[bool, str]:
    """Terminate a stuck background server holding ``port`` while protecting visible GUI editors."""
    is_tr = lang == "tr"
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
            msg = (
                f"Asılı köprü temizlendi: {', '.join(cleaned_extra)}."
                if is_tr
                else f"Cleaned up stuck bridge: {', '.join(cleaned_extra)}."
            )
            return True, msg
        msg = (
            f"Port :{port} üzerinde dinleyen süreç bulunamadı."
            if is_tr
            else f"No active process is listening on port :{port}."
        )
        return False, msg

    win_titles = get_gui_window_titles({name: [pid]}) if name.lower() in PROTECTED_EXES else {}
    if name.lower() in PROTECTED_EXES and pid in win_titles:
        msg = (
            f"Port :{port} açık pencere '{win_titles[pid]}' (PID {pid}) tarafından kullanılıyor; editör korundu."
            if is_tr
            else f"Port :{port} is used by open editor '{win_titles[pid]}' (PID {pid}); left running to prevent data loss."
        )
        return False, msg
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except psutil.TimeoutExpired:
            proc.kill()
        extra_note = f" + {', '.join(cleaned_extra)}" if cleaned_extra else ""
        msg = (
            f"Port :{port} üzerindeki süreç temizlendi ({name}, PID {pid}{extra_note})."
            if is_tr
            else f"Released port :{port} ({name}, PID {pid}{extra_note})."
        )
        return True, msg
    except Exception as exc:
        msg = (
            f"PID {pid} ({name}) sonlandırılamadı: {exc}"
            if is_tr
            else f"Could not terminate PID {pid} ({name}): {exc}"
        )
        return False, msg


def _find_managed_processes(
    exe_names: set[str],
    host_keywords: tuple[str, ...] = (),
    require_all: tuple[str, ...] = (),
) -> list[psutil.Process]:
    """Find only processes explicitly managed by AIconomy (never matches by port ownership)."""
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


def _terminate_all(procs: list[psutil.Process], label: str, wait_timeout: float = 3.5) -> list[str]:
    stopped: list[str] = []
    targeted: list[psutil.Process] = []
    for p in procs:
        try:
            p.terminate()
            targeted.append(p)
            stopped.append(f"{label} (PID {p.pid})")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if targeted:
        _gone, alive = psutil.wait_procs(targeted, timeout=wait_timeout)
        still_alive: list[psutil.Process] = []
        for p in alive:
            try:
                p.kill()
                still_alive.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if still_alive:
            psutil.wait_procs(still_alive, timeout=1.5)
    return stopped


def wait_for_started_ports(ports: list[int], timeout: float = 2.5) -> None:
    """Wait until all given local TCP ports accept connections (or ``timeout`` elapses)."""
    pending = {int(p) for p in ports if p}
    if not pending:
        return
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        ready: set[int] = set()
        for port in pending:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    ready.add(port)
            except OSError:
                pass
        pending -= ready
        if pending:
            time.sleep(0.2)


def has_running_managed_services(tools: list[ToolSpec], live_map: dict[str, str]) -> bool:
    """Return True when at least one AIconomy-managed background service is actively running."""
    managed = _find_managed_processes(
        {"serena.exe", "serena-agent.exe", "mcp-for-unity.exe", "unity-mcp.exe", "blender-mcp.exe", "trellis-server.exe"},
        host_keywords=("serena", "mcp-for-unity", "mcpforunityserver", "unity-mcp", "blender-mcp"),
    )
    if managed:
        return True
    by_id = {t.id: t for t in tools}
    tr_tool = by_id.get("trellis")
    if tr_tool and tr_tool.enabled and "trellis" in live_map:
        return True
    bm_tool = by_id.get("blender_mcp")
    if bm_tool and bm_tool.enabled and live_map.get("blender_open") == "1":
        port = int(bm_tool.port or 9876)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.35):
                return True
        except OSError:
            pass
    return False


def stop_all_managed_services(tools: list[ToolSpec], lang: str = "en") -> tuple[int, str]:
    """Stop all AIconomy-managed background servers and wait until processes and ports fully close."""
    is_tr = lang == "tr"
    stopped_labels: list[str] = []
    stopped_pids: set[int] = set()

    groups: list[tuple[list[psutil.Process], str]] = [
        (
            _find_managed_processes(
                {"serena.exe", "serena-agent.exe"},
                host_keywords=("serena",),
                require_all=("start-mcp-server",),
            ),
            "Serena",
        ),
        (
            _find_managed_processes(
                {"mcp-for-unity.exe", "unity-mcp.exe"},
                host_keywords=("mcp-for-unity", "mcpforunityserver", "unity-mcp"),
            ),
            "Unity MCP",
        ),
        (
            _find_managed_processes({"blender-mcp.exe"}, host_keywords=("blender-mcp",)),
            "blender-mcp",
        ),
        (
            _find_managed_processes({"trellis-server.exe"}),
            "TRELLIS",
        ),
        (
            _find_managed_processes(set(), host_keywords=("--mcp-exec",)),
            "MCP Bridge",
        ),
    ]

    # Also find frozen AIconomy.exe --mcp-exec child bridge processes (never self)
    self_pid = os.getpid()
    bridge_exes: list[psutil.Process] = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info.get("pid") == self_pid:
                continue
            nm = (p.info.get("name") or "").lower()
            if nm == "aiconomy.exe":
                cmd_s = " ".join(str(x).lower() for x in (p.info.get("cmdline") or []))
                if "--mcp-exec" in cmd_s:
                    bridge_exes.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if bridge_exes:
        groups.append((bridge_exes, "MCP Bridge"))

    all_procs: list[psutil.Process] = []
    seen_pids: set[int] = set()
    for procs, label in groups:
        for p in procs:
            if p.pid in seen_pids or p.pid == self_pid:
                continue
            # Also terminate direct children of --mcp-exec bridges (npx/node/uvx)
            if label == "MCP Bridge":
                try:
                    for ch in p.children(recursive=True):
                        if ch.pid not in seen_pids and ch.pid != self_pid:
                            seen_pids.add(ch.pid)
                            try:
                                ch.terminate()
                                all_procs.append(ch)
                                stopped_pids.add(ch.pid)
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            seen_pids.add(p.pid)
            try:
                p.terminate()
                all_procs.append(p)
                stopped_pids.add(p.pid)
                stopped_labels.append(f"{label} (PID {p.pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    # Also clean windowless non-batch blender.exe holding :9876 (K2 safe: never touches GUI or -b batch jobs)
    bm_tool = next((t for t in tools if t.id == "blender_mcp"), None)
    b_port = int(bm_tool.port or 9876) if bm_tool else 9876
    owner_pid, owner_name = find_port_owner(b_port)
    if owner_pid and owner_name.lower() == "blender.exe" and owner_pid not in seen_pids:
        try:
            bproc = psutil.Process(owner_pid)
            cmd = [str(x).lower() for x in (bproc.cmdline() or [])]
            is_batch_job = "-b" in cmd or "--background" in cmd
            has_window = owner_pid in get_gui_window_titles({"blender.exe": [owner_pid]})
            if not is_batch_job and not has_window:
                bproc.terminate()
                all_procs.append(bproc)
                stopped_pids.add(owner_pid)
                stopped_labels.append(f"blender.exe (PID {owner_pid})")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if all_procs:
        _gone, alive = psutil.wait_procs(all_procs, timeout=3.5)
        force_list: list[psutil.Process] = []
        for p in alive:
            try:
                p.kill()
                force_list.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if force_list:
            psutil.wait_procs(force_list, timeout=1.5)

    # Confirm OS TCP ports previously held by terminated PIDs are completely released
    if stopped_pids:
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            still_bound = False
            for p_num in (8080, 9121, 8790, b_port):
                cur_pid, _ = find_port_owner(p_num)
                if cur_pid and cur_pid in stopped_pids:
                    still_bound = True
                    break
            if not still_bound:
                break
            time.sleep(0.2)

    if not stopped_labels:
        msg = "Çalışan yönetilen servis yok." if is_tr else "No managed services were running."
        return 0, msg

    joined = ", ".join(stopped_labels)
    msg = f"Durduruldu: {joined}." if is_tr else f"Stopped: {joined}."
    return len(stopped_labels), msg


def enforce_tool_runtime_state(
    tool: ToolSpec,
    projects_map: dict[str, str],
    allow_stop: bool = True,
    allow_start: bool = True,
    restart_if_running: bool = False,
    lang: str = "en",
) -> str:
    """Align managed background bridge processes with a tool's enabled state."""
    is_tr = lang == "tr"
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
                    psutil.wait_procs([bproc], timeout=2.5)
                    killed.append(f"blender.exe (PID {owner_pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if not killed:
            return ""
        return f" ({', '.join(killed)} {'durduruldu' if is_tr else 'stopped'})"

    if tool.id == "trellis" and not tool.enabled:
        if not allow_stop:
            return ""
        ok, msg = free_trellis_vram(lang=lang)
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
            return f" ({', '.join(killed)} {'durduruldu' if is_tr else 'stopped'})" if killed else ""
        if not allow_start:
            return ""
        if restart_if_running:
            _terminate_all(
                _find_managed_processes(
                    {"mcp-for-unity.exe", "unity-mcp.exe"},
                    host_keywords=("mcp-for-unity", "mcpforunityserver", "unity-mcp"),
                ),
                "Unity MCP",
            )
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
                    return f" (Unity MCP :{port} {'başlatıldı' if is_tr else 'started'})"
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
            return f" ({', '.join(killed)} {'durduruldu' if is_tr else 'stopped'})" if killed else ""
        if not allow_start:
            return ""
        if restart_if_running:
            _terminate_all(
                _find_managed_processes(
                    {"serena.exe", "serena-agent.exe"},
                    host_keywords=("serena",),
                    require_all=("start-mcp-server",),
                ),
                "Serena",
            )
        owner_pid, _ = find_port_owner(port)
        if not owner_pid:
            serena_exe = pathlib.Path.home() / ".local" / "bin" / "serena.exe"
            if serena_exe.is_file():
                serena_mode = "editing" if int(tool.mode_index) == 1 else "planning"
                cmd = [
                    str(serena_exe),
                    "start-mcp-server",
                    "--transport",
                    "streamable-http",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--mode",
                    serena_mode,
                    "--mode",
                    "no-onboarding",
                ]
                proj_dir = projects_map.get(tool.project_scope, "")
                if tool.project_scope != "GLOBAL" and proj_dir and pathlib.Path(proj_dir).is_dir():
                    cmd.extend(["--project", proj_dir])
                opt_map = {o.key: o.enabled for o in tool.options}
                if opt_map.get("no_dashboard", True):
                    cmd.extend(["--open-web-dashboard", "False", "--enable-gui-log-window", "False"])
                try:
                    subprocess.Popen(cmd, creationflags=NO_WINDOW)
                    return f" (Serena :{port} {'başlatıldı' if is_tr else 'started'})"
                except Exception:
                    return ""
    return ""


def free_trellis_vram(lang: str = "en") -> tuple[bool, str]:
    """Terminate trellis-server.exe to release GPU VRAM."""
    is_tr = lang == "tr"
    stopped: list[int] = []
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            if (proc.info.get("name") or "").lower() == "trellis-server.exe":
                proc.terminate()
                stopped.append(proc.info["pid"])
    except Exception as exc:
        return False, (f"TRELLIS kontrol hatası: {exc}" if is_tr else f"TRELLIS check failed: {exc}")

    if not stopped:
        return True, (
            "TRELLIS GPU sunucusu zaten kapalı (VRAM boşta)."
            if is_tr
            else "TRELLIS GPU server is already stopped (VRAM free)."
        )
    pids = ", ".join(map(str, stopped))
    return True, (
        f"TRELLIS sunucusu (PID {pids}) kapatıldı ve VRAM boşaltıldı."
        if is_tr
        else f"Stopped TRELLIS server (PID {pids}) and released GPU VRAM."
    )


def resolve_disk_location(
    tool: ToolSpec,
    projects_map: dict[str, str],
    live_map: dict[str, str],
    lang: str = "en",
) -> str:
    """Resolve the active disk path or live process location string for a tool."""
    is_tr = lang == "tr"
    if tool.id == "serena":
        if "serena" in live_map:
            return live_map["serena"]
        exe = pathlib.Path.home() / ".local" / "bin" / "serena.exe"
        proj_dir = projects_map.get(tool.project_scope, "Global")
        return (
            f"Kurulu: {exe if exe.is_file() else 'serena'}  |  Hedef: {proj_dir}"
            if is_tr
            else f"Binary: {exe if exe.is_file() else 'serena'}  |  Target: {proj_dir}"
        )

    if tool.id in ("unity_mcp", "unity_pipeline"):
        if "unity" in live_map:
            return live_map["unity"]
        proj_dir = projects_map.get(tool.project_scope, tool.param_value) or "Global"
        return f"Unity projesi: {proj_dir}" if is_tr else f"Unity project: {proj_dir}"

    if tool.id == "blender_mcp":
        if "blender" in live_map:
            return live_map["blender"]
        b_exe = _find_blender_exe()
        if b_exe:
            return f"Kurulu: {b_exe}" if is_tr else f"Installed: {b_exe}"
        return f"Blender (:{int(tool.port or 9876)})"

    if tool.id == "trellis":
        if "trellis" in live_map:
            return live_map["trellis"]
        return f"Kurulum: {tool.param_value}" if is_tr else f"Install path: {tool.param_value}"

    if tool.id == "blender_skills":
        if tool.project_scope != "GLOBAL" and tool.project_scope in projects_map:
            p = pathlib.Path(projects_map[tool.project_scope]) / ".agents" / "skills"
            return f"Proje skill dizini: {p}" if is_tr else f"Project skills path: {p}"
        p = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
        return f"Global plugin dizini: {p}" if is_tr else f"Global plugin path: {p}"

    if tool.id == "caveman":
        active_md = pathlib.Path.home() / ".agents" / "skills" / "caveman" / "SKILL.md"
        agy_md = pathlib.Path.home() / ".gemini" / "config" / "skills" / "caveman" / "SKILL.md"
        disabled_md = pathlib.Path.home() / ".agents" / "skills_disabled" / "caveman" / "SKILL.md"
        if active_md.is_file() and agy_md.is_file():
            return f"Dosya: {active_md}  |  AGY: {agy_md}" if is_tr else f"File: {active_md}  |  AGY: {agy_md}"
        if agy_md.is_file():
            return f"AGY: {agy_md}"
        if active_md.is_file():
            return f"Dosya: {active_md}" if is_tr else f"File: {active_md}"
        if disabled_md.is_file():
            return f"Devre dışı kural: {disabled_md}" if is_tr else f"Disabled rule: {disabled_md}"
        return "Global kural" if is_tr else "Global rule"

    if (
        tool.id not in ("blender_skills", "caveman")
        and not tool.mcp_server_key
        and (tool.kind in ("skill_pack", "rule") or (tool.install_cmd or "").strip().startswith("git clone "))
    ):
        act_dir = pathlib.Path.home() / ".agents" / "skills" / tool.id
        dis_dir = pathlib.Path.home() / ".agents" / "skills_disabled" / tool.id
        if act_dir.is_dir():
            return f"Skill klasörü: {act_dir}" if is_tr else f"Skills folder: {act_dir}"
        if dis_dir.is_dir():
            return f"Devre dışı skill: {dis_dir}" if is_tr else f"Disabled skills: {dis_dir}"
        return "Skill (kurulu değil)" if is_tr else "Skill (not installed)"

    if tool.scope_selectable and tool.project_scope != "GLOBAL" and tool.project_scope in projects_map:
        return (
            f"Proje klasörü: {projects_map[tool.project_scope]}"
            if is_tr
            else f"Project folder: {projects_map[tool.project_scope]}"
        )

    return "Kapsam: Global" if is_tr else "Scope: Global"


def probe_tool_health(
    tool: ToolSpec,
    active_skills_count: int,
    projects_map: dict[str, str],
    live_map: dict[str, str],
    lang: str = "en",
    missing_required_keys: set[str] | None = None,
    runtime_active: bool = True,
) -> tuple[bool, str, str, int, str, str]:
    """Return (is_healthy, health_state, short_status_str, latency_ms, detail_msg, location_detail).

    ``health_state`` is one of: ``'ok'``, ``'warn'``, ``'error'``, ``'idle'``, ``'off'``.
    """
    loc_detail = resolve_disk_location(tool, projects_map, live_map, lang=lang)

    if tool.enabled and not runtime_active:
        return True, "idle", tr(lang, "st_stopped_standby"), -1, loc_detail, loc_detail

    if (
        tool.enabled
        and getattr(tool, "auth_mode", "key") != "oauth"
        and tool.vault_key_required
        and tool.vault_key_name
        and missing_required_keys is not None
        and tool.vault_key_name in missing_required_keys
    ):
        return (
            False,
            "warn",
            tr(lang, "st_missing_key"),
            -1,
            f"Missing {tool.vault_key_name}",
            loc_detail,
        )

    if tool.id == "blender_skills":
        plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
        installed = (plugin_dir / "skills").is_dir() or (plugin_dir / "skills_disabled").is_dir()
        if not tool.enabled:
            return False, "off", tr(lang, "st_disabled"), -1, loc_detail, loc_detail
        if not installed:
            return True, "warn", tr(lang, "st_not_installed"), -1, loc_detail, loc_detail
        return True, "ok", tr(lang, "st_active_count", on=active_skills_count), 1, loc_detail, loc_detail

    if tool.id == "caveman":
        if not tool.enabled:
            return False, "off", tr(lang, "st_disabled"), -1, loc_detail, loc_detail
        active_md = pathlib.Path.home() / ".agents" / "skills" / "caveman" / "SKILL.md"
        agy_md = pathlib.Path.home() / ".gemini" / "config" / "skills" / "caveman" / "SKILL.md"
        disabled_md = pathlib.Path.home() / ".agents" / "skills_disabled" / "caveman" / "SKILL.md"
        modes = localized_tool_modes(tool, lang)
        mode_short = modes[min(tool.mode_index, len(modes) - 1)].split()[0] if modes else ""
        label = f"{tr(lang, 'st_ready')} ({mode_short})" if mode_short else tr(lang, "st_ready")
        want_agy = bool(tool.clients.get("AGY", False))
        want_agents = bool(tool.clients.get("CDX", False) or tool.clients.get("CLD", False) or tool.clients.get("CUR", False))
        if (want_agy and agy_md.is_file() and (not want_agents or active_md.is_file())) or (
            want_agents and not want_agy and active_md.is_file()
        ):
            src_str = str(agy_md if (want_agy and agy_md.is_file()) else active_md)
            return True, "ok", label, 1, src_str, loc_detail
        if active_md.is_file() or disabled_md.is_file():
            return True, "idle", label, 1, str(active_md if active_md.is_file() else disabled_md), loc_detail
        return False, "warn", tr(lang, "st_not_installed"), -1, str(active_md), loc_detail

    if tool.id == "blender_mcp":
        port = int(tool.port or 9876)
        blender_window_open = live_map.get("blender_open") == "1"
        zombie_pid = live_map.get("blender_zombie_pid", "")
        if not tool.enabled:
            return False, "off", tr(lang, "st_disabled"), -1, loc_detail, loc_detail

        if not blender_window_open:
            if zombie_pid:
                return False, "warn", tr(lang, "st_blender_zombie", pid=zombie_pid), -1, loc_detail, loc_detail
            return False, "idle", tr(lang, "st_blender_closed", port=port), -1, loc_detail, loc_detail

        t0 = time.perf_counter()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.65):
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                return True, "ok", tr(lang, "st_running", ms=ms), ms, f"127.0.0.1:{port} active", loc_detail
        except OSError as exc:
            return False, "warn", tr(lang, "st_blender_no_sock", port=port), -1, str(exc), loc_detail

    if tool.port:
        port = int(tool.port)
        if not tool.enabled:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.35):
                    return False, "off", tr(lang, "st_port_open_disabled", port=port), -1, loc_detail, loc_detail
            except OSError:
                return False, "off", tr(lang, "st_disabled"), -1, loc_detail, loc_detail

        t0 = time.perf_counter()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.65):
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                if tool.health_url:
                    try:
                        with urllib.request.urlopen(tool.health_url, timeout=1.2) as resp:
                            body = resp.read(64).decode("utf-8", errors="replace").strip()
                            return True, "ok", tr(lang, "st_running", ms=ms), ms, f"HTTP 200: {body}", loc_detail
                    except Exception as exc:
                        return False, "error", tr(lang, "st_http_err", port=port), ms, str(exc), loc_detail
                return True, "ok", tr(lang, "st_running", ms=ms), ms, f"127.0.0.1:{port} TCP OK", loc_detail
        except OSError as exc:
            if tool.id == "trellis":
                cli_exe = pathlib.Path(tool.param_value) / "runtime" / "trellis-cli.exe"
                if cli_exe.is_file():
                    return False, "idle", tr(lang, "st_standby", port=port), -1, str(cli_exe), loc_detail
            return False, "error", tr(lang, "st_offline", port=port), -1, str(exc), loc_detail

    if tool.id == "unity_pipeline":
        if not tool.enabled:
            return False, "off", tr(lang, "st_disabled"), -1, loc_detail, loc_detail
        target_proj = projects_map.get(tool.project_scope, tool.param_value)
        manifest = pathlib.Path(target_proj) / "Packages" / "manifest.json"
        if manifest.is_file() and "com.unity.pipeline" in manifest.read_text(encoding="utf-8", errors="ignore"):
            return True, "ok", tr(lang, "st_installed"), 2, str(manifest), loc_detail
        return False, "warn", tr(lang, "st_missing_pkg"), -1, str(manifest), loc_detail

    if not tool.enabled:
        return False, "off", tr(lang, "st_disabled"), -1, loc_detail, loc_detail

    if (
        tool.id not in ("blender_skills", "caveman")
        and not tool.mcp_server_key
        and (tool.kind in ("skill_pack", "rule") or (tool.install_cmd or "").strip().startswith("git clone "))
    ):
        act_dir = pathlib.Path.home() / ".agents" / "skills" / tool.id
        dis_dir = pathlib.Path.home() / ".agents" / "skills_disabled" / tool.id
        if act_dir.is_dir():
            return True, "ok", tr(lang, "st_ready"), 1, str(act_dir), loc_detail
        if dis_dir.is_dir():
            return True, "idle", tr(lang, "st_ready"), 1, str(dis_dir), loc_detail
        return False, "warn", tr(lang, "st_not_installed"), -1, str(act_dir), loc_detail

    return True, "ok", tr(lang, "st_ready"), 2, tool.mcp_command or tool.install_cmd or "stdio", loc_detail
