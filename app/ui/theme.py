"""Minimalist dark and light themes and application icon loader."""
from __future__ import annotations

import pathlib
import sys

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QProxyStyle, QStyle


class MinimalStyle(QProxyStyle):
    """Draw crisp anti-aliased chevrons for QComboBox and checkmarks for QCheckBox."""

    def __init__(self, is_light: bool = False) -> None:
        super().__init__("Fusion")
        self.is_light = is_light

    def drawPrimitive(self, element, option, painter, widget=None) -> None:  # noqa: N802
        if element == QStyle.PrimitiveElement.PE_IndicatorArrowDown:
            r = option.rect
            cx, cy = r.center().x(), r.center().y()
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            col = QColor("#64748b" if self.is_light else "#94a3b8")
            pen = QPen(col, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath()
            path.moveTo(QPointF(cx - 3.6, cy - 1.5))
            path.lineTo(QPointF(cx, cy + 2.2))
            path.lineTo(QPointF(cx + 3.6, cy - 1.5))
            painter.drawPath(path)
            painter.restore()
            return
        if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            r = option.rect
            checked = bool(option.state & QStyle.StateFlag.State_On)
            hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if checked:
                bg = QColor("#2563eb")
                border = QColor("#3b82f6")
            else:
                bg = QColor("#ffffff" if self.is_light else "#0c1117")
                border = QColor("#2563eb" if hover else ("#cbd5e1" if self.is_light else "#334155"))
            painter.setPen(QPen(border, 1.2))
            painter.setBrush(bg)
            box = r.adjusted(1, 1, -1, -1)
            painter.drawRoundedRect(box, 4, 4)
            if checked:
                pen = QPen(QColor("#ffffff"), 1.8)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                cx, cy = box.center().x(), box.center().y()
                path = QPainterPath()
                path.moveTo(QPointF(cx - 3.4, cy + 0.2))
                path.lineTo(QPointF(cx - 0.8, cy + 2.8))
                path.lineTo(QPointF(cx + 3.8, cy - 2.6))
                painter.drawPath(path)
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)

