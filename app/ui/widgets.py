"""Custom reusable PySide6 table and header widgets."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QWidget,
)

from ..catalog import AI_CLIENTS

if TYPE_CHECKING:
    from .main_window import MainWindow


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
        bg_col = QColor("#dbeafe") if is_light else QColor("#1e324d")
        border_col = QColor("#3b82f6")
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
            painter.drawText(option.rect.adjusted(3, 0, -3, 0), flags, str(text))

        pen = QPen(border_col, 1)
        painter.setPen(pen)
        painter.drawLine(option.rect.left(), option.rect.top(), option.rect.right(), option.rect.top())
        painter.drawLine(option.rect.left(), option.rect.bottom(), option.rect.right(), option.rect.bottom())

        if index.column() == 0:
            painter.fillRect(option.rect.left(), option.rect.top(), 3, option.rect.height(), border_col)
        painter.restore()


class HoverTableWidget(QTableWidget):
    """QTableWidget supporting smooth full-row hover tracking even over cell widgets."""

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
    """Table header hosting the master selection checkbox and bulk [AGY][CDX][CLD][CUR] client buttons."""

    AI_COL = 5
    AI_COL_WIDTH = 161

    def __init__(self, parent_table: QTableWidget, main_win: "MainWindow") -> None:
        super().__init__(Qt.Orientation.Horizontal, parent_table)
        self.main_win = main_win
        self.setSectionsClickable(True)
        self.setMinimumHeight(34)

        self.master_cb = QCheckBox(self.viewport())
        self.master_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.master_cb.setToolTip("Tüm araçları seç / seçimi kaldır (durum kopyalama için)")
        self.master_cb.clicked.connect(lambda checked: self.main_win._set_panel_checks("all" if checked else "none"))

        self.ai_bar = QWidget(self.viewport())
        self.ai_bar.setStyleSheet("background: transparent; border: none;")
        bar_lay = QHBoxLayout(self.ai_bar)
        bar_lay.setContentsMargins(4, 2, 4, 2)
        bar_lay.setSpacing(3)

        self.buttons: dict[str, QPushButton] = {}
        for code, full_lbl in AI_CLIENTS:
            b_btn = QPushButton(code, self.ai_bar)
            b_btn.setFixedWidth(36)
            b_btn.setFixedHeight(22)
            b_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            b_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b_btn.setToolTip(
                f"{full_lbl} — Sol tık: Tüm sütunu tek tıkla komple AÇ / KAPAT\n"
                "Sağ tık: Gelişmiş toplu seçim menüsü"
            )
            b_btn.clicked.connect(lambda _=False, c=code: self.main_win._toggle_client_all(c, mode="auto"))
            b_btn.customContextMenuRequested.connect(
                lambda pos, c=code, btn=b_btn: self.main_win._show_bulk_client_menu(c, btn, pos)
            )
            self.buttons[code] = b_btn
            bar_lay.addWidget(b_btn)

        self.sectionResized.connect(lambda *_: self.sync_ai_bar_geometry())
        self.sectionMoved.connect(lambda *_: self.sync_ai_bar_geometry())
        self.geometriesChanged.connect(self.sync_ai_bar_geometry)

    def sync_ai_bar_geometry(self) -> None:
        vh = self.viewport().height() or self.height()
        if self.count() > 0 and not self.isSectionHidden(0):
            x0 = self.sectionViewportPosition(0)
            self.master_cb.setGeometry(x0 + 10, max(4, (vh - 18) // 2), 20, 18)
            self.master_cb.show()
            self.master_cb.raise_()
        else:
            self.master_cb.hide()

        if self.count() <= self.AI_COL or self.isSectionHidden(self.AI_COL):
            self.ai_bar.hide()
            return
        x = self.sectionViewportPosition(self.AI_COL)
        w = self.sectionSize(self.AI_COL)
        self.ai_bar.setGeometry(x, 0, w, max(24, vh - 1))
        self.ai_bar.show()
        self.ai_bar.raise_()

    def updateGeometries(self) -> None:
        super().updateGeometries()
        self.sync_ai_bar_geometry()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.sync_ai_bar_geometry()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.sync_ai_bar_geometry()


def create_option_help_badge(tooltip_text: str, on_click: Any, size: int = 20) -> QPushButton:
    btn = QPushButton("?")
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background-color: #172554; color: #93c5fd; border: 1px solid #3b82f6; "
        f"border-radius: {size // 2}px; font-size: 11px; font-weight: 800; padding: 0px; }}"
        "QPushButton:hover { background-color: #2563eb; color: #ffffff; }"
    )
    btn.setToolTip(tooltip_text)
    btn.clicked.connect(lambda _=False: on_click())
    return btn
