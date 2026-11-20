"""AIconomy — single-instance desktop launcher.

* Single instance: the first instance owns a named mutex and a QLocalServer. A second launch
  connects to that server, asks the running window to come to the front and exits. This does
  not depend on the (localized) window title, so it works in every UI language.
* Data folder: user data lives in %LOCALAPPDATA%\\AIconomy\\data so the app also works when the
  .exe is placed in a read-only location (e.g. Program Files). Data from the legacy
  "<exe folder>\\data" location is copied over once. Create an empty "portable.txt" next to the
  .exe to keep using the legacy folder.
"""
from __future__ import annotations

import sys

# Ultra-fast pre-Qt RAM secret bridge for stdio MCP servers
if len(sys.argv) >= 3 and sys.argv[1] == "--mcp-exec":
    from app.mcp_bridge import run_mcp_exec_cli

    raise SystemExit(run_mcp_exec_cli(sys.argv[2:]))

import base64
import contextlib
import ctypes
from ctypes import wintypes
import json
import os
import pathlib
import shutil

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow, create_app_icon
from app.mcp_bridge import BRIDGE_EXE_NAME
from app.mcp_config import build_effective_stdio_spec

APP_USER_MODEL_ID = "DoranPierst.AIconomy.App"
_SESSION_SUFFIX = (os.environ.get("USERNAME") or "user").replace(" ", "_")
MUTEX_NAME = f"Local\\AIconomy.SingleInstance.{_SESSION_SUFFIX}"
SERVER_NAME = f"AIconomy.SingleInstance.{_SESSION_SUFFIX}"
LEGACY_MUTEX_NAME = "Local\\AIAracMerkeziPySide6Mutex"
# Strictly pre-rename legacy binaries ONLY — never terminate a running modern AIconomy.exe!
LEGACY_EXE_NAMES = ("ai-arac-merkezi.exe",)


def _app_root_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def _cleanup_old_exe_swap() -> None:
    """Remove leftover ``AIconomy.exe.old`` files left behind after an atomic NTFS self-update swap."""
    if not getattr(sys, "frozen", False):
        return
    try:
        cur_exe = pathlib.Path(sys.executable).resolve()
        old_swap = cur_exe.with_suffix(".exe.old")
        if old_swap.is_file():
            old_swap.unlink(missing_ok=True)
        for cand in cur_exe.parent.glob(f"{cur_exe.name}.*.old"):
            with contextlib.suppress(OSError):
                cand.unlink(missing_ok=True)
    except OSError:
        pass


def resolve_data_dir(root_dir: pathlib.Path) -> pathlib.Path:
    legacy_dir = root_dir / "data"
    if (root_dir / "portable.txt").is_file():
        legacy_dir.mkdir(parents=True, exist_ok=True)
        return legacy_dir

    base = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
    data_dir = pathlib.Path(base) / "AIconomy" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # One-time migration: copy (not move) legacy files so the old folder stays as a backup.
    has_data = any(data_dir.iterdir())
    if not has_data and legacy_dir.is_dir():
        for item in legacy_dir.iterdir():
            try:
                if item.is_file():
                    shutil.copy2(item, data_dir / item.name)
                elif item.is_dir():
                    shutil.copytree(item, data_dir / item.name, dirs_exist_ok=True)
            except OSError:
                continue
    return data_dir