DARK_QSS = """
QMainWindow, QDialog { background-color: #0c1117; color: #e6edf3; font-family: 'Segoe UI'; font-size: 12px; }
QWidget { color: #e6edf3; font-family: 'Segoe UI'; font-size: 12px; }

QTabWidget::pane {
    border: 1px solid #1e293b;
    border-radius: 8px;
    background-color: #111822;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #94a3b8;
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid transparent;
    font-weight: 500;
}
QTabBar::tab:hover {
    color: #e2e8f0;
    background: #161f2e;
}
QTabBar::tab:selected {
    background: #111822;
    color: #f8fafc;
    border: 1px solid #1e293b;
    border-bottom: 2px solid #3b82f6;
    font-weight: 600;
}

QPushButton {
    background-color: #16202e;
    border: 1px solid #263549;
    border-radius: 6px;
    padding: 5px 12px;
    color: #e2e8f0;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #1e2c40;
    border-color: #3b82f6;
}
QPushButton:pressed {
    background-color: #172334;
}
QPushButton:disabled {
    color: #526175;
    background-color: #111822;
    border-color: #1b2432;
}
QPushButton#primaryBtn {
    background-color: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primaryBtn:hover {
    background-color: #1d4ed8;
    border-color: #1d4ed8;
}
QPushButton#successBtn {
    background-color: #059669;
    border-color: #059669;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#successBtn:hover {
    background-color: #047857;
}
QPushButton#warnBtn {
    background-color: #9a3412;
    border-color: #ea580c;
    color: #ffedd5;
    font-weight: 600;
}
QPushButton#warnBtn:hover {
    background-color: #c2410c;
}
QPushButton#runtimeStartBtn {
    background-color: #059669;
    border: 1px solid #10b981;
    color: #ffffff;
    font-weight: 600;
    padding: 5px 14px;
}
QPushButton#runtimeStartBtn:hover {
    background-color: #047857;
    border-color: #34d399;
}
QPushButton#runtimeStartBtn:disabled {
    background-color: #0b2e24;
    border: 1px solid #14533d;
    color: #6ee7b7;
}
QPushButton#runtimeStopBtn {
    background-color: #b45309;
    border: 1px solid #f59e0b;
    color: #fef3c7;
    font-weight: 600;
    padding: 5px 14px;
}
QPushButton#runtimeStopBtn:hover {
    background-color: #d97706;
    border-color: #fbbf24;
    color: #ffffff;
}
QPushButton#runtimeStopBtn:disabled {
    background-color: #3b2309;
    border: 1px solid #78350f;
    color: #fcd34d;
}
QPushButton#ghostBtn {
    background-color: transparent;
    border: 1px solid transparent;
    color: #94a3b8;
    padding: 4px 8px;
}
QPushButton#ghostBtn:hover {
    background-color: #1a2434;
    color: #f8fafc;
    border-color: #263549;
}
QPushButton#iconBtn {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px;
}
QPushButton#iconBtn:hover {
    background-color: #1e2c40;
    border-color: #2d3f58;
}
QPushButton#updatePillBtn {
    background-color: #2a1c0b;
    border: 1px solid #d97706;
    border-radius: 4px;
    color: #fbbf24;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 700;
}
QPushButton#updatePillBtn:hover {
    background-color: #45290d;
    border-color: #f59e0b;
}
QPushButton#tokenSummaryBtn {
    background-color: #0b241d;
    border: 1px solid #059669;
    border-radius: 6px;
    color: #34d399;
    padding: 3px 10px;
    font-family: Consolas, 'Segoe UI', monospace;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#tokenSummaryBtn:hover {
    background-color: #11382d;
    border-color: #10b981;
    color: #6ee7b7;
}
QPushButton#newProfileBtn {
    background-color: #132036;
    border: 1px solid #2563eb;
    color: #93c5fd;
    font-weight: 600;
    padding: 5px 11px;
}
QPushButton#newProfileBtn:hover {
    background-color: #1e3a5f;
    border-color: #60a5fa;
    color: #ffffff;
}
QPushButton#tagBenefitBtn, QLabel#tagBenefitPill {
    background-color: #08271f;
    border: 1px solid #0d5c46;
    border-radius: 3px;
    color: #34d399;
    padding: 0px 6px;
    font-size: 10px;
    font-weight: 600;
}
QPushButton#tagBenefitBtn:hover {
    background-color: #0f3d30;
    border-color: #10b981;
    color: #6ee7b7;
}
QPushButton#tagDomainBtn, QLabel#tagDomainPill {
    background-color: #141e2d;
    border: 1px solid #253449;
    border-radius: 3px;
    color: #94a3b8;
    padding: 0px 6px;
    font-size: 10px;
    font-weight: 500;
}
QPushButton#tagDomainBtn:hover {
    background-color: #1e2d42;
    border-color: #3b82f6;
    color: #e2e8f0;
}
QPushButton#wizBenefitChip {
    background-color: #0d1d18;
    border: 1px solid #14533d;
    border-radius: 6px;
    color: #6ee7b7;
    padding: 5px 15px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#wizBenefitChip:hover {
    background-color: #133026;
    border-color: #10b981;
}
QPushButton#wizBenefitChip:checked {
    background-color: #059669;
    border: 1px solid #34d399;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#wizDomainChip {
    background-color: #131c29;
    border: 1px solid #263549;
    border-radius: 6px;
    color: #cbd5e1;
    padding: 5px 9px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton#wizDomainChip:hover {
    background-color: #1b283b;
    border-color: #3b82f6;
}
QPushButton#wizDomainChip:checked {
    background-color: #2563eb;
    border: 1px solid #60a5fa;
    color: #ffffff;
    font-weight: 700;
}

QLineEdit, QComboBox, QPlainTextEdit {
    background-color: #0c1117;
    border: 1px solid #263549;
    border-radius: 6px;
    padding: 5px 9px;
    color: #e6edf3;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
    border-color: #3b82f6;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border: none;
}
QComboBox::down-arrow {
    image: url(__CHEVRON_DARK__);
    width: 12px;
    height: 12px;
    margin-right: 4px;
}
QComboBox QAbstractItemView {
    background-color: #111822;
    border: 1px solid #263549;
    selection-background-color: #1e3a5f;
    selection-color: #f8fafc;
    color: #e6edf3;
    outline: none;
}

QMenu {
    background-color: #131b27;
    border: 1px solid #263549;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 20px 6px 12px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #1e3a5f;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: #1e293b;
    margin: 4px 6px;
}

QTableWidget {
    background-color: #0f151f;
    alternate-background-color: #121a26;
    gridline-color: #1b2535;
    border: 1px solid #1e293b;
    border-radius: 8px;
}
QWidget#cellBox { background: transparent; }
QScrollArea { background: transparent; border: none; }
QHeaderView::section {
    background-color: #141c28;
    color: #94a3b8;
    padding: 7px 10px;
    border: none;
    border-right: 1px solid #1e293b;
    border-bottom: 1px solid #1e293b;
    font-weight: 600;
    font-size: 11px;
}
QHeaderView::section:hover {
    background-color: #1b2638;
    color: #e2e8f0;
}

QFrame#card {
    background-color: #141c28;
    border: 1px solid #1e293b;
    border-radius: 8px;
}
QFrame#bannerWarn {
    background-color: #21170c;
    border: 1px solid #b45309;
    border-radius: 8px;
}
QFrame#bannerInfo {
    background-color: #101d33;
    border: 1px solid #2563eb;
    border-radius: 8px;
}

QProgressBar {
    border: 1px solid #263549;
    border-radius: 5px;
    background: #0c1117;
    text-align: center;
    color: #cbd5e1;
    font-size: 11px;
    min-height: 18px;
}
QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 4px;
}
QProgressBar#slimBar {
    min-height: 7px;
    max-height: 7px;
    border-radius: 4px;
}
QListWidget {
    background-color: #0f151f;
    border: 1px solid #1e293b;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    padding: 7px 10px;
    border-radius: 5px;
}
QListWidget::item:selected {
    background-color: #1e3a5f;
    color: #ffffff;
}

QCheckBox {
    spacing: 7px;
}

QScrollBar:vertical {
    background: #0c1117;
    width: 10px;
    margin: 2px 0px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #263549;
    min-height: 28px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background: #3b4f6b;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0px;
}
QScrollBar:horizontal {
    background: #0c1117;
    height: 10px;
    margin: 0px 2px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: #263549;
    min-width: 28px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background: #3b4f6b;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    width: 0px;
}
"""

