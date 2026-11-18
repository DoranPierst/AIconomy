"""Application stylesheets (dark/light) and icon loader."""
from __future__ import annotations

import pathlib
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

DARK_QSS = """
QMainWindow, QDialog { background-color: #0f141c; color: #e6edf3; font-family: 'Segoe UI'; font-size: 12px; }
QWidget { color: #e6edf3; font-family: 'Segoe UI'; font-size: 12px; }
QTabWidget::pane { border: 1px solid #243042; border-radius: 6px; background-color: #141b26; }
QTabBar::tab { background: #161f2c; color: #94a3b8; padding: 7px 14px; margin-right: 4px; border-top-left-radius: 6px; border-top-right-radius: 6px; border: 1px solid #243042; }
QTabBar::tab:selected { background: #2563eb; color: #ffffff; border-color: #2563eb; font-weight: 600; }
QPushButton { background-color: #1c2636; border: 1px solid #2e3d54; border-radius: 5px; padding: 5px 10px; color: #e6edf3; }
QPushButton:hover { background-color: #263449; border-color: #3b82f6; }
QPushButton:disabled { color: #556378; background-color: #151c27; border-color: #1f2937; }
QPushButton#primaryBtn { background-color: #2563eb; border-color: #2563eb; color: #ffffff; font-weight: 600; }
QPushButton#primaryBtn:hover { background-color: #1d4ed8; }
QPushButton#successBtn { background-color: #15803d; border-color: #16a34a; color: #ffffff; font-weight: 600; }
QPushButton#warnBtn { background-color: #7c2d12; border-color: #ea580c; color: #ffedd5; font-weight: 600; }
QLineEdit, QComboBox, QPlainTextEdit { background-color: #0f141c; border: 1px solid #2e3d54; border-radius: 5px; padding: 4px 8px; color: #e6edf3; }
QTableWidget { background-color: #111823; alternate-background-color: #151e2b; gridline-color: #1f2a3c; border: 1px solid #243042; border-radius: 6px; }
QWidget#cellBox { background: transparent; }
QHeaderView::section { background-color: #182232; color: #94a3b8; padding: 6px 10px; border: none; border-right: 1px solid #2c3d55; border-bottom: 1px solid #2c3d55; font-weight: 600; }
QHeaderView::section:hover { background-color: #1f2e45; color: #e2e8f0; }
QFrame#card { background-color: #151e2b; border: 1px solid #243042; border-radius: 6px; }
QProgressBar { border: 1px solid #2e3d54; border-radius: 4px; background: #0f141c; text-align: center; color: #e6edf3; min-height: 18px; }
QProgressBar::chunk { background-color: #2563eb; border-radius: 3px; }
"""

LIGHT_QSS = """
QMainWindow, QDialog { background-color: #f4f6fb; color: #1e293b; font-family: 'Segoe UI'; font-size: 12px; }
QWidget { color: #1e293b; font-family: 'Segoe UI'; font-size: 12px; }
QTabWidget::pane { border: 1px solid #cbd5e1; border-radius: 6px; background-color: #ffffff; }
QTabBar::tab { background: #e2e8f0; color: #475569; padding: 7px 14px; margin-right: 4px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: #2563eb; color: #ffffff; font-weight: 600; }
QPushButton { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 5px; padding: 5px 10px; color: #1e293b; }
QPushButton:hover { background-color: #eff6ff; border-color: #2563eb; }
QPushButton#primaryBtn { background-color: #2563eb; border-color: #2563eb; color: #ffffff; font-weight: 600; }
QPushButton#successBtn { background-color: #16a34a; border-color: #16a34a; color: #ffffff; font-weight: 600; }
QPushButton#warnBtn { background-color: #ea580c; border-color: #ea580c; color: #ffffff; font-weight: 600; }
QLineEdit, QComboBox, QPlainTextEdit { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 5px; padding: 4px 8px; color: #1e293b; }
QTableWidget { background-color: #ffffff; alternate-background-color: #f8fafc; gridline-color: #e2e8f0; border: 1px solid #cbd5e1; border-radius: 6px; }
QWidget#cellBox { background: transparent; }
QHeaderView::section { background-color: #f1f5f9; color: #475569; padding: 6px 10px; border: none; border-right: 1px solid #cbd5e1; border-bottom: 1px solid #cbd5e1; font-weight: 600; }
QHeaderView::section:hover { background-color: #e2e8f0; color: #0f172a; }
QFrame#card { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; }
"""


def create_app_icon() -> QIcon:
    candidates: list[pathlib.Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(pathlib.Path(meipass) / "assets" / "aiconomy.png")
        candidates.append(pathlib.Path(sys.executable).resolve().parent / "assets" / "aiconomy.png")
    candidates.append(pathlib.Path(__file__).resolve().parent.parent.parent / "assets" / "aiconomy.png")
    for c in candidates:
        if c.is_file():
            ico = QIcon(str(c))
            if not ico.isNull():
                return ico

    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#2563eb"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", 22, QFont.Weight.Bold)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "AI")
    p.end()
    return QIcon(pix)