def _activate_running_instance() -> bool:
    """Asks an already running instance to show its window. Returns True on success."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(1200):
        return False
    sock.write(b"activate")
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def _terminate_stale_instances() -> int:
    """Close pre-1.3.4 legacy builds that hold the old mutex without an activation server."""
    self_pids = {os.getpid(), os.getppid()}
    stale: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info.get("pid") in self_pids:
                continue
            if (proc.info.get("name") or "").lower() in LEGACY_EXE_NAMES:
                proc.terminate()
                stale.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if stale:
        psutil.wait_procs(stale, timeout=2.0)
    return len(stale)


def _bring_to_front(win: MainWindow) -> None:
    win.showNormal()
    win.raise_()
    win.activateWindow()


def _is_trusted_bridge_peer(conn: QLocalSocket, data_dir: pathlib.Path) -> bool:
    """Verify via Win32 kernel ``GetNamedPipeClientProcessId`` that the pipe caller is an official AIconomy bridge."""
    if os.name != "nt":
        return False
    try:
        desc = int(conn.socketDescriptor())
        if desc <= 0:
            return False
        client_pid = wintypes.ULONG(0)
        ok = ctypes.windll.kernel32.GetNamedPipeClientProcessId(
            wintypes.HANDLE(desc),
            ctypes.byref(client_pid),
        )
        if not ok or not client_pid.value:
            return False
        pid = int(client_pid.value)
        if pid == os.getpid():
            return True

        peer = psutil.Process(pid)
        peer_exe = pathlib.Path(peer.exe()).resolve()
        self_exe = pathlib.Path(sys.executable).resolve()
        bridge_exe = (data_dir / "bin" / BRIDGE_EXE_NAME).resolve()

        if peer_exe == bridge_exe:
            return True
        if peer_exe == self_exe:
            if getattr(sys, "frozen", False):
                return True
            cmdline = [str(x) for x in (peer.cmdline() or [])]
            return "--mcp-exec" in cmdline
    except Exception:
        return False
    return False


def _authorize_bridge_tool_request(
    conn: QLocalSocket,
    raw_payload: str,
    win: MainWindow,
    data_dir: pathlib.Path,
    require_dir_binding: bool,
) -> tuple[str, object | None]:
    """Validate kernel peer identity, exact data_dir match, unlocked vault, running runtime, and enabled tool."""
    if not _is_trusted_bridge_peer(conn, data_dir):
        return "DENIED", None

    if "|" in raw_payload:
        req_tid, dir_b64 = raw_payload.split("|", 1)
        req_tid = req_tid.strip()
        try:
            decoded_dir = base64.b64decode(dir_b64.strip().encode("ascii")).decode("utf-8")
            if pathlib.Path(decoded_dir).resolve() != data_dir.resolve():
                return "DENIED", None
        except Exception:
            return "DENIED", None
    elif require_dir_binding:
        return "DENIED", None
    else:
        req_tid = raw_payload.strip()

    if win.vault.is_locked():
        return "LOCKED", None
    if not (win.runtime_started and getattr(win, "_runtime_state", "") == "running"):
        return "DENIED", None

    t_obj = next(
        (t for t in win.tools if t.id == req_tid and getattr(t, "in_workspace", True) and t.enabled),
        None,
    )
    if t_obj is None:
        return "DENIED", None
    return "OK", t_obj


def handle_ipc_message(
    msg: bytes,
    conn: QLocalSocket,
    win: MainWindow,
    data_dir: pathlib.Path,
) -> tuple[bytes | None, bool]:
    """Process a single local pipe frame and return ``(optional_reply_bytes, should_activate_window)``."""
    clean = msg.strip()
    if not clean:
        return None, False

    if clean == b"activate":
        return b"OK\n", True

    # Never expose raw Master Passphrase PBKDF2 entropy over IPC!
    if clean == b"request_entropy":
        return b"DENIED\n", False

    if clean.startswith(b"resolve_launch:"):
        raw_arg = clean.split(b":", 1)[1].decode("ascii", errors="ignore").strip()
        status, t_obj = _authorize_bridge_tool_request(conn, raw_arg, win, data_dir, require_dir_binding=True)
        if status != "OK" or t_obj is None:
            return f"{status}\n".encode("ascii"), False
        spec = build_effective_stdio_spec(t_obj, win.vault, wrap_windows_npx=False)  # type: ignore[arg-type]
        if spec is None:
            return b"DENIED\n", False
        cmd, args, env = spec
        launch_doc = {
            "name": getattr(t_obj, "name", ""),
            "cmd": cmd,
            "args": args,
            "env": env,
            "vault_key": getattr(t_obj, "vault_key_name", ""),
        }
        b64 = base64.b64encode(json.dumps(launch_doc, ensure_ascii=False).encode("utf-8")).decode("ascii")
        return f"LAUNCH:{b64}\n".encode("ascii"), False

    if clean.startswith(b"resolve_secret:"):
        raw_arg = clean.split(b":", 1)[1].decode("ascii", errors="ignore").strip()
        status, t_obj = _authorize_bridge_tool_request(conn, raw_arg, win, data_dir, require_dir_binding=False)
        if status != "OK" or t_obj is None:
            return f"{status}\n".encode("ascii"), False
        vk = getattr(t_obj, "vault_key_name", "")
        if not vk:
            return b"DENIED\n", False
        sec = win.vault.get_secret(vk)
        if sec:
            b64 = base64.b64encode(sec.encode("utf-8")).decode("ascii")
            return f"SECRET:{b64}\n".encode("ascii"), False
        return b"EMPTY\n", False

    return b"DENIED\n", False


def main() -> int:
    _cleanup_old_exe_swap()
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("AIconomy")
    app.setWindowIcon(create_app_icon())

    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        if _activate_running_instance():
            kernel32.CloseHandle(mutex)
            return 0
        if _terminate_stale_instances() == 0:
            # Another modern AIconomy instance owns the mutex; never force-kill it!
            kernel32.CloseHandle(mutex)
            return 0
    else:
        # Builds before 1.3.4 used a different mutex name and have no activation server.
        legacy = kernel32.OpenMutexW(0x00100000, False, LEGACY_MUTEX_NAME)  # SYNCHRONIZE
        if legacy:
            kernel32.CloseHandle(legacy)
            _terminate_stale_instances()

    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    data_dir = resolve_data_dir(_app_root_dir())
    win = MainWindow(data_dir=data_dir)
    active_conns: set[QLocalSocket] = set()

    def _on_new_connection() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is None:
                continue
            active_conns.add(conn)
            handled = False

            def _cleanup(c: QLocalSocket = conn) -> None:
                active_conns.discard(c)
                c.deleteLater()

            def _process_ready(c: QLocalSocket = conn) -> None:
                nonlocal handled
                if handled:
                    return
                msg = bytes(c.readAll())
                if not msg:
                    return
                handled = True
                reply, should_activate = handle_ipc_message(msg, c, win, data_dir)
                if reply is not None:
                    c.write(reply)
                    c.flush()
                    c.waitForBytesWritten(200)
                c.disconnectFromServer()
                if should_activate:
                    _bring_to_front(win)

            conn.readyRead.connect(_process_ready)
            conn.disconnected.connect(_cleanup)
            QTimer.singleShot(1500, lambda c=conn: c.disconnectFromServer() if c in active_conns else None)
            if conn.bytesAvailable() > 0:
                _process_ready()

    server.newConnection.connect(_on_new_connection)
    win.show()
    code = app.exec()
    server.close()
    kernel32.CloseHandle(mutex)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
