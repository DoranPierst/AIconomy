"""AI Araç & Token Ekonomisi Kontrol Merkezi — Tek Örnekli (Mutex) Masaüstü Başlatıcı."""
from __future__ import annotations

import ctypes
import pathlib
import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def main() -> int:
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\AIAracMerkeziPySide6Mutex")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.kernel32.CloseHandle(mutex)
        return 0

    if getattr(sys, "frozen", False):
        root_dir = pathlib.Path(sys.executable).resolve().parent
    else:
        root_dir = pathlib.Path(__file__).resolve().parent
    data_dir = root_dir / "data"

    app = QApplication(sys.argv)
    app.setApplicationName("AI Araç & Token Ekonomisi Kontrol Merkezi")
    win = MainWindow(data_dir=data_dir)
    win.show()
    code = app.exec()
    ctypes.windll.kernel32.CloseHandle(mutex)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