LIGHT_QSS = """
QMainWindow, QDialog { background-color: #f4f6fa; color: #0f172a; font-family: 'Segoe UI'; font-size: 12px; }
QWidget { color: #0f172a; font-family: 'Segoe UI'; font-size: 12px; }

QTabWidget::pane {
    border: 1px solid #dbe2ec;
    border-radius: 8px;
    background-color: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #64748b;
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid transparent;
    font-weight: 500;
}
QTabBar::tab:hover {
    color: #0f172a;
    background: #e9eef6;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #0f172a;
    border: 1px solid #dbe2ec;
    border-bottom: 2px solid #2563eb;
    font-weight: 600;
}

QPushButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px 12px;
    color: #1e293b;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #2563eb;
}
QPushButton:disabled {
    color: #94a3b8;
    background-color: #f8fafc;
    border-color: #e2e8f0;
}
QPushButton#primaryBtn {
    background-color: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primaryBtn:hover {
    background-color: #1d4ed8;
}
QPushButton#successBtn {
    background-color: #059669;
    border-color: #059669;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#successBtn:hover {
    background-color: #047857;
}
QPushButton#warnBtn {
    background-color: #ea580c;
    border-color: #ea580c;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#runtimeStartBtn {
    background-color: #059669;
    border: 1px solid #047857;
    color: #ffffff;
    font-weight: 600;
    padding: 5px 14px;
}
QPushButton#runtimeStartBtn:hover {
    background-color: #047857;
}
QPushButton#runtimeStartBtn:disabled {
    background-color: #d1fae5;
    border: 1px solid #6ee7b7;
    color: #047857;
}
QPushButton#runtimeStopBtn {
    background-color: #d97706;
    border: 1px solid #b45309;
    color: #ffffff;
    font-weight: 600;
    padding: 5px 14px;
}
QPushButton#runtimeStopBtn:hover {
    background-color: #b45309;
}
QPushButton#runtimeStopBtn:disabled {
    background-color: #fef3c7;
    border: 1px solid #fcd34d;
    color: #92400e;
}
QPushButton#ghostBtn {
    background-color: transparent;
    border: 1px solid transparent;
    color: #475569;
    padding: 4px 8px;
}
QPushButton#ghostBtn:hover {
    background-color: #e2e8f0;
    color: #0f172a;
}
QPushButton#iconBtn {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px;
}
QPushButton#iconBtn:hover {
    background-color: #e2e8f0;
    border-color: #cbd5e1;
}
QPushButton#updatePillBtn {
    background-color: #fef3c7;
    border: 1px solid #d97706;
    border-radius: 4px;
    color: #92400e;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 700;
}
QPushButton#updatePillBtn:hover {
    background-color: #fde68a;
}
QPushButton#tokenSummaryBtn {
    background-color: #ecfdf5;
    border: 1px solid #6ee7b7;
    border-radius: 6px;
    color: #047857;
    padding: 3px 10px;
    font-family: Consolas, 'Segoe UI', monospace;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#tokenSummaryBtn:hover {
    background-color: #d1fae5;
    border-color: #059669;
    color: #065f46;
}
QPushButton#newProfileBtn {
    background-color: #eff6ff;
    border: 1px solid #3b82f6;
    color: #1d4ed8;
    font-weight: 600;
    padding: 5px 11px;
}
QPushButton#newProfileBtn:hover {
    background-color: #dbeafe;
    border-color: #2563eb;
    color: #1e3a8a;
}
QPushButton#tagBenefitBtn, QLabel#tagBenefitPill {
    background-color: #ecfdf5;
    border: 1px solid #6ee7b7;
    border-radius: 3px;
    color: #047857;
    padding: 0px 6px;
    font-size: 10px;
    font-weight: 600;
}
QPushButton#tagBenefitBtn:hover {
    background-color: #d1fae5;
    border-color: #059669;
}
QPushButton#tagDomainBtn, QLabel#tagDomainPill {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 3px;
    color: #475569;
    padding: 0px 6px;
    font-size: 10px;
    font-weight: 500;
}
QPushButton#tagDomainBtn:hover {
    background-color: #e2e8f0;
    border-color: #3b82f6;
    color: #0f172a;
}
QPushButton#wizBenefitChip {
    background-color: #ecfdf5;
    border: 1px solid #6ee7b7;
    border-radius: 6px;
    color: #047857;
    padding: 5px 15px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#wizBenefitChip:hover {
    background-color: #d1fae5;
}
QPushButton#wizBenefitChip:checked {
    background-color: #059669;
    border: 1px solid #047857;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#wizDomainChip {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    color: #334155;
    padding: 5px 9px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton#wizDomainChip:hover {
    background-color: #f1f5f9;
    border-color: #3b82f6;
}
QPushButton#wizDomainChip:checked {
    background-color: #2563eb;
    border: 1px solid #1d4ed8;
    color: #ffffff;
    font-weight: 700;
}

QLineEdit, QComboBox, QPlainTextEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px 9px;
    color: #0f172a;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
    border-color: #2563eb;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border: none;
}
QComboBox::down-arrow {
    image: url(__CHEVRON_DARK__);
    width: 12px;
    height: 12px;
    margin-right: 4px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
    color: #0f172a;
    outline: none;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 20px 6px 12px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #dbeafe;
    color: #0f172a;
}
QMenu::separator {
    height: 1px;
    background: #e2e8f0;
    margin: 4px 6px;
}

QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    gridline-color: #e8edf5;
    border: 1px solid #dbe2ec;
    border-radius: 8px;
}
QWidget#cellBox { background: transparent; }
QScrollArea { background: transparent; border: none; }
QHeaderView::section {
    background-color: #f1f5f9;
    color: #475569;
    padding: 7px 10px;
    border: none;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #dbe2ec;
    font-weight: 600;
    font-size: 11px;
}
QHeaderView::section:hover {
    background-color: #e2e8f0;
    color: #0f172a;
}

QFrame#card {
    background-color: #f8fafc;
    border: 1px solid #dbe2ec;
    border-radius: 8px;
}
QFrame#bannerWarn {
    background-color: #fffbeb;
    border: 1px solid #f59e0b;
    border-radius: 8px;
}
QFrame#bannerInfo {
    background-color: #eff6ff;
    border: 1px solid #3b82f6;
    border-radius: 8px;
}

QProgressBar {
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    background: #f1f5f9;
    text-align: center;
    color: #1e293b;
    font-size: 11px;
    min-height: 18px;
}
QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 4px;
}
QProgressBar#slimBar {
    min-height: 7px;
    max-height: 7px;
    border-radius: 4px;
}
QListWidget {
    background-color: #ffffff;
    border: 1px solid #dbe2ec;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    padding: 7px 10px;
    border-radius: 5px;
}
QListWidget::item:selected {
    background-color: #dbeafe;
    color: #0f172a;
}

QCheckBox {
    spacing: 7px;
}

QScrollBar:vertical {
    background: #f1f5f9;
    width: 10px;
    margin: 2px 0px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 28px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0px;
}
QScrollBar:horizontal {
    background: #f1f5f9;
    height: 10px;
    margin: 0px 2px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1;
    min-width: 28px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background: #94a3b8;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    width: 0px;
}
"""


