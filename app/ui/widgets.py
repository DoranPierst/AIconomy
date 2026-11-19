"""Custom minimalist PySide6 widgets: ToggleSwitch, StatusBadge, HoverTableWidget, AiMatrixHeaderView."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QWidget,
)

from ..catalog import AI_CLIENTS
from .icons import make_status_dot_pixmap

if TYPE_CHECKING:
    from .main_window import MainWindow


class ToggleSwitch(QAbstractButton):
    """Minimalist pill toggle switch replacing verbose ON/OFF pushbuttons."""

    def __init__(self, checked: bool = False, is_light: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self._is_light = is_light
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 22)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(38, 22)

    def enterEvent(self, event: Any) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        r = h / 2.0

        if self.isChecked():
            track_col = QColor("#3b82f6" if self._hovered else "#2563eb")
            border_col = QColor("#60a5fa" if self._hovered else "#2563eb")
        else:
            if self._is_light:
                track_col = QColor("#cbd5e1" if self._hovered else "#dbe2ec")
                border_col = QColor("#94a3b8" if self._hovered else "#cbd5e1")
            else:
                track_col = QColor("#334155" if self._hovered else "#223044")
                border_col = QColor("#475569" if self._hovered else "#2e3f57")

        p.setPen(QPen(border_col, 1.0))
        p.setBrush(track_col)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), r, r)

        knob_d = h - 6.0
        knob_x = (w - knob_d - 3.0) if self.isChecked() else 3.0
        knob_y = 3.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff" if self.isChecked() or self._is_light else "#cbd5e1"))
        p.drawEllipse(QRectF(knob_x, knob_y, knob_d, knob_d))
        p.end()


STATUS_DOT_COLORS: dict[str, str] = {
    "ok": "#22c55e",
    "warn": "#f59e0b",
    "error": "#ef4444",
    "idle": "#60a5fa",
    "off": "#64748b",
}


class StatusBadgeWidget(QWidget):
    """Colored anti-aliased status dot + concise single-line label."""

    def __init__(self, state: str, text: str, tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cellBox")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)

        dot_col = STATUS_DOT_COLORS.get(state, "#64748b")
        dot = QLabel()
        dot.setPixmap(make_status_dot_pixmap(dot_col, 8))
        dot.setFixedSize(8, 8)
        lay.addWidget(dot)

        lbl = QLabel(text)
        if state == "off":
            lbl.setStyleSheet("color: #64748b;")
        elif state == "error":
            lbl.setStyleSheet("color: #f87171;")
        elif state == "warn":
            lbl.setStyleSheet("color: #fbbf24;")
        lay.addWidget(lbl)
        lay.addStretch()
        if tooltip:
            self.setToolTip(tooltip)


class FullRowHoverDelegate(QStyledItemDelegate):
    """Highlight an entire table row across text and embedded cell widgets on hover."""

    def __init__(self, table: "HoverTableWidget", main_win: "MainWindow") -> None:
        super().__init__(table)
        self.table = table
        self.main_win = main_win

    def paint(self, painter: QPainter, option: Any, index: Any) -> None:
        if index.row() != self.table.hover_row:
            super().paint(painter, option, index)
            return

        is_light = self.main_win.meta.get("theme", "dark") == "light"
        bg_col = QColor("#e8f1fd") if is_light else QColor("#18273c")
        accent_col = QColor("#3b82f6")
        txt_col = QColor("#0f172a") if is_light else QColor("#f8fafc")

        painter.save()
        painter.fillRect(option.rect, bg_col)

        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            align = index.data(Qt.ItemDataRole.TextAlignmentRole)
            flags = int(align) if align is not None else int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            fg_brush = index.data(Qt.ItemDataRole.ForegroundRole)
            pen_col = fg_brush.color() if hasattr(fg_brush, "color") else txt_col
            painter.setPen(pen_col)
            painter.setFont(QFont(option.font))
            painter.drawText(option.rect.adjusted(6, 0, -6, 0), flags, str(text))

        if index.column() == 0:
            painter.fillRect(option.rect.left(), option.rect.top(), 2, option.rect.height(), accent_col)
        painter.restore()


class HoverTableWidget(QTableWidget):
    """QTableWidget supporting smooth full-row hover tracking even over embedded cell widgets."""

    def __init__(self, rows: int, cols: int, main_win: "MainWindow") -> None:
        super().__init__(rows, cols)
        self.main_win = main_win
        self.hover_row: int = -1
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setItemDelegate(FullRowHoverDelegate(self, main_win))
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def detach_filter(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def set_hover_row(self, row: int) -> None:
        if row != self.hover_row:
            self.hover_row = row
            self.viewport().update()

    def _refresh_hover_from_cursor(self) -> None:
        if not self.isVisible():
            if self.hover_row != -1:
                self.set_hover_row(-1)
            return
        if QApplication.activePopupWidget() is not None:
            return
        vp = self.viewport()
        local_pos = vp.mapFromGlobal(QCursor.pos())
        if vp.rect().contains(local_pos):
            self.set_hover_row(self.rowAt(local_pos.y()))
        else:
            self.set_hover_row(-1)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove, QEvent.Type.Leave, QEvent.Type.Wheel):
            self._refresh_hover_from_cursor()
        return False

    def leaveEvent(self, event: Any) -> None:  # noqa: N802
        self.set_hover_row(-1)
        super().leaveEvent(event)


class AiMatrixHeaderView(QHeaderView):
    """Table header embedding bulk [AGY][CDX][CLD][CUR] client buttons in the AI Clients column."""

    AI_COL = 3
    AI_COL_WIDTH = 168

    def __init__(self, parent_table: QTableWidget, main_win: "MainWindow") -> None:
        super().__init__(Qt.Orientation.Horizontal, parent_table)
        self.main_win = main_win
        self.setSectionsClickable(True)
        self.setMinimumHeight(34)

        self.ai_bar = QWidget(self.viewport())
        self.ai_bar.setStyleSheet("background: transparent; border: none;")
        bar_lay = QHBoxLayout(self.ai_bar)
        bar_lay.setContentsMargins(6, 2, 6, 2)
        bar_lay.setSpacing(4)

        self.buttons: dict[str, QPushButton] = {}
        for code, _full_lbl in AI_CLIENTS:
            b_btn = QPushButton(code, self.ai_bar)
            b_btn.setFixedWidth(36)
            b_btn.setFixedHeight(22)
            b_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            b_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b_btn.clicked.connect(lambda _=False, c=code: self.main_win._toggle_client_all(c, mode="auto"))
            b_btn.customContextMenuRequested.connect(
                lambda pos, c=code, btn=b_btn: self.main_win._show_bulk_client_menu(c, btn, pos)
            )
            self.buttons[code] = b_btn
            bar_lay.addWidget(b_btn)

        self.sectionResized.connect(lambda *_: self.sync_ai_bar_geometry())
        self.sectionMoved.connect(lambda *_: self.sync_ai_bar_geometry())
        self.geometriesChanged.connect(self.sync_ai_bar_geometry)

    def refresh_visible_clients(self, visible_codes: list[str]) -> int:
        vis_set = set(visible_codes)
        shown = 0
        for code, _lbl in AI_CLIENTS:
            btn = self.buttons.get(code)
            if btn is not None:
                is_vis = code in vis_set
                btn.setVisible(is_vis)
                if is_vis:
                    shown += 1
        col_w = max(60, shown * 40 + 8)
        self.AI_COL_WIDTH = col_w
        self.sync_ai_bar_geometry()
        return col_w

    def sync_ai_bar_geometry(self) -> None:
        vh = self.viewport().height() or self.height()
        if self.count() <= self.AI_COL or self.isSectionHidden(self.AI_COL):
            self.ai_bar.hide()
            return
        x = self.sectionViewportPosition(self.AI_COL)
        w = self.sectionSize(self.AI_COL)
        self.ai_bar.setGeometry(x, 0, w, max(24, vh - 1))
        self.ai_bar.show()
        self.ai_bar.raise_()

    def updateGeometries(self) -> None:  # noqa: N802
        super().updateGeometries()
        self.sync_ai_bar_geometry()

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.sync_ai_bar_geometry()

    def showEvent(self, event: Any) -> None:  # noqa: N802
        super().showEvent(event)
        self.sync_ai_bar_geometry()


def create_option_help_badge(tooltip_text: str, on_click: Any, size: int = 18) -> QPushButton:
    btn = QPushButton("i")
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background-color: transparent; color: #60a5fa; border: 1px solid #334155; "
        f"border-radius: {size // 2}px; font-size: 10px; font-weight: 700; padding: 0px; }}"
        "QPushButton:hover { background-color: #2563eb; color: #ffffff; border-color: #2563eb; }"
    )
    btn.setToolTip(tooltip_text)
    btn.clicked.connect(lambda _=False: on_click())
    return btn
