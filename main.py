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

# Ultra-fast pre-Qt RAM secret bridge for stdio MCP servers (zero GUI overhead, <10ms)
if len(sys.argv) >= 3 and sys.argv[1] == "--mcp-exec":
    from app.mcp_bridge import run_mcp_exec_cli

    raise SystemExit(run_mcp_exec_cli(sys.argv[2:]))

import ctypes
import os
import pathlib
import shutil

import psutil
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow, create_app_icon

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


def main() -> int:
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

    win = MainWindow(data_dir=resolve_data_dir(_app_root_dir()))

    def _on_new_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(300)
        msg = bytes(conn.readAll()).strip()
        if msg == b"request_entropy":
            ent = win.vault.export_entropy_hex()
            reply = f"ENTROPY:{ent}".encode("ascii") if ent else b"LOCKED"
            conn.write(reply)
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
