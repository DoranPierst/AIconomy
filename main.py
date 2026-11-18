"""AI Araç & Token Ekonomisi Kontrol Merkezi — Tek Örnekli (Mutex + Ön Plana Getirme / Eski Sürüm Yenileme) Başlatıcı."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import pathlib
import sys
import time

import psutil
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.updater import get_current_app_version


def _focus_same_version_or_replace_stale(app_ver: str) -> bool:
    """Aynı masaüstünde aynı sürüm zaten açıksa (tepsiye gizlenmiş olsa bile) öne getirir ve True döndürür.
    Eski sürüm veya farklı/hayalet oturumda kalmış süreç varsa temizler ve False döndürür.
    """
    if os.name != "nt":
        return False

    found_hwnd: list[int] = []
    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

        expected_prefixes = ("AIconomy", "AI Araç & Token Ekonomisi Kontrol Merkezi")
        expected_ver = f"{app_ver}v"

        @WNDENUMPROC
        def _cb(hwnd: int, _lparam: int) -> bool:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if title.startswith(expected_prefixes) and expected_ver in title:
                    found_hwnd.append(int(hwnd))
                    return False
            return True

        user32.EnumWindows(_cb, 0)
        if found_hwnd:
            hwnd = found_hwnd[0]
            user32.ShowWindow(hwnd, 5)  # SW_SHOW (tepsiden geri getir)
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE (simge durumundaysa büyüt)
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass

    # Aynı sürüm penceresi bu masaüstünde yoksa, eski sürüm / hayalet süreçleri temizle
    self_pids = {os.getpid(), os.getppid()}
    stale: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            nm = (proc.info.get("name") or "").lower()
            if pid not in self_pids and nm in ("aiconomy.exe", "ai-arac-merkezi.exe"):
                proc.terminate()
                stale.append(proc)
        except Exception:
            pass
    if stale:
        psutil.wait_procs(stale, timeout=2.0)
    return False


def main() -> int:
    app_ver = get_current_app_version()
    mutex_name = "Local\\AIAracMerkeziPySide6Mutex"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.kernel32.CloseHandle(mutex)
        if _focus_same_version_or_replace_stale(app_ver):
            return 0
        time.sleep(0.25)
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)

    if getattr(sys, "frozen", False):
        root_dir = pathlib.Path(sys.executable).resolve().parent
    else:
        root_dir = pathlib.Path(__file__).resolve().parent
    data_dir = root_dir / "data"

    app = QApplication(sys.argv)
    app.setApplicationName("AIconomy")
    win = MainWindow(data_dir=data_dir)
    win.show()
    code = app.exec()
    ctypes.windll.kernel32.CloseHandle(mutex)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
