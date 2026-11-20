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
import os
import pathlib
import shutil

import psutil
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow, create_app_icon
from app.mcp_bridge import BRIDGE_EXE_NAME

APP_USER_MODEL_ID = "DoranPierst.AIconomy.App"
_SESSION_SUFFIX = (os.environ.get("USERNAME") or "user").replace(" ", "_")
MUTEX_NAME = f"Local\\AIconomy.SingleInstance.{_SESSION_SUFFIX}"
SERVER_NAME = f"AIconomy.SingleInstance.{_SESSION_SUFFIX}"
LEGACY_MUTEX_NAME = "Local\\AIAracMerkeziPySide6Mutex"
LEGACY_EXE_NAMES = ("aiconomy.exe", "ai-arac-merkezi.exe")


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
    if not sock.waitForConnected(800):
        return False
    sock.write(b"activate")
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def _terminate_stale_instances() -> None:
    """Closes old builds that hold the mutex but have no activation server (pre-1.3.4 versions or hung processes)."""
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
        _terminate_stale_instances()
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

    def _on_new_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(300)
        msg = bytes(conn.readAll()).strip()

        # Never expose raw Master Passphrase PBKDF2 entropy over IPC!
        if msg == b"request_entropy":
            conn.write(b"DENIED")
            conn.flush()
            conn.waitForBytesWritten(300)
            conn.disconnectFromServer()
            return

        if msg.startswith(b"resolve_secret:"):
            if not _is_trusted_bridge_peer(conn, data_dir):
                conn.write(b"DENIED")
            elif win.vault.is_locked():
                conn.write(b"LOCKED")
            else:
                req_tid = msg.split(b":", 1)[1].decode("ascii", errors="ignore").strip()
                t_obj = next(
                    (t for t in win.tools if t.id == req_tid and getattr(t, "in_workspace", True)),
                    None,
                )
                if t_obj is None or not t_obj.vault_key_name:
                    conn.write(b"DENIED")
                else:
                    sec = win.vault.get_secret(t_obj.vault_key_name)
                    if sec:
                        b64 = base64.b64encode(sec.encode("utf-8")).decode("ascii")
                        conn.write(f"SECRET:{b64}".encode("ascii"))
                    else:
                        conn.write(b"EMPTY")
            conn.flush()
            conn.waitForBytesWritten(300)
            conn.disconnectFromServer()
            return

        conn.disconnectFromServer()
        _bring_to_front(win)

    server.newConnection.connect(_on_new_connection)
    win.show()
    code = app.exec()
    server.close()
    kernel32.CloseHandle(mutex)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