def _resolve_asset_url(filename: str) -> str:
    candidates: list[pathlib.Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(pathlib.Path(meipass) / "assets" / filename)
        candidates.append(pathlib.Path(sys.executable).resolve().parent / "assets" / filename)
    candidates.append(pathlib.Path(__file__).resolve().parent.parent.parent / "assets" / filename)
    for c in candidates:
        if c.is_file():
            return c.as_posix()
    return ""


def get_stylesheet(mode: str) -> str:
    is_light = mode == "light"
    qss = LIGHT_QSS if is_light else DARK_QSS
    url = _resolve_asset_url("chevron_light.png" if is_light else "chevron_dark.png")
    return qss.replace("__CHEVRON_DARK__", url).replace("__CHEVRON_LIGHT__", url)


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


# 18 distinct signature colors: tag_id -> (accent_dark, text_dark, accent_light, text_light)
TAG_COLOR_ANCHORS: dict[str, tuple[str, str, str, str]] = {
    "token_saver": ("#10b981", "#6ee7b7", "#059669", "#065f46"),      # Emerald
    "free_local": ("#14b8a6", "#5eead4", "#0d9488", "#115e59"),       # Seafoam Teal
    "coding_lsp": ("#3b82f6", "#93c5fd", "#2563eb", "#1e40af"),       # Electric Blue
    "desktop_ui": ("#38bdf8", "#bae6fd", "#0284c7", "#075985"),       # Cerulean Sky
    "git_repo": ("#f97316", "#fdba74", "#ea580c", "#9a3412"),         # Git Orange
    "unity": ("#06b6d4", "#67e8f9", "#0891b2", "#155e75"),            # Cyan-Turquoise
    "modeling_3d": ("#f59e0b", "#fde68a", "#d97706", "#92400e"),      # Blender Amber
    "style_3d": ("#ec4899", "#f9a8d4", "#db2777", "#9d174d"),         # Magenta-Rose
    "shader_gpu": ("#a855f7", "#d8b4fe", "#9333ea", "#6b21a8"),       # Electric Violet
    "audio_sfx": ("#f43f5e", "#fda4af", "#e11d48", "#9f1239"),        # Coral Crimson
    "web_browser": ("#0ea5e9", "#7dd3fc", "#0369a1", "#0c4a6e"),      # Ocean Azure
    "database": ("#6366f1", "#a5b4fc", "#4f46e5", "#3730a3"),         # Deep Indigo
    "cloud_devops": ("#22d3ee", "#a5f3fc", "#0e7490", "#164e63"),     # Cloud Cyan
    "docs_search": ("#eab308", "#fef08a", "#ca8a04", "#854d0e"),      # Warm Gold
    "design_ui": ("#d946ef", "#f0abfc", "#c026d3", "#86198f"),        # Orchid Fuchsia
    "security": ("#ef4444", "#fca5a5", "#dc2626", "#991b1b"),         # Scarlet Red
    "testing_qa": ("#84cc16", "#bef264", "#65a30d", "#3f6212"),       # Vivid Lime
    "automation": ("#8b5cf6", "#c4b5fd", "#7c3aed", "#5b21b6"),       # Amethyst Purple
}


def _mix_hex(base_hex: str, tint_hex: str, ratio: float) -> str:
    b = base_hex.lstrip("#")
    t = tint_hex.lstrip("#")
    br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
    tr_c, tg_c, tb_c = int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
    r = max(0, min(255, round(br + (tr_c - br) * ratio)))
    g = max(0, min(255, round(bg + (tg_c - bg) * ratio)))
    bl = max(0, min(255, round(bb + (tb_c - bb) * ratio)))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _tag_visual_tokens(tag_id: str, is_primary: bool, is_light: bool) -> tuple[str, str, str, str, str, int]:
    acc_d, txt_d, acc_l, txt_l = TAG_COLOR_ANCHORS.get(
        tag_id, ("#3b82f6", "#93c5fd", "#2563eb", "#1e40af")
    )
    if is_light:
        if is_primary:
            bg = _mix_hex("#ffffff", acc_l, 0.16)
            border = acc_l
            fg = txt_l
            hover_bg = _mix_hex("#ffffff", acc_l, 0.25)
            hover_border = txt_l
            weight = 700
        else:
            bg = _mix_hex("#f8fafc", acc_l, 0.05)
            border = _mix_hex("#cbd5e1", acc_l, 0.30)
            fg = _mix_hex("#64748b", txt_l, 0.48)
            hover_bg = _mix_hex("#f1f5f9", acc_l, 0.13)
            hover_border = _mix_hex("#94a3b8", acc_l, 0.60)
            weight = 500
    else:
        if is_primary:
            bg = _mix_hex("#0b1017", acc_d, 0.27)
            border = acc_d
            fg = txt_d
            hover_bg = _mix_hex("#0b1017", acc_d, 0.38)
            hover_border = txt_d
            weight = 700
        else:
            bg = _mix_hex("#101722", acc_d, 0.06)
            border = _mix_hex("#1e293b", acc_d, 0.28)
            fg = _mix_hex("#7c8ca1", txt_d, 0.44)
            hover_bg = _mix_hex("#141e2d", acc_d, 0.16)
            hover_border = _mix_hex("#334155", acc_d, 0.65)
            weight = 500
    return bg, border, fg, hover_bg, hover_border, weight


def tag_button_qss(tag_id: str, is_primary: bool, is_light: bool) -> str:
    """Return clickable QPushButton QSS where every tag has its own hue, but only primary (1st) tags shine."""
    bg, border, fg, h_bg, h_border, weight = _tag_visual_tokens(tag_id, is_primary, is_light)
    return (
        f"QPushButton {{ background-color: {bg}; border: 1px solid {border}; border-radius: 3px; "
        f"color: {fg}; padding: 0px 6px; font-size: 10px; font-weight: {weight}; }}"
        f"QPushButton:hover {{ background-color: {h_bg}; border-color: {h_border}; }}"
    )


def tag_pill_qss(tag_id: str, is_primary: bool, is_light: bool) -> str:
    """Return non-clickable QLabel QSS matching tag_button_qss (primary glows, secondary stays muted)."""
    bg, border, fg, _h_bg, _h_border, weight = _tag_visual_tokens(tag_id, is_primary, is_light)
    return (
        f"background-color: {bg}; border: 1px solid {border}; border-radius: 3px; "
        f"color: {fg}; padding: 0px 6px; font-size: 10px; font-weight: {weight};"
    )


def wizard_chip_qss(tag_id: str, is_light: bool, is_benefit: bool = False) -> str:
    """Return checkable QPushButton QSS for ProfileWizardDialog tag chips with per-tag signature colors."""
    acc_d, txt_d, acc_l, txt_l = TAG_COLOR_ANCHORS.get(
        tag_id, ("#3b82f6", "#93c5fd", "#2563eb", "#1e40af")
    )
    pad = "5px 14px" if is_benefit else "5px 9px"
    if is_light:
        idle_bg = _mix_hex("#ffffff", acc_l, 0.06)
        idle_bd = _mix_hex("#cbd5e1", acc_l, 0.36)
        idle_fg = _mix_hex("#334155", txt_l, 0.55)
        hov_bg = _mix_hex("#f8fafc", acc_l, 0.14)
        chk_bg = _mix_hex("#ffffff", acc_l, 0.20)
        chk_bd = acc_l
        chk_fg = txt_l
    else:
        idle_bg = _mix_hex("#111824", acc_d, 0.08)
        idle_bd = _mix_hex("#223044", acc_d, 0.35)
        idle_fg = _mix_hex("#94a3b8", txt_d, 0.50)
        hov_bg = _mix_hex("#141e2d", acc_d, 0.18)
        chk_bg = _mix_hex("#0b1017", acc_d, 0.32)
        chk_bd = acc_d
        chk_fg = txt_d
    return (
        f"QPushButton {{ background-color: {idle_bg}; border: 1px solid {idle_bd}; border-radius: 6px; "
        f"color: {idle_fg}; padding: {pad}; font-size: 11px; font-weight: 600; }}"
        f"QPushButton:hover {{ background-color: {hov_bg}; border-color: {chk_bd}; }}"
        f"QPushButton:checked {{ background-color: {chk_bg}; border: 1px solid {chk_bd}; "
        f"color: {chk_fg}; font-weight: 700; }}"
    )
