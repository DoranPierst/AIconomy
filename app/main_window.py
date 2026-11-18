"""PySide6 (Qt 6) Yerel Masaüstü Arayüzü: Proje/Konum Sütunu, 94-Skill Çark Yöneticisi, Çift Yönlü AI Danışman ve Sistem Tepsisi."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import threading
import time
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStyledItemDelegate,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .ai_advisor import (
    build_logs_ai_prompt,
    build_skills_ai_prompt,
    build_tool_ai_prompt,
    parse_skills_ai_response,
    parse_tool_ai_response,
)
from .catalog import (
    AI_CLIENTS,
    BLENDER_SKILLS_94,
    PROFILES,
    ToolSpec,
    build_default_catalog,
    describe_blender_skill,
)
from .i18n import SUPPORTED_LANGUAGES, detect_default_language, tr
from .storage import LogDatabase, StateStore, WindowsDpapiVault
from .system_ops import (
    check_all_tools_updates_parallel,
    detect_running_dcc_apps,
    enforce_tool_runtime_state,
    free_trellis_vram,
    get_missing_host_dependencies,
    inspect_github_repo,
    kill_zombie_port_process,
    launch_host_app_for_tool,
    probe_tool_health,
    query_gpu_vram,
    resolve_disk_location,
    scan_live_process_locations,
    sync_blender_skills_on_disk,
    sync_mcp_json_clients,
    test_tool_connection_e2e,
    update_single_tool,
)
from .updater import (
    UpdateCheckResult,
    apply_self_update,
    check_for_app_updates,
    get_current_app_version,
    resolve_effective_app_repo,
    restart_running_python_app,
    stamp_repo_into_version_json,
)

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
    candidates.append(pathlib.Path(__file__).resolve().parent.parent / "assets" / "aiconomy.png")
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


class WorkerBridge(QObject):
    health_done = Signal(object, bool)
    repo_done = Signal(object)
    plugin_check_done = Signal(int, bool)
    update_progress = Signal(int, int, str)
    update_all_done = Signal(int, int, str)
    app_check_done = Signal(object)
    conn_test_row = Signal(int, bool, int, str, str)
    conn_test_done = Signal()
    app_dl_progress = Signal(int, int)
    app_apply_done = Signal(bool, str, str)


class FullRowHoverDelegate(QStyledItemDelegate):
    """Fare hangi satırın üzerindeyse (buton ve açılır kutular dahil) satırı soldan sağa komple aydınlatır."""

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
    """İçindeki tüm hücre bileşenleri üzerinde bile tam satır (full-row) hover takibi yapan tablo."""

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
    """Sütun 0'a toplu seçim kutusu ve Sütun 5 başlığının tam içine [AGY] [CDX] [CLD] [CUR] toplu kontrol butonları yerleştirir."""

    AI_COL = 5
    AI_COL_WIDTH = 161  # 4px sol + 4x36px buton + 3x3px boşluk + 4px sağ = 161px

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


class ToolInfoDialog(QDialog):
    """Eklentinin ne işe yaradığını, ne zaman açılıp kapatılacağını ve teknik gereksinimlerini anlatan bilgi kartı."""

    def __init__(self, parent: "MainWindow", tool: ToolSpec) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.tool = tool
        self.setWindowTitle(f"❓ {tool.name} — Ne İşe Yarar?")
        self.setMinimumWidth(620)
        self.resize(640, 500)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        hdr_row = QHBoxLayout()
        title_lbl = QLabel(f"<span style='font-size:15px; font-weight:700;'>{tool.name}</span>")
        hdr_row.addWidget(title_lbl)
        badge_lbl = QLabel(f"  <span style='color:#60a5fa; font-weight:600;'>[{tool.kind} · {tool.version}]</span>")
        hdr_row.addWidget(badge_lbl)
        hdr_row.addStretch()
        lay.addLayout(hdr_row)

        # 1) Ne İşe Yarar?
        what_card = QFrame()
        what_card.setObjectName("card")
        w_lay = QVBoxLayout(what_card)
        w_lay.setSpacing(6)
        w_lay.addWidget(QLabel("<b>🎯 Ne İşe Yarar?</b>"))
        sum_txt = tool.summary or "Bu eklenti yapay zeka istemcinize ek araç ve yetenekler kazandırır."
        det_txt = tool.details or ""
        full_what = f"{sum_txt}\n\n{det_txt}".strip() if det_txt else sum_txt
        what_lbl = QLabel(full_what)
        what_lbl.setWordWrap(True)
        w_lay.addWidget(what_lbl)
        lay.addWidget(what_card)

        # 2) Ne Zaman Açmalı / Kapatmalı?
        when_card = QFrame()
        when_card.setObjectName("card")
        wh_lay = QVBoxLayout(when_card)
        wh_lay.addWidget(QLabel("<b>💡 Ne Zaman Açmalı / Ne Zaman Kapatmalı?</b>"))
        when_lbl = QLabel(
            tool.when_to_use
            or "İlgili projede aktif olarak ihtiyacınız olduğunda AÇIN; kullanmadığınız zamanlarda gereksiz şema tokenı harcamaması için KAPATIN."
        )
        when_lbl.setWordWrap(True)
        wh_lay.addWidget(when_lbl)
        lay.addWidget(when_card)

        # 3) Teknik Özet & Bağlantı
        tech_card = QFrame()
        tech_card.setObjectName("card")
        t_lay = QVBoxLayout(tech_card)
        t_lay.addWidget(QLabel("<b>📊 Teknik & Kaynak Özeti</b>"))

        if tool.id == "blender_skills":
            tok_info = "Seçilen her skill ~350 token (94 skill tamamı açılırsa ~33,000 token)"
        else:
            tok_info = f"~{tool.schema_tokens:,} şema tokenı (Kapalıyken 0 token)"

        key_info = (
            f"🔐 <b>{tool.vault_key_name}</b> gerekir (Şifreli Kasa sekmesinden girilir)"
            if tool.vault_key_name
            else "✓ Ücretsiz / API Anahtarı Gerekmez"
        )
        t_lay.addWidget(QLabel(f"• <b>Bağlam Yükü:</b> {tok_info}"))
        t_lay.addWidget(QLabel(f"• <b>Anahtar İhtiyacı:</b> {key_info}"))
        if tool.install_cmd:
            t_lay.addWidget(QLabel(f"• <b>Kurulum / Çalıştırma:</b> <code>{tool.install_cmd}</code>"))
        if tool.repo_url:
            link_lbl = QLabel(f"• <b>Resmi Kaynak:</b> <a style='color:#60a5fa;' href='{tool.repo_url}'>{tool.repo_url} ↗</a>")
            link_lbl.setOpenExternalLinks(True)
            t_lay.addWidget(link_lbl)
        lay.addWidget(tech_card)

        lay.addStretch()
        bot = QHBoxLayout()
        if tool.has_gear:
            btn_gear = QPushButton("⚙️ Bu Eklentinin Ayarlarını Aç")
            btn_gear.clicked.connect(lambda: (self.accept(), self.main_win.open_gear(tool)))
            bot.addWidget(btn_gear)
        bot.addStretch()
        btn_ok = QPushButton("Tamam")
        btn_ok.setObjectName("primaryBtn")
        btn_ok.clicked.connect(self.accept)
        bot.addWidget(btn_ok)
        lay.addLayout(bot)
        self.adjustSize()


class AppUpdateDialog(QDialog):
    """Paylaşılan Kullanıcılar ve Geliştirici İçin Tek Tık Program Güncelleme Merkezi."""

    def __init__(self, parent: "MainWindow", initial_result: UpdateCheckResult | None = None) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.last_check: UpdateCheckResult | None = initial_result
        cur_ver = get_current_app_version()
        self.setWindowTitle(f"🔄 Program Güncelleme Merkezi (Kullandığınız Sürüm: v{cur_ver})")
        self.resize(620, 380)

        lay = QVBoxLayout(self)

        cur_repo = resolve_effective_app_repo(str(parent.meta.get("app_update_repo", "")))

        top_bar = QHBoxLayout()
        self.status_badge = QLabel("🔍 Güncel sürüm kontrol ediliyor..." if cur_repo else "⚠️ Güncelleme kanalı henüz bağlanmadı")
        self.status_badge.setStyleSheet("font-weight: 700; font-size: 14px;")
        top_bar.addWidget(self.status_badge, stretch=1)

        self.notes_link_lbl = QLabel("")
        self.notes_link_lbl.setOpenExternalLinks(True)
        top_bar.addWidget(self.notes_link_lbl)

        self.btn_toggle_channel = QPushButton("⚙️ Kanal Ayarı")
        self.btn_toggle_channel.setToolTip("Güncellemelerin çekildiği GitHub depo adresini görüntüler veya değiştirir")
        self.btn_toggle_channel.clicked.connect(self._toggle_repo_card)
        top_bar.addWidget(self.btn_toggle_channel)
        lay.addLayout(top_bar)

        # Gelişmiş / Kanal Ayarı Kartı (Repo zaten gömülüyse sade görünüm için gizli başlar; yoksa açık gelir)
        self.repo_card = QFrame()
        self.repo_card.setObjectName("card")
        r_lay = QVBoxLayout(self.repo_card)
        r_lay.addWidget(
            QLabel(
                "<b>GitHub Güncelleme Kanalı</b> "
                "<span style='color:#94a3b8;'>(Kaydettiğinizde ürettiğiniz .exe içine gömülür; paylaştığınız kişiler adres girmeden günceller)</span>"
            )
        )
        row = QHBoxLayout()
        self.repo_inp = QLineEdit(cur_repo)
        self.repo_inp.setPlaceholderText("https://github.com/DoranPierst/AIconomy")
        row.addWidget(self.repo_inp, stretch=1)

        btn_save_repo = QPushButton("💾 Kanalı Kaydet && Kontrol Et")
        btn_save_repo.setObjectName("primaryBtn")
        btn_save_repo.clicked.connect(self.run_check)
        row.addWidget(btn_save_repo)
        r_lay.addLayout(row)
        if cur_repo:
            self.repo_card.hide()
        lay.addWidget(self.repo_card)

        self.info_box = QPlainTextEdit()
        self.info_box.setReadOnly(True)
        self.info_box.setPlaceholderText("Sürüm karşılaştırması ve güncelleme notları burada görünür...")
        lay.addWidget(self.info_box, stretch=1)

        self.dl_bar = QProgressBar()
        self.dl_bar.hide()
        lay.addWidget(self.dl_bar)

        bot = QHBoxLayout()
        self.btn_check = QPushButton("🔍 Şimdi Tekrar Kontrol Et")
        self.btn_check.clicked.connect(self.run_check)
        bot.addWidget(self.btn_check)

        bot.addStretch()
        btn_close = QPushButton("Kapat")
        btn_close.clicked.connect(self.reject)
        self.btn_apply = QPushButton("✓ Sürüm Güncel")
        self.btn_apply.setObjectName("successBtn")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.run_apply)
        bot.addWidget(btn_close)
        bot.addWidget(self.btn_apply)
        lay.addLayout(bot)

        parent.bridge.app_check_done.connect(self._on_checked)
        parent.bridge.app_dl_progress.connect(self._on_dl_prog)
        parent.bridge.app_apply_done.connect(self._on_applied)

        if initial_result is not None and initial_result.ok:
            self._render_result(initial_result)
        elif cur_repo:
            QTimer.singleShot(120, self.run_check)
        else:
            self.info_box.setPlainText(
                "Bu programı arkadaşlarınıza veya topluluğa gönderdiğinizde tek tıkla güncelleme alabilmeleri için:\n\n"
                "1) GitHub'da oluşturduğunuz açık kaynak (Public) repo linkini yukarıdaki kutuya yapıştırıp kaydedin.\n"
                "2) Siz yeni bir sürüm yayınladığınızda, programı paylaştığınız herkes üst bardaki '🔄 Program Güncelle' butonuna basarak (veya programı açtığında gelen bildirimle) tekrar indirme yapmadan otomatik güncellenir."
            )

    def _toggle_repo_card(self) -> None:
        self.repo_card.setVisible(not self.repo_card.isVisible())

    def run_check(self) -> None:
        repo = self.repo_inp.text().strip()
        if repo:
            self.main_win.meta["app_update_repo"] = repo
            stamp_repo_into_version_json(repo)
            self.main_win._save_state()
        else:
            repo = resolve_effective_app_repo(str(self.main_win.meta.get("app_update_repo", "")))
        self.btn_check.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.status_badge.setText("🔍 GitHub üzerinden son sürüm kontrol ediliyor...")
        self.status_badge.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 14px;")
        self.info_box.setPlainText("GitHub üzerinden son sürüm ve değişiklik notları kontrol ediliyor...")
        tok = self.main_win.vault.get_secret("GITHUB_TOKEN")

        def worker() -> None:
            res = check_for_app_updates(repo, tok)
            self.main_win.bridge.app_check_done.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_checked(self, res: UpdateCheckResult) -> None:
        if not res.ok and res.repo_url:
            self.main_win.logs.add("WARN", "Program Güncelleyici", f"Sürüm kontrol uyarısı: {res.message}", f"Repo: {res.repo_url}\nDetay: {res.message}")
            self.main_win._refresh_logs_tab()
        if not self.isVisible():
            return
        self.btn_check.setEnabled(True)
        self._render_result(res)

    def _render_result(self, res: UpdateCheckResult) -> None:
        self.last_check = res
        if res.repo_url and not self.repo_inp.text().strip():
            self.repo_inp.setText(res.repo_url)

        if not res.ok:
            self.status_badge.setText(f"⚠️ {res.message}")
            self.status_badge.setStyleSheet("color: #f59e0b; font-weight: 700; font-size: 13px;")
            self.notes_link_lbl.setText("")
            if not res.repo_url:
                self.repo_card.show()
        elif res.has_update:
            self.status_badge.setText(f"🔔 Güncelleme Mevcut:  {res.local_version}v > {res.remote_version}v")
            self.status_badge.setStyleSheet("color: #f59e0b; font-weight: 700; font-size: 14px;")
            if res.release_notes_url:
                self.notes_link_lbl.setText(f"<a style='color:#60a5fa;' href='{res.release_notes_url}'>📄 Güncelleme Notları ↗</a>")
        else:
            self.status_badge.setText(f"✓ Programınız güncel ({res.local_version}v)")
            self.status_badge.setStyleSheet("color: #22c55e; font-weight: 700; font-size: 14px;")
            if res.release_notes_url:
                self.notes_link_lbl.setText(f"<a style='color:#60a5fa;' href='{res.release_notes_url}'>📄 Sürüm Geçmişi ↗</a>")

        lines = [
            f"Sürüm Karşılaştırması: {res.local_version}v > {res.remote_version}v" if res.has_update else f"Mevcut Sürüm: {res.local_version}v (En güncel sürümdesiniz)",
        ]
        if res.repo_url:
            lines.append(f"Güncelleme Kanalı: {res.repo_url}")
        if res.release_notes_url:
            lines.append(f"Güncelleme Notları: {res.release_notes_url}")
        if res.exe_download_url:
            lines.append("Güncelleme Yöntemi: Doğrudan AIconomy.exe otomatik yenileme (ayarlarınız korunur)")
        elif res.can_git_pull:
            lines.append("Güncelleme Yöntemi: Git Kaynak Deposu (git pull)")
        if res.changelog:
            lines.extend(["", "--- Bu Sürümdeki Yenilikler ---", res.changelog])
        self.info_box.setPlainText("\n".join(lines))

        self.btn_apply.setEnabled(res.ok and res.has_update)
        if res.has_update:
            self.btn_apply.setText(f"⚡ Şimdi Güncelle ve Yeniden Başlat ({res.local_version}v > {res.remote_version}v)")
        else:
            self.btn_apply.setText("✓ Sürüm Güncel")

    def run_apply(self) -> None:
        if not self.last_check:
            return
        self.btn_apply.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.dl_bar.setMaximum(100)
        self.dl_bar.setValue(0)
        self.dl_bar.setFormat("Yeni sürüm GitHub'dan indiriliyor...")
        self.dl_bar.show()
        tok = self.main_win.vault.get_secret("GITHUB_TOKEN")
        chk = self.last_check

        def worker() -> None:
            ok, mode, msg = apply_self_update(
                chk,
                tok,
                progress_cb=lambda cur, tot: self.main_win.bridge.app_dl_progress.emit(cur, tot),
            )
            self.main_win.bridge.app_apply_done.emit(ok, mode, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_dl_prog(self, cur: int, tot: int) -> None:
        if not self.isVisible():
            return
        if tot > 0:
            pct = int((cur * 100) / tot)
            self.dl_bar.setValue(pct)
            self.dl_bar.setFormat(f"İndiriliyor: {cur / (1024 * 1024):.1f} / {tot / (1024 * 1024):.1f} MB (%{pct})")

    def _on_applied(self, ok: bool, mode: str, msg: str) -> None:
        if not ok:
            first_line = msg.splitlines()[0] if msg else "Güncelleme hatası"
            self.main_win.logs.add("ERR", "Program Güncelleyici", first_line, msg)
            self.main_win._refresh_logs_tab()
        else:
            self.main_win.logs.add("INFO", "Program Güncelleyici", "Program güncellemesi başarıyla uygulandı.", msg)
            self.main_win._refresh_logs_tab()
        if not self.isVisible():
            return
        self.btn_check.setEnabled(True)
        self.dl_bar.setValue(100 if ok else 0)
        if not ok:
            self.btn_apply.setEnabled(True)
            QMessageBox.warning(self, "Güncelleme Hatası", f"{msg.splitlines()[0]}\n\n(Tam teknik çıktı Debug & Log sekmesine kaydedildi.)")
            return
        if mode == "swap_exe":
            # _apply_update.bat arka planda yeni .exe'yi taşımak için mevcut sürecin kapanmasını bekler; bloklamadan hemen kapatıyoruz
            self.accept()
            self.main_win._quit_app()
            return
        if mode == "restart_py":
            self.accept()
            self.main_win._save_state()
            restart_running_python_app()
            return
        QMessageBox.information(self, "Güncelleme Tamamlandı", msg)


class AiPasteDialog(QDialog):
    """AI yanıtını panodan veya kutudan alıp <<<ACIK: ...>>> ayrıştırması yapan pencere."""

    def __init__(self, parent: QWidget, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 340)
        lay = QVBoxLayout(self)
        info = QLabel(
            "AI'dan aldığın cevabı aşağıya yapıştır (panoda varsa otomatik dolduruldu).\n"
            "Program cevabın sonundaki <<<ACIK: ...>>> satırını (veya metindeki isimleri) otomatik yakalar:"
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        self.editor = QPlainTextEdit()
        clip = QApplication.clipboard().text()
        if clip:
            self.editor.setPlainText(clip)
        lay.addWidget(self.editor)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("İptal")
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton("📥 Analiz Et && Seçime Uygula")
        apply_btn.setObjectName("primaryBtn")
        apply_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(apply_btn)
        lay.addLayout(btns)


def _create_option_help_badge(tooltip_text: str, on_click: Any, size: int = 20) -> QPushButton:
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


class BlenderSkillsDialog(QDialog):
    """⚙️ Blender Skills (arjun988) — 94 Skill Çoklu Seçim + (?) Skill Bilgi Rehberi + Çift Yönlü AI Danışma Penceresi."""

    def __init__(self, parent: QWidget, active_skills: set[str], checked_skills: set[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚙️ Blender Skills (arjun988) — 94 Skill Yöneticisi")
        self.resize(920, 660)
        self.draft_active: set[str] = set(active_skills)
        self.checked_items: set[str] = set(checked_skills or set())
        self.saved_result: set[str] | None = None
        self.saved_checked: set[str] = set()

        root = QVBoxLayout(self)

        top_bar = QHBoxLayout()
        self.btn_all_on = QPushButton("Hepsini Aç")
        self.btn_all_off = QPushButton("Hepsini Kapat")
        self.btn_sel_on = QPushButton("Seçileni Aç (0)")
        self.btn_sel_on.setObjectName("primaryBtn")
        self.btn_sel_off = QPushButton("Seçileni Kapat (0)")
        self.btn_clear_sel = QPushButton("Seçimi Temizle")

        self.btn_all_on.clicked.connect(self._enable_all)
        self.btn_all_off.clicked.connect(self._disable_all)
        self.btn_sel_on.clicked.connect(self._enable_selected)
        self.btn_sel_off.clicked.connect(self._disable_selected)
        self.btn_clear_sel.clicked.connect(self._clear_selection)

        for b in (self.btn_all_on, self.btn_all_off, self.btn_sel_on, self.btn_sel_off, self.btn_clear_sel):
            top_bar.addWidget(b)

        top_bar.addStretch()
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("94 skill içinde ara (örn: horror, unity, uv)...")
        self.search_inp.setFixedWidth(230)
        self.search_inp.textChanged.connect(self._rebuild_grid)

        self.filter_cmb = QComboBox()
        self.filter_cmb.addItems(["Tümü (94)", "Açık Olanlar", "Kapalı Olanlar", "Tikli / Seçililer"])
        self.filter_cmb.currentIndexChanged.connect(self._rebuild_grid)

        top_bar.addWidget(self.search_inp)
        top_bar.addWidget(self.filter_cmb)
        root.addLayout(top_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid_layout = QGridLayout(self.grid_host)
        self.grid_layout.setSpacing(6)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, stretch=1)

        # Canlı Skill Açıklama Kartı (? butonuna tıklanınca veya üzerine gelince ne işe yaradığını anlatır)
        self.skill_help_card = QFrame()
        self.skill_help_card.setObjectName("card")
        self.skill_help_card.setStyleSheet("QFrame#card { border: 1px solid #2563eb; background-color: #132038; }")
        sh_lay = QVBoxLayout(self.skill_help_card)
        sh_lay.setContentsMargins(10, 6, 10, 6)
        sh_lay.setSpacing(3)
        self.skill_help_title = QLabel("<b>ℹ️ Skill Rehberi:</b> <span style='color:#93c5fd;'>Herhangi bir skill'in yanındaki (?) ikonuna tıklayarak açtığınızda ne işe yaradığını görebilirsiniz.</span>")
        self.skill_help_body = QLabel(describe_blender_skill("blender-director"))
        self.skill_help_body.setWordWrap(True)
        self.skill_help_body.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        sh_lay.addWidget(self.skill_help_title)
        sh_lay.addWidget(self.skill_help_body)
        root.addWidget(self.skill_help_card)

        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setFixedHeight(105)
        self.prompt_preview.hide()
        root.addWidget(self.prompt_preview)

        bot = QHBoxLayout()
        self.summary_lbl = QLabel()
        bot.addWidget(self.summary_lbl)
        bot.addStretch()

        self.btn_ask_ai = QPushButton("🤖 AI'a Danış (Prompt Kopyala)")
        self.btn_paste_ai = QPushButton("📥 AI Yanıtını Yapıştır && Uygula")
        self.btn_cancel = QPushButton("Vazgeç")
        self.btn_save = QPushButton("💾 Kaydet")
        self.btn_save.setObjectName("successBtn")

        self.btn_ask_ai.clicked.connect(self._copy_ai_prompt)
        self.btn_paste_ai.clicked.connect(self._paste_ai_response)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._save_and_close)

        for b in (self.btn_ask_ai, self.btn_paste_ai, self.btn_cancel, self.btn_save):
            bot.addWidget(b)
        root.addLayout(bot)

        self._rebuild_grid()

    def _show_skill_help(self, skill_name: str) -> None:
        self.skill_help_title.setText(f"<b>ℹ️ {skill_name}</b> — Açarsan / Kapatırsan Ne Olur?")
        self.skill_help_body.setText(describe_blender_skill(skill_name))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Enter:
            sk_nm = watched.property("skill_name")
            if sk_nm:
                self._show_skill_help(str(sk_nm))
        return super().eventFilter(watched, event)

    def _rebuild_grid(self) -> None:
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        q = self.search_inp.text().strip().lower()
        f_idx = self.filter_cmb.currentIndex()

        filtered: list[str] = []
        for sk in BLENDER_SKILLS_94:
            if q and q not in sk:
                continue
            if f_idx == 1 and sk not in self.draft_active:
                continue
            if f_idx == 2 and sk in self.draft_active:
                continue
            if f_idx == 3 and sk not in self.checked_items:
                continue
            filtered.append(sk)

        cols = 3
        for idx, sk in enumerate(filtered):
            card = QFrame()
            card.setObjectName("card")
            row_lay = QHBoxLayout(card)
            row_lay.setContentsMargins(8, 4, 8, 4)
            row_lay.setSpacing(5)

            desc_txt = describe_blender_skill(sk)
            cb = QCheckBox(sk)
            cb.setChecked(sk in self.checked_items)
            cb.setToolTip(f"❓ {sk}\n{desc_txt}")
            cb.setProperty("skill_name", sk)
            cb.installEventFilter(self)
            cb.toggled.connect(lambda checked, name=sk: self._on_check_toggled(name, checked))
            row_lay.addWidget(cb, stretch=1)

            q_btn = _create_option_help_badge(
                f"❓ {sk}\n{desc_txt}",
                lambda name=sk: self._show_skill_help(name),
                size=18,
            )
            row_lay.addWidget(q_btn)

            is_on = sk in self.draft_active
            badge = QLabel("AÇIK" if is_on else "KAPALI")
            badge.setStyleSheet(
                "color: #22c55e; font-weight: 700; font-size: 11px;"
                if is_on
                else "color: #64748b; font-size: 11px;"
            )
            row_lay.addWidget(badge)
            self.grid_layout.addWidget(card, idx // cols, idx % cols)

        self.grid_layout.setRowStretch((len(filtered) // cols) + 1, 1)
        self._update_counters()

    def _on_check_toggled(self, name: str, checked: bool) -> None:
        if checked:
            self.checked_items.add(name)
        else:
            self.checked_items.discard(name)
        self._update_counters()

    def _update_counters(self) -> None:
        sel_n = len(self.checked_items)
        on_n = len(self.draft_active)
        off_n = len(BLENDER_SKILLS_94) - on_n
        saved_tok = round(off_n * 0.35, 1)
        self.btn_sel_on.setText(f"Seçileni Aç ({sel_n})")
        self.btn_sel_off.setText(f"Seçileni Kapat ({sel_n})")
        self.btn_sel_on.setEnabled(sel_n > 0)
        self.btn_sel_off.setEnabled(sel_n > 0)
        self.summary_lbl.setText(
            f"Açık: {on_n} / 94  ·  Kapalı: {off_n}  ·  Tikli: {sel_n}  ·  Tahmini Tasarruf: +{saved_tok}K tok"
        )

    def _enable_all(self) -> None:
        self.draft_active = set(BLENDER_SKILLS_94)
        self._rebuild_grid()

    def _disable_all(self) -> None:
        self.draft_active.clear()
        self._rebuild_grid()

    def _enable_selected(self) -> None:
        self.draft_active.update(self.checked_items)
        self._rebuild_grid()

    def _disable_selected(self) -> None:
        self.draft_active.difference_update(self.checked_items)
        self._rebuild_grid()

    def _clear_selection(self) -> None:
        self.checked_items.clear()
        self._rebuild_grid()

    def _copy_ai_prompt(self) -> None:
        prompt = build_skills_ai_prompt(self.draft_active, self.checked_items)
        QApplication.clipboard().setText(prompt)
        self.prompt_preview.setPlainText(prompt)
        self.prompt_preview.show()

    def _paste_ai_response(self) -> None:
        dlg = AiPasteDialog(self, "📥 AI Yanıtını Yapıştır & 94 Skill Seçimine Uygula")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            matched, msg = parse_skills_ai_response(dlg.editor.toPlainText())
            if matched or "tümü kapalı" in msg:
                self.draft_active = set(matched)
                self.checked_items = set(matched)
                self._rebuild_grid()
                QMessageBox.information(
                    self,
                    "AI Önerisi Uygulandı",
                    f"{msg}.\n\nŞu an {len(self.draft_active)} skill AÇIK olarak ayarlandı ve kontrol edebilmen için tiklendi.\nKalıcı olması için '💾 Kaydet' butonuna basabilirsin.",
                )
            else:
                QMessageBox.warning(self, "Eşleşme Bulunamadı", "Metin içinde geçerli bir Blender skill adı veya <<<ACIK: ...>>> bloğu bulunamadı.")

    def _save_and_close(self) -> None:
        self.saved_result = set(self.draft_active)
        self.saved_checked = set(self.checked_items)
        self.accept()


class ToolGearDialog(QDialog):
    """⚙️ Standart Araç Teknik Ayarları + (?) Özellik Rehberi + Çift Yönlü AI Danışma Penceresi."""

    def __init__(
        self,
        parent: QWidget,
        tool: ToolSpec,
        vault: WindowsDpapiVault,
        logs: LogDatabase,
        scope_display: str,
    ) -> None:
        super().__init__(parent)
        self.tool = tool
        self.vault = vault
        self.logs = logs
        self.scope_display = scope_display
        self.setWindowTitle(f"⚙️ {tool.name} — Teknik Ayarlar")
        self.setMinimumWidth(680)
        self.resize(700, 560)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # Konum / Proje Bilgi Kartı
        loc_card = QFrame()
        loc_card.setObjectName("card")
        loc_lay = QVBoxLayout(loc_card)
        loc_lay.addWidget(QLabel(f"<b>📁 Proje / Kapsam:</b> {scope_display}"))
        if tool.live_location_detail:
            det = QLabel(f"<span style='color:#94a3b8;'>{tool.live_location_detail}</span>")
            det.setWordWrap(True)
            loc_lay.addWidget(det)
        lay.addWidget(loc_card)

        # Canlı Özellik / Ayar Açıklama Kartı (Aşağıdaki ? butonları ve hover ile güncellenir)
        self.opt_help_card = QFrame()
        self.opt_help_card.setObjectName("card")
        self.opt_help_card.setStyleSheet("QFrame#card { border: 1px solid #2563eb; background-color: #132038; }")
        oh_lay = QVBoxLayout(self.opt_help_card)
        oh_lay.setContentsMargins(12, 8, 12, 8)
        oh_lay.setSpacing(4)
        self.opt_help_title = QLabel("<b>ℹ️ Özellik Rehberi (Açarsan / Kapatırsan Ne Olur?)</b>")
        self.opt_help_body = QLabel("")
        self.opt_help_body.setWordWrap(True)
        self.opt_help_body.setStyleSheet("color: #dbeafe; font-size: 12px;")
        oh_lay.addWidget(self.opt_help_title)
        oh_lay.addWidget(self.opt_help_body)

        if tool.param_label:
            p_card = QFrame()
            p_card.setObjectName("card")
            p_lay = QVBoxLayout(p_card)
            p_hdr = QHBoxLayout()
            p_hdr.setSpacing(6)
            p_hdr.addWidget(QLabel(f"<b>{tool.param_label}</b>"))
            p_help = tool.param_help or f"{tool.param_label} değerini projeye göre özelleştirmenizi sağlar."
            p_hdr.addWidget(
                _create_option_help_badge(
                    f"❓ {tool.param_label}\n{p_help}",
                    lambda lbl=tool.param_label, h=p_help: self._show_option_help(lbl, h),
                )
            )
            p_hdr.addStretch()
            p_lay.addLayout(p_hdr)
            self.param_inp = QLineEdit(tool.param_value)
            self.param_inp.setToolTip(p_help)
            p_lay.addWidget(self.param_inp)
            lay.addWidget(p_card)
        else:
            self.param_inp = None

        if tool.vault_key_name:
            v_card = QFrame()
            v_card.setObjectName("card")
            v_lay = QHBoxLayout(v_card)
            has_k = vault.has_secret(tool.vault_key_name)
            status_txt = "Tanımlı (Windows DPAPI ile Şifreli)" if has_k else "Henüz Girilmedi (Şifreli Kasa sekmesinden ekleyin)"
            v_lay.addWidget(QLabel(f"🔐 <b>{tool.vault_key_name}:</b> {status_txt}"))
            lay.addWidget(v_card)

        self.opt_checks: dict[str, QCheckBox] = {}
        if tool.options:
            opt_card = QFrame()
            opt_card.setObjectName("card")
            opt_lay = QVBoxLayout(opt_card)
            opt_lay.setSpacing(6)
            opt_lay.addWidget(
                QLabel(
                    "<b>Özellikler & Çalışma İzinleri</b>  "
                    "<span style='color:#94a3b8; font-size:11px;'>(Yanındaki <b>?</b> butonuna tıklayarak veya üzerine gelerek ne işe yaradığını okuyun)</span>"
                )
            )
            for opt in tool.options:
                row_w = QWidget()
                row_w.setObjectName("cellBox")
                r_lay = QHBoxLayout(row_w)
                r_lay.setContentsMargins(2, 2, 2, 2)
                r_lay.setSpacing(8)

                h_txt = (
                    opt.help_text
                    or "✅ AÇARSAN: Bu alt özelliği etkinleştirir.\n⛔ KAPATIRSAN: Bu alt özellik devre dışı kalır."
                )
                cb = QCheckBox(opt.label)
                cb.setChecked(opt.enabled)
                cb.setCursor(Qt.CursorShape.PointingHandCursor)
                cb.setToolTip(f"❓ {opt.label}\n\n{h_txt}")
                cb.installEventFilter(self)
                cb.setProperty("opt_title", opt.label)
                cb.setProperty("opt_help", h_txt)
                self.opt_checks[opt.key] = cb
                r_lay.addWidget(cb)

                info_btn = _create_option_help_badge(
                    f"❓ {opt.label}\n\n{h_txt}",
                    lambda lbl=opt.label, h=h_txt: self._show_option_help(lbl, h),
                )
                r_lay.addWidget(info_btn)
                r_lay.addStretch()
                opt_lay.addWidget(row_w)
            lay.addWidget(opt_card)

        lay.addWidget(self.opt_help_card)

        # Açılışta ilk özelliğin (veya parametrenin) açıklamasını rehber kutusunda hemen göster
        if tool.options:
            first = tool.options[0]
            self._show_option_help(
                first.label,
                first.help_text or "✅ AÇARSAN: Bu alt özelliği etkinleştirir.\n⛔ KAPATIRSAN: Devre dışı bırakır.",
            )
        elif tool.param_label:
            self._show_option_help(
                tool.param_label,
                tool.param_help or f"{tool.param_label} değerini yapılandırır.",
            )
        else:
            self.opt_help_card.hide()

        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setFixedHeight(95)
        self.prompt_preview.hide()
        lay.addWidget(self.prompt_preview)

        lay.addStretch()

        bot = QHBoxLayout()
        btn_ask = QPushButton("🤖 AI'a Danış (Prompt Kopyala)")
        btn_paste = QPushButton("📥 AI Yanıtını Yapıştır && Uygula")
        btn_cancel = QPushButton("Vazgeç")
        btn_save = QPushButton("💾 Kaydet")
        btn_save.setObjectName("successBtn")

        btn_ask.clicked.connect(self._copy_prompt)
        btn_paste.clicked.connect(self._paste_response)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)

        for b in (btn_ask, btn_paste):
            bot.addWidget(b)
        bot.addStretch()
        bot.addWidget(btn_cancel)
        bot.addWidget(btn_save)
        lay.addLayout(bot)

    def _show_option_help(self, title: str, help_body: str) -> None:
        self.opt_help_title.setText(f"<b>ℹ️ {title}</b>")
        self.opt_help_body.setText(help_body)
        self.opt_help_card.show()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Enter:
            t = watched.property("opt_title")
            h = watched.property("opt_help")
            if t and h:
                self._show_option_help(str(t), str(h))
        return super().eventFilter(watched, event)

    def _copy_prompt(self) -> None:
        cur_param = self.param_inp.text().strip() if self.param_inp else ""
        opt_states = {k: cb.isChecked() for k, cb in self.opt_checks.items()}
        has_key = self.vault.has_secret(self.tool.vault_key_name) if self.tool.vault_key_name else False
        issue = self.logs.latest_issue_for_tool(self.tool.name)
        prompt = build_tool_ai_prompt(self.tool, cur_param, opt_states, has_key, issue, self.scope_display)
        QApplication.clipboard().setText(prompt)
        self.prompt_preview.setPlainText(prompt)
        self.prompt_preview.show()

    def _paste_response(self) -> None:
        dlg = AiPasteDialog(self, f"📥 {self.tool.name} — AI Yanıtını Uygula")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            matched, msg = parse_tool_ai_response(self.tool, dlg.editor.toPlainText())
            if matched or "kapalı" in msg:
                for k, cb in self.opt_checks.items():
                    cb.setChecked(k in matched)
                QMessageBox.information(self, "AI Önerisi Uygulandı", f"{msg}.\nKaydet butonuna basarak kalıcı hale getirebilirsiniz.")
            else:
                QMessageBox.warning(self, "Eşleşme Yok", "Metinde geçerli bir seçenek anahtarı veya <<<ACIK: ...>>> satırı bulunamadı.")

    def _save(self) -> None:
        if self.param_inp is not None:
            self.tool.param_value = self.param_inp.text().strip()
        for opt in self.tool.options:
            opt.enabled = self.opt_checks[opt.key].isChecked()
        self.accept()


class ConnectionTestDialog(QDialog):
    """Antigravity/AI açık olmasa bile tüm aktif araçların gerçek MCP/soket/stdio bağlantısını uçtan uca test eder."""

    def __init__(
        self,
        parent: QWidget,
        tools: list[ToolSpec],
        vault: WindowsDpapiVault,
        projects_map: dict[str, str],
        active_skills_count: int,
    ) -> None:
        super().__init__(parent)
        self.tools = [t for t in tools if t.enabled]
        self.vault = vault
        self.projects_map = projects_map
        self.active_skills_count = active_skills_count
        self._running = False
        self._bridge = WorkerBridge()
        self._bridge.conn_test_row.connect(self._on_row_result)
        self._bridge.conn_test_done.connect(self._on_all_done)

        self.setWindowTitle("🔌 Bağlantı Test Merkezi (Canlı MCP & İstemci Doğrulama)")
        self.resize(840, 520)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        info = QLabel(
            "<b>Antigravity veya başka bir AI editörü açık olmasa bile</b> tüm <b>AÇIK</b> araçların gerçekten çalışıp çalışmadığını "
            "doğrudan test eder (HTTP MCP <code>initialize</code>, Blender <code>get_scene_info</code>, stdio MCP el sıkışması ve config kontrolü)."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        self.tbl = QTableWidget(len(self.tools), 4, self)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setHorizontalHeaderLabels(["Araç", "Durum", "Gecikme", "Test Sonucu / Detay"])
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tbl.itemSelectionChanged.connect(self._on_row_selected)
        lay.addWidget(self.tbl, stretch=1)

        self.detail_box = QPlainTextEdit()
        self.detail_box.setReadOnly(True)
        self.detail_box.setFixedHeight(95)
        self.detail_box.setPlaceholderText("Detaylı ham teknik yanıtı görmek için yukarıdan bir satıra tıklayın...")
        lay.addWidget(self.detail_box)

        bot = QHBoxLayout()
        self.summary_lbl = QLabel("Hazır.")
        self.summary_lbl.setStyleSheet("font-weight: 600;")
        bot.addWidget(self.summary_lbl, stretch=1)

        self.btn_retest = QPushButton("🔄 Tümünü Tekrar Test Et")
        self.btn_retest.setObjectName("primaryBtn")
        self.btn_retest.clicked.connect(self.start_tests)
        bot.addWidget(self.btn_retest)

        btn_close = QPushButton("Kapat")
        btn_close.clicked.connect(self.accept)
        bot.addWidget(btn_close)
        lay.addLayout(bot)

        self._raw_details: list[str] = [""] * len(self.tools)
        self._ok_count = 0
        self._fail_count = 0
        self.start_tests()

    def start_tests(self) -> None:
        if self._running:
            return
        self._running = True
        self._ok_count = 0
        self._fail_count = 0
        self.btn_retest.setEnabled(False)
        self._raw_details = [""] * len(self.tools)

        if not self.tools:
            self.summary_lbl.setText("⚠️ Panelde AÇIK araç yok — önce Araç Paneli'nden test etmek istediğiniz araçları açın.")
            self._running = False
            self.btn_retest.setEnabled(True)
            return

        self.summary_lbl.setText(f"⏳ {len(self.tools)} aktif araç test ediliyor...")
        for r, t in enumerate(self.tools):
            self.tbl.setItem(r, 0, QTableWidgetItem(t.name))
            self.tbl.setItem(r, 1, QTableWidgetItem("⏳ Bekliyor"))
            self.tbl.setItem(r, 2, QTableWidgetItem("—"))
            self.tbl.setItem(r, 3, QTableWidgetItem("Bağlantı deneniyor..."))

        snap = list(self.tools)
        proj = dict(self.projects_map)
        sk = self.active_skills_count

        def worker() -> None:
            for idx, t in enumerate(snap):
                ok, ms, msg, raw = test_tool_connection_e2e(t, self.vault, proj, sk)
                self._bridge.conn_test_row.emit(idx, ok, ms, msg, raw)
            self._bridge.conn_test_done.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _on_row_result(self, row: int, ok: bool, ms: int, msg: str, raw: str) -> None:
        if row < 0 or row >= len(self.tools):
            return
        self._raw_details[row] = raw
        if ok:
            self._ok_count += 1
        else:
            self._fail_count += 1
        st_item = QTableWidgetItem("✅ Başarılı" if ok else "❌ Başarısız")
        st_item.setForeground(QColor("#22c55e" if ok else "#ef4444"))
        self.tbl.setItem(row, 1, st_item)
        self.tbl.setItem(row, 2, QTableWidgetItem(f"{ms}ms" if ms >= 0 else "—"))
        self.tbl.setItem(row, 3, QTableWidgetItem(msg))

    def _on_all_done(self) -> None:
        self._running = False
        self.btn_retest.setEnabled(True)
        self.summary_lbl.setText(
            f"Test Tamamlandı: {self._ok_count} Başarılı, {self._fail_count} Başarısız ({len(self.tools)} AÇIK araç)"
        )

    def _on_row_selected(self) -> None:
        idxs = self.tbl.selectionModel().selectedRows()
        if not idxs:
            return
        r = idxs[0].row()
        if 0 <= r < len(self._raw_details):
            self.detail_box.setPlainText(self._raw_details[r])


class MainWindow(QMainWindow):
    """AI Araç & Token Ekonomisi Masaüstü Kontrol Merkezi Ana Penceresi."""

    def __init__(self, data_dir: pathlib.Path, sync_live_environment: bool = True) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.sync_live_environment = sync_live_environment
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.vault = WindowsDpapiVault(self.data_dir / "vault.dpapi.json")
        self.logs = LogDatabase(self.data_dir / "ai_hub_logs.db")
        self.store = StateStore(self.data_dir / "hub_state.json")

        self.tools: list[ToolSpec] = build_default_catalog()
        self.default_ids: set[str] = {t.id for t in self.tools}
        self.active_skills, self.meta = self.store.load_into(self.tools)

        self.sort_key = str(self.meta.get("sort_key", "usage"))
        self.sort_desc = bool(self.meta.get("sort_desc", True))
        self.seconds_left = 30
        self._live_watch_busy = False
        self.last_detected_apps = {"unity": False, "blender": False}
        self.detected_repo_candidate: dict[str, Any] | None = None
        self.tray_notified = False
        self.force_quit = False

        self.bridge = WorkerBridge()
        self.bridge.health_done.connect(self._on_health_results)
        self.bridge.repo_done.connect(self._on_repo_inspected)
        self.bridge.plugin_check_done.connect(self._on_plugin_check_done)
        self.bridge.update_progress.connect(self._on_update_progress)
        self.bridge.update_all_done.connect(self._on_update_all_done)
        self.bridge.app_check_done.connect(self._on_bg_app_check_done)
        self.plugin_checks: dict[str, QCheckBox] = {}
        self.panel_row_checks: dict[str, QCheckBox] = {}
        self.checked_log_ids: set[int] = set()
        self.log_row_checks: dict[int, QCheckBox] = {}
        self.profile_btns: dict[str, QPushButton] = {}
        self._auto_heal_cooldown: dict[str, float] = {}
        self._last_warn_time: dict[str, float] = {}
        self._latest_live_map: dict[str, str] = {}
        saved_lang = str(self.meta.get("lang") or "").strip().lower()
        valid_langs = {c for c, _ in SUPPORTED_LANGUAGES}
        self.lang = saved_lang if saved_lang in valid_langs else detect_default_language()
        self.meta["lang"] = self.lang
        self.updating_busy = False
        self.checking_plugins_busy = False
        self.latest_app_check: UpdateCheckResult | None = None
        self._silent_app_check = False
        self._startup_app_check = False

        app_ver = get_current_app_version()
        self.setWindowTitle(tr(self.lang, "app_title", ver=app_ver))
        self.setWindowIcon(create_app_icon())
        self.resize(1340, 760)

        self._build_ui()
        self._build_tray()
        self._apply_theme(self.meta.get("theme", "dark"))
        self._update_profile_buttons_ui()
        self._retranslate_ui()
        for t in self.tools:
            t.live_location_detail = resolve_disk_location(t, self.projects_map, {})
        self._rebuild_project_filter_combo()
        self._rebuild_custom_presets_combo()
        self._refresh_table()
        self._refresh_plugins_tab()
        self._refresh_vault_tab()
        self._refresh_logs_tab()
        self._update_vram_bar()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._on_second_tick)
        self.tick_timer.start(1000)

        if self.sync_live_environment:
            QTimer.singleShot(250, lambda: self._sync_live_environment_async(target_tools=list(self.tools)))
        else:
            QTimer.singleShot(250, self.run_health_scan)
        # Açılışta otomatik güncelleme kontrolü (yalnız kontrol eder; başlatmak kullanıcıya aittir)
        QTimer.singleShot(900, lambda: self.run_plugin_update_check(manual=False))
        QTimer.singleShot(1400, self._run_startup_app_update_check)

    @property
    def projects_map(self) -> dict[str, str]:
        return self.meta.setdefault("projects", {})

    def _format_scope_display(self, t: ToolSpec) -> str:
        if not t.scope_selectable:
            return t.fixed_location_label or "🖥️ Sistem Geneli"
        if t.project_scope == "GLOBAL":
            return "🌐 Tüm Projeler (Global)"
        p_dir = self.projects_map.get(t.project_scope, "")
        return f"📁 {t.project_scope} ({p_dir})" if p_dir else f"📁 {t.project_scope}"

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(12, 10, 12, 8)
        main_lay.setSpacing(8)

        # 1. ÜST BAR: Hazır İş Modu Profilleri (Çoklu Seçilebilir) + Oto-Algılama + VRAM + Sayaç
        prof_bar = QHBoxLayout()
        self.lbl_preset = QLabel(tr(self.lang, "preset_lbl"))
        prof_bar.addWidget(self.lbl_preset)
        for p_key, p_info in PROFILES.items():
            btn = QPushButton(p_info["title"].replace("&", "&&"))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(
                f"{p_info['desc']}\n"
                "• Tıkladığınızda seçili kalır; birden fazla hazır ayarı birlikte seçebilirsiniz.\n"
                "• Seçili olana tekrar tıkladığınızda seçimi kaldırır."
            )
            btn.clicked.connect(lambda _=False, k=p_key: self.apply_profile(k))
            self.profile_btns[p_key] = btn
            prof_bar.addWidget(btn)

        self.auto_detect_cb = QCheckBox("👁️ Oto-Algıla")
        self.auto_detect_cb.setToolTip("Unity.exe veya blender.exe açıldığında otomatik algılar")
        self.auto_detect_cb.setChecked(bool(self.meta.get("auto_detect_apps", True)))
        self.auto_detect_cb.toggled.connect(self._on_auto_detect_toggled)
        prof_bar.addWidget(self.auto_detect_cb)

        prof_bar.addStretch()

        self.vram_bar = QProgressBar()
        self.vram_bar.setFixedWidth(185)
        self.vram_bar.setFormat("VRAM: Ölçülüyor...")
        prof_bar.addWidget(self.vram_bar)

        self.btn_vram_free = QPushButton(tr(self.lang, "vram_free"))
        self.btn_vram_free.setToolTip("Arka planda açık kalan Trellis GPU sunucusunu uyutup VRAM'i boşaltır")
        self.btn_vram_free.clicked.connect(self._handle_free_vram)
        prof_bar.addWidget(self.btn_vram_free)

        self.timer_lbl = QLabel("00:30")
        self.timer_lbl.setStyleSheet("font-family: Consolas, monospace; font-weight: 700; padding: 4px 8px;")
        prof_bar.addWidget(self.timer_lbl)

        self.btn_refresh = QPushButton(tr(self.lang, "scan_now"))
        self.btn_refresh.setToolTip("Tüm araçların port, sağlık, VRAM ve canlı süreç durumlarını anında yeniler")
        self.btn_refresh.clicked.connect(self.run_health_scan)
        prof_bar.addWidget(self.btn_refresh)

        self.btn_test_conns = QPushButton(tr(self.lang, "test_conns"))
        self.btn_test_conns.setToolTip(
            "Antigravity açık olmasa bile tüm AÇIK araçlara gerçek MCP/soket/stdio testi atıp\n"
            "bağlantıların gerçekten çalışıp çalışmadığını doğrular."
        )
        self.btn_test_conns.clicked.connect(self._open_connection_test_dialog)
        prof_bar.addWidget(self.btn_test_conns)

        self.btn_app_update_top = QPushButton(tr(self.lang, "app_update"))
        self.btn_app_update_top.setObjectName("primaryBtn")
        self.btn_app_update_top.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_app_update_top.setToolTip(
            "Bu programın (DoranPierst/AIconomy) yeni bir sürümü var mı doğrudan kontrol eder.\n"
            "• Yeni sürüm çıktığında tek tıkla indirip programı otomatik yeniler.\n"
            "• Sağ tık: Program sürüm detaylarını açar."
        )
        self.btn_app_update_top.clicked.connect(self._handle_quick_check_app_update)
        self.btn_app_update_top.customContextMenuRequested.connect(lambda _pos: self._open_app_update_dialog(self.latest_app_check))
        prof_bar.addWidget(self.btn_app_update_top)

        self.btn_sync = QPushButton(tr(self.lang, "sync_configs"))
        self.btn_sync.setObjectName("successBtn")
        self.btn_sync.setToolTip(
            "Global ve Proje Bazlı yapılandırmaları yedek (.bak) alarak yazar:\n"
            "• Antigravity (AGY): ~/.gemini/config/mcp_config.json\n"
            "• Codex (CDX): ~/.codex/config.toml\n"
            "• Claude Code (CLD): ~/.claude.json ve <proje>/.mcp.json\n"
            "• Cursor (CUR): ~/.cursor/mcp.json ve <proje>/.cursor/mcp.json\n"
            "• Program Ayar Yedeği: data/hub_state.json"
        )
        self.btn_sync.clicked.connect(self._handle_sync_configs)
        prof_bar.addWidget(self.btn_sync)

        self.lang_cmb = QComboBox()
        self.lang_cmb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_cmb.setToolTip("Arayüz Dili / Interface Language")
        for l_code, l_lbl in SUPPORTED_LANGUAGES:
            self.lang_cmb.addItem(l_lbl, l_code)
        l_idx = self.lang_cmb.findData(self.lang)
        self.lang_cmb.setCurrentIndex(max(0, l_idx))
        self.lang_cmb.currentIndexChanged.connect(self._on_language_changed)
        prof_bar.addWidget(self.lang_cmb)

        self.btn_theme = QPushButton(tr(self.lang, "theme"))
        self.btn_theme.clicked.connect(self._toggle_theme)
        prof_bar.addWidget(self.btn_theme)

        main_lay.addLayout(prof_bar)

        # YENİ SÜRÜM BİLDİRİM ÇUBUĞU (Yalnızca bu programın yeni sürümü çıktığında otomatik görünür)
        self.app_update_banner = QFrame()
        self.app_update_banner.setObjectName("card")
        self.app_update_banner.setStyleSheet("QFrame#card { border: 1px solid #f59e0b; background-color: #271a0c; }")
        ub_lay = QHBoxLayout(self.app_update_banner)
        ub_lay.setContentsMargins(12, 6, 12, 6)
        self.app_update_banner_lbl = QLabel("")
        self.app_update_banner_lbl.setStyleSheet("color: #fde68a; font-weight: 700;")
        ub_lay.addWidget(self.app_update_banner_lbl, stretch=1)

        self.app_update_notes_lbl = QLabel("")
        self.app_update_notes_lbl.setOpenExternalLinks(True)
        ub_lay.addWidget(self.app_update_notes_lbl)

        btn_banner_upd = QPushButton("⚡ Tek Tıkla Programı Güncelle")
        btn_banner_upd.setObjectName("warnBtn")
        btn_banner_upd.clicked.connect(lambda: self._open_app_update_dialog(self.latest_app_check))
        ub_lay.addWidget(btn_banner_upd)
        self.app_update_banner.hide()
        main_lay.addWidget(self.app_update_banner)

        # 2. SEKMELER
        self.tabs = QTabWidget()
        main_lay.addWidget(self.tabs, stretch=1)

        self._init_panel_tab()
        self._init_plugins_tab()
        self._init_vault_tab()
        self._init_repo_tab()
        self._init_logs_tab()

        # 3. ALT DURUM ÇUBUĞU + SÜRÜM/KANAL BUTONU
        foot = QHBoxLayout()
        self.status_lbl = QLabel("Hazır — Sağ alt sistem tepsisinde (Tray) kesintisiz çalışır.")
        foot.addWidget(self.status_lbl, stretch=1)

        self.btn_do_app_upd = QPushButton(f"📦 Program Sürümü: {get_current_app_version()}v")
        self.btn_do_app_upd.setToolTip("Kullandığınız programın sürüm notlarını ve güncelleme detaylarını açar")
        self.btn_do_app_upd.clicked.connect(lambda: self._open_app_update_dialog(self.latest_app_check))
        foot.addWidget(self.btn_do_app_upd)

        self.token_summary_lbl = QLabel()
        self.token_summary_lbl.setStyleSheet("font-family: Consolas, monospace; font-weight: 600; color: #22c55e;")
        foot.addWidget(self.token_summary_lbl)
        main_lay.addLayout(foot)

    def _make_info_btn(self, tool: ToolSpec) -> QPushButton:
        btn = QPushButton("?")
        btn.setFixedSize(20, 20)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        is_light = self.meta.get("theme", "dark") == "light"
        btn.setStyleSheet(
            "QPushButton { background-color: #dbeafe; color: #1d4ed8; border: 1px solid #60a5fa; "
            "border-radius: 10px; font-size: 11px; font-weight: 800; padding: 0px; }"
            "QPushButton:hover { background-color: #2563eb; color: #ffffff; }"
            if is_light
            else "QPushButton { background-color: #172554; color: #93c5fd; border: 1px solid #3b82f6; "
            "border-radius: 10px; font-size: 11px; font-weight: 800; padding: 0px; }"
            "QPushButton:hover { background-color: #2563eb; color: #ffffff; }"
        )
        tip_parts = [f"❓ {tool.name} — Ne İşe Yarar?"]
        if tool.summary:
            tip_parts.append(tool.summary)
        if tool.when_to_use:
            tip_parts.append(f"\n💡 Ne zaman kullanılır:\n{tool.when_to_use}")
        tip_parts.append("\n(Detaylı açıklama kartını açmak için tıklayın)")
        btn.setToolTip("\n".join(tip_parts))
        btn.clicked.connect(lambda _=False, t_obj=tool: ToolInfoDialog(self, t_obj).exec())
        return btn

    # --- SEKME 1: ANA PANEL (8 SÜTUN — PROJE / KONUM DAHİL) ---
    def _init_panel_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        flt = QHBoxLayout()
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("Araç, görev veya konum ara (örn: Serena, shader, ses, doküman)...")
        self.search_inp.setFixedWidth(250)
        self.search_inp.textChanged.connect(self._refresh_table)
        flt.addWidget(self.search_inp)

        self.kind_cmb = QComboBox()
        for k_data, k_lbl in [
            ("ALL", tr(self.lang, "all_types")),
            ("Skill Paketi", "Skill Paketi"),
            ("Skill / Kural", "Skill / Kural"),
            ("stdio MCP", "stdio MCP"),
            ("HTTP Servis", "HTTP Servis"),
            ("CLI / GPU", "CLI / GPU"),
        ]:
            self.kind_cmb.addItem(k_lbl, k_data)
        self.kind_cmb.currentIndexChanged.connect(self._refresh_table)
        flt.addWidget(self.kind_cmb)

        self.lbl_proj_flt = QLabel(tr(self.lang, "project_lbl"))
        flt.addWidget(self.lbl_proj_flt)
        self.proj_filter_cmb = QComboBox()
        self.proj_filter_cmb.currentIndexChanged.connect(self._refresh_table)
        flt.addWidget(self.proj_filter_cmb)

        self.btn_add_proj = QPushButton(tr(self.lang, "add_project"))
        self.btn_add_proj.setToolTip("Yeni bir oyun veya web sitesi klasörünü proje listesine ekler")
        self.btn_add_proj.clicked.connect(lambda: self._prompt_add_project_folder(assign_tool=None))
        flt.addWidget(self.btn_add_proj)

        flt.addStretch()

        # ÖZEL KAYITLI AYARLARIM KUTUSU (Üstteki Hazır Ayarlardan ayrı, kullanıcıya özel isimli kayıtlar)
        preset_box = QFrame()
        preset_box.setObjectName("card")
        pb_lay = QHBoxLayout(preset_box)
        pb_lay.setContentsMargins(8, 3, 8, 3)
        pb_lay.setSpacing(6)

        self.lbl_saved_presets = QLabel(tr(self.lang, "saved_presets_lbl"))
        pb_lay.addWidget(self.lbl_saved_presets)

        self.saved_presets_cmb = QComboBox()
        self.saved_presets_cmb.setMinimumWidth(220)
        self.saved_presets_cmb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.saved_presets_cmb.setToolTip(
            "Daha önce isim vererek kaydettiğiniz özel araç/proje düzenlerini listeler.\n"
            "• Bir kayıt seçtiğinizde tüm araçlar (AÇIK/KAPALI, AI istemcileri, proje kapsamı, modlar) o kayda döner."
        )
        self.saved_presets_cmb.currentIndexChanged.connect(self._on_custom_preset_selected)
        pb_lay.addWidget(self.saved_presets_cmb)

        self.btn_save_preset = QPushButton(tr(self.lang, "save_btn"))
        self.btn_save_preset.setObjectName("primaryBtn")
        self.btn_save_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_preset.setToolTip("Şu anki araç, AI ve proje ayarlarınızı istediğiniz bir isimle kaydeder")
        self.btn_save_preset.clicked.connect(self._save_custom_preset)
        pb_lay.addWidget(self.btn_save_preset)

        self.btn_del_preset = QPushButton("🗑️")
        self.btn_del_preset.setFixedSize(28, 26)
        self.btn_del_preset.setStyleSheet("padding: 0px; font-size: 13px;")
        self.btn_del_preset.setEnabled(False)
        self.btn_del_preset.setToolTip("Seçili kayıtlı ayarı sil")
        self.btn_del_preset.clicked.connect(self._delete_custom_preset)
        pb_lay.addWidget(self.btn_del_preset)

        flt.addWidget(preset_box)
        lay.addLayout(flt)

        # BAĞIMLI PROGRAM UYARI ÇUBUĞU (Yalnızca AÇIK bir aracın bağlı olduğu program kapalıysa görünür)
        self.host_dep_banner = QFrame()
        self.host_dep_banner.setObjectName("card")
        self.host_dep_banner.setStyleSheet("QFrame#card { border: 1px solid #f59e0b; background-color: #271a0c; }")
        hdb_lay = QHBoxLayout(self.host_dep_banner)
        hdb_lay.setContentsMargins(10, 5, 10, 5)
        hdb_lay.setSpacing(8)
        self.host_dep_lbl = QLabel("")
        self.host_dep_lbl.setStyleSheet("color: #fde68a; font-weight: 600;")
        self.host_dep_lbl.setWordWrap(True)
        hdb_lay.addWidget(self.host_dep_lbl, stretch=1)
        self.host_dep_btns_lay = QHBoxLayout()
        self.host_dep_btns_lay.setSpacing(6)
        hdb_lay.addLayout(self.host_dep_btns_lay)
        self.host_dep_banner.hide()
        lay.addWidget(self.host_dep_banner)

        self.table = HoverTableWidget(0, 8, self)
        self.ai_header = AiMatrixHeaderView(self.table, self)
        self.bulk_client_btns: dict[str, QPushButton] = self.ai_header.buttons
        self.table.setHorizontalHeader(self.ai_header)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setHorizontalHeaderLabels(
            [
                "Araç",
                "Tür",
                "Proje / Konum",
                "Son Yanıt",
                "Kullanım",
                "",
                "Çalışma Modu",
                "Detay / Durum",
            ]
        )
        hdr = self.ai_header
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(5, AiMatrixHeaderView.AI_COL_WIDTH)
        self.table.setColumnWidth(5, AiMatrixHeaderView.AI_COL_WIDTH)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr.sectionClicked.connect(self._on_header_clicked)
        self.table.horizontalScrollBar().valueChanged.connect(lambda *_: hdr.sync_ai_bar_geometry())
        lay.addWidget(self.table, stretch=1)

        # ARAÇ PANELİ ALT SEÇİM & GENEL DURUM KOPYALAMA ÇUBUĞU
        panel_bot = QHBoxLayout()
        panel_bot.setContentsMargins(2, 4, 2, 0)

        self.lbl_panel_sel = QLabel("☑️ Seçili: 14 / 14 araç")
        self.lbl_panel_sel.setStyleSheet("color: #94a3b8; font-weight: 600;")
        panel_bot.addWidget(self.lbl_panel_sel)

        btn_p_all = QPushButton("Tümünü Seç")
        btn_p_all.clicked.connect(lambda: self._set_panel_checks("all"))
        panel_bot.addWidget(btn_p_all)

        btn_p_act = QPushButton("Sadece Açıkları Seç")
        btn_p_act.setToolTip("Yalnızca şu an durumu AÇIK olan araçları seçer")
        btn_p_act.clicked.connect(lambda: self._set_panel_checks("enabled_only"))
        panel_bot.addWidget(btn_p_act)

        btn_p_none = QPushButton("Seçimi Temizle")
        btn_p_none.clicked.connect(lambda: self._set_panel_checks("none"))
        panel_bot.addWidget(btn_p_none)

        panel_bot.addStretch()

        self.btn_copy_tools_status = QPushButton("📋 Seçili Araçların Genel Durumunu Kopyala (14)")
        self.btn_copy_tools_status.setObjectName("primaryBtn")
        self.btn_copy_tools_status.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_tools_status.setToolTip(
            "Yalnızca tabloda işaretlediğiniz araçların genel durumunu (Açık/Kapalı, AI istemcileri,\n"
            "çalışma modu, son yanıt, aktif seçenekler ve proje konumları) düzenli rapor olarak kopyalar."
        )
        self.btn_copy_tools_status.clicked.connect(self._copy_selected_tools_status)
        panel_bot.addWidget(self.btn_copy_tools_status)
        lay.addLayout(panel_bot)

        self.tabs.addTab(tab, "📊 Araç Paneli (14)")

    def _rebuild_project_filter_combo(self) -> None:
        cur_data = self.proj_filter_cmb.currentData() if self.proj_filter_cmb.count() else "ALL"
        self.proj_filter_cmb.blockSignals(True)
        self.proj_filter_cmb.clear()
        self.proj_filter_cmb.addItem(tr(self.lang, "all_scopes"), "ALL")
        self.proj_filter_cmb.addItem(tr(self.lang, "global_only"), "GLOBAL")
        for p_name in sorted(self.projects_map.keys()):
            self.proj_filter_cmb.addItem(f"📁 {p_name}", p_name)
        idx = self.proj_filter_cmb.findData(cur_data)
        self.proj_filter_cmb.setCurrentIndex(max(0, idx))
        self.proj_filter_cmb.blockSignals(False)

    def _prompt_add_project_folder(self, assign_tool: ToolSpec | None) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Proje Klasörünü Seçin (Unity, Web Sitesi vb.)")
        if not folder:
            if assign_tool is not None:
                self._refresh_table()
            return
        p_path = pathlib.Path(folder)
        proj_key = p_path.name
        self.projects_map[proj_key] = str(p_path)
        if assign_tool is not None and assign_tool.scope_selectable:
            assign_tool.project_scope = proj_key
        self._save_state()
        self._rebuild_project_filter_combo()
        self.run_health_scan()
        self.set_status(f"📁 Yeni proje tanımlandı: {proj_key} ({p_path})")

    def _on_header_clicked(self, col: int) -> None:
        key_map = {0: "name", 1: "kind", 2: "project", 3: "ping", 4: "usage", 6: "mode", 7: "enabled"}
        if col not in key_map:
            return
        k = key_map[col]
        if self.sort_key == k:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = k
            self.sort_desc = col in (3, 4, 7)
        self._save_state()
        self._refresh_table()

    def _update_panel_header_indicators(self) -> None:
        base_labels = [
            tr(self.lang, "col_tool"),
            tr(self.lang, "col_kind"),
            tr(self.lang, "col_project"),
            tr(self.lang, "col_ping"),
            tr(self.lang, "col_usage"),
            "",
            tr(self.lang, "col_mode"),
            tr(self.lang, "col_status"),
        ]
        key_to_col = {
            "name": 0,
            "kind": 1,
            "project": 2,
            "ping": 3,
            "usage": 4,
            "mode": 6,
            "enabled": 7,
        }
        active_col = key_to_col.get(self.sort_key, -1)
        arrow = " ▼" if self.sort_desc else " ▲"
        labels = [
            f"{lbl}{arrow}" if (idx == active_col and lbl) else lbl
            for idx, lbl in enumerate(base_labels)
        ]
        self.table.setHorizontalHeaderLabels(labels)

    def _tool_sort_value(self, item: ToolSpec) -> Any:
        if self.sort_key == "name":
            return item.name.lower()
        if self.sort_key == "kind":
            return (item.kind.lower(), item.name.lower())
        if self.sort_key == "project":
            if item.scope_selectable:
                vis = "tüm projeler" if item.project_scope == "GLOBAL" else item.project_scope.lower()
            else:
                raw = (item.fixed_location_label or "sistem geneli").strip()
                vis = raw.lstrip("🖥️🌐📁📍🟢⚠️☁️ ").lower()
            return (vis, item.name.lower())
        if self.sort_key == "ping":
            if item.last_latency_ms >= 0:
                return (1, -item.last_latency_ms, item.name.lower())
            return (0, 0, item.last_ping.lower(), item.name.lower())
        if self.sort_key == "mode":
            if item.id == "blender_skills":
                m_txt = f"{len(self.active_skills):02d}/94"
            elif len(item.modes) > 1:
                m_txt = item.modes[item.mode_index].lower()
            else:
                m_txt = "~"
            return (m_txt, item.name.lower())
        if self.sort_key == "enabled":
            return (1 if item.enabled else 0, item.usage_count, item.name.lower())
        return (item.usage_count, item.name.lower())

    def _calculate_token_economy(self) -> tuple[int, int]:
        active_tok = 0
        saved_tok = 0
        for t in self.tools:
            if t.id == "blender_skills":
                per_skill = 350
                on_cnt = len(self.active_skills) if t.enabled else 0
                active_tok += on_cnt * per_skill
                saved_tok += (len(BLENDER_SKILLS_94) - on_cnt) * per_skill
            else:
                if t.enabled:
                    active_tok += t.schema_tokens
                else:
                    saved_tok += t.schema_tokens
        return round(active_tok / 1000), round(saved_tok / 1000)

    def _refresh_table(self) -> None:
        q = self.search_inp.text().strip().lower()
        kf = str(self.kind_cmb.currentData() or "ALL")
        pf = self.proj_filter_cmb.currentData() or "ALL"

        rows: list[ToolSpec] = []
        for t in self.tools:
            if q and (
                q not in t.name.lower()
                and q not in t.kind.lower()
                and q not in t.summary.lower()
                and q not in t.project_scope.lower()
                and q not in t.live_location_detail.lower()
            ):
                continue
            if kf != "ALL" and t.kind != kf:
                continue
            if pf == "GLOBAL" and (not t.scope_selectable or t.project_scope != "GLOBAL"):
                continue
            if pf not in ("ALL", "GLOBAL"):
                # Belirli bir proje filtresi seçildiğinde hem o projeye özel araçları hem de tüm projelerde çalışan GLOBAL araçları göster
                if t.scope_selectable and t.project_scope not in (pf, "GLOBAL"):
                    continue
            rows.append(t)

        self._update_panel_header_indicators()
        rows.sort(key=self._tool_sort_value, reverse=self.sort_desc)
        panel_checked_set = self._get_panel_checked_set()
        self.panel_row_checks.clear()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))

        for r_idx, t in enumerate(rows):
            self.table.setRowHeight(r_idx, 38)

            # Sütun 0: Seçim Kutusu + Eklenti Adı + (?) Ne İşe Yarar Bilgi Butonu
            nm_w = QWidget()
            nm_w.setObjectName("cellBox")
            nm_l = QHBoxLayout(nm_w)
            nm_l.setContentsMargins(10, 2, 6, 2)
            nm_l.setSpacing(6)

            row_cb = QCheckBox()
            row_cb.setCursor(Qt.CursorShape.PointingHandCursor)
            row_cb.setChecked(t.id in panel_checked_set)
            row_cb.setToolTip(f"{t.name} aracını durum kopyalama listesine dahil et / çıkar")
            row_cb.toggled.connect(lambda checked, tid=t.id: self._on_panel_row_check_toggled(tid, checked))
            self.panel_row_checks[t.id] = row_cb
            nm_l.addWidget(row_cb)

            nm_lbl = QLabel(f"<b>{t.name}</b>")
            if t.summary or t.live_location_detail:
                nm_lbl.setToolTip(f"{t.summary}\n\n{t.live_location_detail}".strip())
            nm_l.addWidget(nm_lbl)

            cur_v = t.version.strip().lstrip("vV")
            lat_v = (t.latest_version or t.version).strip().lstrip("vV")
            if t.has_update and lat_v != cur_v:
                ver_lbl = QLabel(f"{cur_v}v > {lat_v}v")
                ver_lbl.setStyleSheet(
                    "color: #f59e0b; background-color: #271a0c; border: 1px solid #f59e0b; "
                    "border-radius: 4px; padding: 1px 5px; font-size: 10px; font-weight: 700;"
                )
                ver_lbl.setToolTip(f"Eklenti güncellemesi mevcut: {cur_v}v -> {lat_v}v")
            else:
                ver_lbl = QLabel(f"{cur_v}v")
                ver_lbl.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600;")
                ver_lbl.setToolTip(f"{t.name} kurulu sürümü: {cur_v}v")
            nm_l.addWidget(ver_lbl)

            nm_l.addWidget(self._make_info_btn(t))
            nm_l.addStretch()
            self.table.setCellWidget(r_idx, 0, nm_w)

            kd_item = QTableWidgetItem(t.kind)
            kd_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r_idx, 1, kd_item)

            # Sütun 2: PROJE / KONUM (Seçilebilir olanlarda proje kutusu + canlı konum rozeti; sabit servislerde gerçek konum etiketi)
            proj_w = QWidget()
            proj_w.setObjectName("cellBox")
            proj_l = QHBoxLayout(proj_w)
            proj_l.setContentsMargins(4, 2, 4, 2)
            proj_l.setSpacing(4)

            is_live = (
                t.enabled
                and t.live_location_detail.startswith("🟢")
                and (t.id != "blender_mcp" or t.last_latency_ms >= 0)
            )
            is_warn = t.live_location_detail.startswith("⚠️")
            tooltip_full = f"{self._format_scope_display(t)}\n{t.live_location_detail}".strip()

            if t.scope_selectable:
                p_cmb = QComboBox()
                p_cmb.addItem("🌐 Tüm Projeler", "GLOBAL")
                for p_name in sorted(self.projects_map.keys()):
                    p_cmb.addItem(f"📁 {p_name}", p_name)
                p_cmb.addItem("➕ Klasör Seç...", "__ADD_NEW__")

                cur_idx = p_cmb.findData(t.project_scope)
                p_cmb.setCurrentIndex(cur_idx if cur_idx >= 0 else 0)
                p_cmb.setToolTip(tooltip_full)
                p_cmb.currentIndexChanged.connect(
                    lambda _idx, cmb=p_cmb, tool_obj=t: self._on_tool_scope_changed(tool_obj, str(cmb.currentData()))
                )
                proj_l.addWidget(p_cmb, stretch=1)
            else:
                fixed_lbl = QLabel(t.fixed_location_label or "🖥️ Sistem Geneli")
                fixed_lbl.setStyleSheet("color: #94a3b8; padding-left: 4px;")
                fixed_lbl.setToolTip(tooltip_full)
                proj_l.addWidget(fixed_lbl, stretch=1)

            loc_btn = QPushButton("🟢" if is_live else ("⚠️" if is_warn else "📍"))
            loc_btn.setFixedSize(32, 26)
            loc_btn.setStyleSheet("padding: 0px; font-size: 13px;")
            loc_btn.setToolTip(f"{tooltip_full}\n(Konum bilgisini panoya kopyalamak için tıklayın)")
            loc_btn.clicked.connect(
                lambda _=False, info=tooltip_full, nm=t.name: (
                    QApplication.clipboard().setText(info),
                    self.set_status(f"📍 {nm} konum bilgisi kopyalandı: {info.splitlines()[-1]}"),
                )
            )
            proj_l.addWidget(loc_btn)
            self.table.setCellWidget(r_idx, 2, proj_w)

            # Sütun 3: Son Yanıt
            pg_item = QTableWidgetItem(t.last_ping)
            pg_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r_idx, 3, pg_item)

            # Sütun 4: Kullanım
            us_item = QTableWidgetItem(str(t.usage_count))
            us_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            us_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r_idx, 4, us_item)

            # Sütun 5: AI Matrisi [AGY] [CDX] [CLD] [CUR]
            mat_w = QWidget()
            mat_w.setObjectName("cellBox")
            mat_l = QHBoxLayout(mat_w)
            mat_l.setContentsMargins(4, 2, 4, 2)
            mat_l.setSpacing(3)
            for code, full_lbl in AI_CLIENTS:
                c_btn = QPushButton(code)
                c_btn.setCheckable(True)
                is_c_on = t.clients.get(code, False)
                c_btn.setChecked(is_c_on)
                c_btn.setToolTip(f"{full_lbl}: {'Açık' if is_c_on else 'Kapalı'}")
                c_btn.setFixedWidth(36)
                c_btn.setStyleSheet(
                    "background-color: #1d4ed8; color: #fff; font-size: 10px; font-weight: 700; padding: 2px;"
                    if is_c_on
                    else "color: #64748b; font-size: 10px; padding: 2px;"
                )
                c_btn.clicked.connect(lambda checked, tool_obj=t, c=code: self._toggle_client(tool_obj, c, checked))
                mat_l.addWidget(c_btn)
            self.table.setCellWidget(r_idx, 5, mat_w)

            # Sütun 6: Çalışma Modu
            mod_w = QWidget()
            mod_w.setObjectName("cellBox")
            mod_l = QHBoxLayout(mod_w)
            mod_l.setContentsMargins(4, 2, 4, 2)
            if t.id == "blender_skills":
                sk_btn = QPushButton(f"{len(self.active_skills)} / 94 Açık")
                sk_btn.clicked.connect(lambda _=False, tool_obj=t: self.open_gear(tool_obj))
                mod_l.addWidget(sk_btn)
            elif len(t.modes) > 1:
                cmb = QComboBox()
                cmb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
                cmb.addItems(t.modes)
                cmb.setCurrentIndex(t.mode_index)
                cmb.currentIndexChanged.connect(lambda idx, tool_obj=t: self._change_mode(tool_obj, idx))
                mod_l.addWidget(cmb)
            else:
                dash = QLabel("—")
                dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
                dash.setStyleSheet("color: #64748b;")
                mod_l.addWidget(dash)
            self.table.setCellWidget(r_idx, 6, mod_w)

            # Sütun 7: ⚙️ Çark + AÇIK/KAPALI
            act_w = QWidget()
            act_w.setObjectName("cellBox")
            act_l = QHBoxLayout(act_w)
            act_l.setContentsMargins(4, 2, 4, 2)
            act_l.setSpacing(5)
            act_l.addStretch()
            if t.has_gear:
                g_btn = QPushButton("⚙️")
                g_btn.setFixedSize(34, 26)
                g_btn.setStyleSheet("padding: 0px; font-size: 13px;")
                g_btn.setToolTip(f"{t.name} Detaylı Ayarlar, Konum & AI'a Danış")
                g_btn.clicked.connect(lambda _=False, tool_obj=t: self.open_gear(tool_obj))
                act_l.addWidget(g_btn)

            t_btn = QPushButton(tr(self.lang, "state_on") if t.enabled else tr(self.lang, "state_off"))
            t_btn.setFixedWidth(66)
            if t.enabled:
                t_btn.setObjectName("primaryBtn")
            t_btn.clicked.connect(lambda _=False, tool_obj=t: self._toggle_tool(tool_obj))
            act_l.addWidget(t_btn)
            self.table.setCellWidget(r_idx, 7, act_w)

        active_k, saved_k = self._calculate_token_economy()
        self.token_summary_lbl.setText(tr(self.lang, "token_summary", act=active_k, sav=saved_k))
        self.table.resizeColumnToContents(6)
        self._update_bulk_client_buttons()
        self._update_panel_selection_ui()
        self.ai_header.sync_ai_bar_geometry()
        self.table._refresh_hover_from_cursor()

    def _get_panel_checked_set(self) -> set[str]:
        saved = self.meta.get("panel_checked_ids")
        if isinstance(saved, list):
            return {str(x) for x in saved}
        all_ids = [t.id for t in self.tools]
        self.meta["panel_checked_ids"] = all_ids
        return set(all_ids)

    def _on_panel_row_check_toggled(self, tool_id: str, checked: bool) -> None:
        cur = self._get_panel_checked_set()
        if checked:
            cur.add(tool_id)
        else:
            cur.discard(tool_id)
        self.meta["panel_checked_ids"] = [t.id for t in self.tools if t.id in cur]
        self._update_panel_selection_ui()
        self._save_state()

    def _set_panel_checks(self, mode: str) -> None:
        if mode == "all":
            target = {t.id for t in self.tools}
        elif mode == "enabled_only":
            target = {t.id for t in self.tools if t.enabled}
        else:
            target = set()
        self.meta["panel_checked_ids"] = [t.id for t in self.tools if t.id in target]
        for tid, cb in self.panel_row_checks.items():
            cb.blockSignals(True)
            cb.setChecked(tid in target)
            cb.blockSignals(False)
        self._update_panel_selection_ui()
        self._save_state()

    def _update_panel_selection_ui(self) -> None:
        cur = self._get_panel_checked_set()
        sel_cnt = sum(1 for t in self.tools if t.id in cur)
        tot_cnt = len(self.tools)
        self.lbl_panel_sel.setText(f"☑️ Seçili: {sel_cnt} / {tot_cnt} araç")
        self.btn_copy_tools_status.setText(f"📋 Seçili Araçların Genel Durumunu Kopyala ({sel_cnt})")
        self.ai_header.master_cb.blockSignals(True)
        self.ai_header.master_cb.setChecked(tot_cnt > 0 and sel_cnt == tot_cnt)
        self.ai_header.master_cb.blockSignals(False)

    def _copy_selected_tools_status(self) -> None:
        checked_set = self._get_panel_checked_set()
        selected_tools = [t for t in self.tools if t.id in checked_set]
        if not selected_tools:
            QMessageBox.information(
                self,
                "Araç Seçilmedi",
                "Genel durumu kopyalamak için lütfen Araç Paneli tablosundan en az bir aracı işaretleyin.",
            )
            return

        selected_tools.sort(key=self._tool_sort_value, reverse=self.sort_desc)
        active_k, saved_k = self._calculate_token_economy()
        en_cnt = sum(1 for t in selected_tools if t.enabled)
        now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        gpu_txt = self.vram_bar.text()

        lines = [
            f"=== AI Araç & Token Ekonomisi Genel Durum Raporu ({now_str}) ===",
            f"Seçili Araç: {len(selected_tools)} / {len(self.tools)} ({en_cnt} Açık, {len(selected_tools) - en_cnt} Kapalı)",
            f"Token Ekonomisi: Aktif Şema ~{active_k}K tok | Korunan Tasarruf +{saved_k}K tok | GPU: {gpu_txt}",
            "",
        ]

        for idx, t in enumerate(selected_tools, start=1):
            st_tag = "AÇIK" if t.enabled else "KAPALI"
            port_part = f" · Port :{t.port}" if t.port else ""
            lines.append(f"{idx}. [{st_tag}] {t.name} ({t.kind} · {t.version}{port_part})")

            scope_str = self._format_scope_display(t)
            loc_str = f" | {t.live_location_detail}" if t.live_location_detail else ""
            lines.append(f"   • Kapsam & Konum: {scope_str}{loc_str}")

            if t.id == "blender_skills":
                mode_str = f"{len(self.active_skills)} / {len(BLENDER_SKILLS_94)} Skill Açık"
            elif len(t.modes) > 1 and 0 <= t.mode_index < len(t.modes):
                mode_str = t.modes[t.mode_index]
            else:
                mode_str = "Standart"

            on_clients = [c for c, _ in AI_CLIENTS if t.clients.get(c, False)]
            clients_str = ", ".join(on_clients) if on_clients else "Hiçbiri (Tümü Kapalı)"
            lines.append(f"   • Son Yanıt: {t.last_ping} | Çalışma Modu: {mode_str} | Açık AI İstemcileri: {clients_str}")

            if t.id == "blender_skills" and self.active_skills:
                lines.append(f"   • Aktif Blender Skill'ler ({len(self.active_skills)}): {', '.join(sorted(self.active_skills))}")

            if t.options:
                on_opts = [o.label for o in t.options if o.enabled]
                if on_opts:
                    lines.append(f"   • Aktif Seçenekler: {', '.join(on_opts)}")

            if t.vault_key_name:
                has_k = bool(self.vault.get_secret(t.vault_key_name))
                lines.append(f"   • API Anahtarı ({t.vault_key_name}): {'Şifreli Kasada Kayıtlı ✓' if has_k else 'Girilmemiş'}")

        report_txt = "\n".join(lines)
        QApplication.clipboard().setText(report_txt)
        self.set_status(f"📋 Seçili {len(selected_tools)} aracın genel durum raporu panoya kopyalandı!")

        self.btn_copy_tools_status.setText(f"✓ Panoya Kopyalandı! ({len(selected_tools)} Araç)")
        self.btn_copy_tools_status.setObjectName("successBtn")
        self.style().unpolish(self.btn_copy_tools_status)
        self.style().polish(self.btn_copy_tools_status)

        def _restore_copy_btn() -> None:
            self.btn_copy_tools_status.setObjectName("primaryBtn")
            self._update_panel_selection_ui()
            self.style().unpolish(self.btn_copy_tools_status)
            self.style().polish(self.btn_copy_tools_status)

        QTimer.singleShot(1800, _restore_copy_btn)

    def _on_tool_scope_changed(self, tool: ToolSpec, new_scope: str) -> None:
        if new_scope == "__ADD_NEW__":
            self._prompt_add_project_folder(assign_tool=tool)
            return
        tool.project_scope = new_scope
        if new_scope != "GLOBAL" and new_scope in self.projects_map:
            proj_dir = self.projects_map[new_scope]
            if tool.id == "unity_pipeline":
                tool.param_value = proj_dir
            elif tool.id == "renderdoc_mcp":
                tool.param_value = proj_dir
        self._save_state()
        live_map = scan_live_process_locations()
        _, _, _, _, loc_det = probe_tool_health(tool, len(self.active_skills), self.projects_map, live_map)
        tool.live_location_detail = loc_det
        self.logs.add("INFO", tool.name, f"Proje kapsamı değiştirildi -> {self._format_scope_display(tool)}", loc_det)
        self.set_status(f"📁 {tool.name} kapsamı güncellendi: {self._format_scope_display(tool)}")
        self._refresh_table()
        self._refresh_logs_tab()

    # --- SEKME 2: EKLENTİLER & EXPORT / IMPORT ---
    def _init_plugins_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        top = QHBoxLayout()
        btn_sel_all = QPushButton("Tümünü Seç")
        btn_sel_all.clicked.connect(lambda: self._set_all_plugin_checks(True))
        top.addWidget(btn_sel_all)

        btn_clr_all = QPushButton("Seçimi Temizle")
        btn_clr_all.clicked.connect(lambda: self._set_all_plugin_checks(False))
        top.addWidget(btn_clr_all)

        self.btn_plugins_check = QPushButton("🔍 Güncellemeleri Kontrol Et")
        self.btn_plugins_check.setObjectName("primaryBtn")
        self.btn_plugins_check.clicked.connect(lambda: self.run_plugin_update_check(manual=True))
        top.addWidget(self.btn_plugins_check)

        self.btn_plugins_update_all = QPushButton("⬆️ Mevcut Güncellemeleri Başlat (0)")
        self.btn_plugins_update_all.setObjectName("successBtn")
        self.btn_plugins_update_all.setEnabled(False)
        self.btn_plugins_update_all.clicked.connect(self._handle_start_available_updates)
        top.addWidget(self.btn_plugins_update_all)

        self.btn_plugins_install_sel = QPushButton("📦 Seçilenleri Kur / Güncelle")
        self.btn_plugins_install_sel.clicked.connect(self._handle_update_selected_plugins)
        top.addWidget(self.btn_plugins_install_sel)

        top.addStretch()

        btn_export = QPushButton("📤 Export")
        btn_export.setToolTip("Tüm açık/kapalı durumlarını, 94 skill seçimini, proje kapsamlarını, çark ve kutucuk seçimlerini dışa aktarır")
        btn_export.clicked.connect(self._export_settings)
        top.addWidget(btn_export)

        btn_import = QPushButton("📥 Import")
        btn_import.setToolTip("Dışa aktarılan ayar dosyasını tüm seçimlerinizle birlikte geri yükler")
        btn_import.clicked.connect(self._import_settings)
        top.addWidget(btn_import)
        lay.addLayout(top)

        # Güncelleme Durum Özeti Çubuğu (Pop-up açmadan temiz bilgi verir)
        banner = QFrame()
        banner.setObjectName("card")
        b_lay = QHBoxLayout(banner)
        b_lay.setContentsMargins(10, 6, 10, 6)
        self.plugins_banner_lbl = QLabel("🔍 Açılış güncelleme kontrolü yapılıyor...")
        self.plugins_banner_lbl.setStyleSheet("font-weight: 600;")
        b_lay.addWidget(self.plugins_banner_lbl, stretch=1)

        self.btn_jump_err_logs = QPushButton("🐛 Hata Logunu Gör")
        self.btn_jump_err_logs.setObjectName("warnBtn")
        self.btn_jump_err_logs.hide()
        self.btn_jump_err_logs.clicked.connect(self._jump_to_error_logs)
        b_lay.addWidget(self.btn_jump_err_logs)
        lay.addWidget(banner)

        self.update_prog = QProgressBar()
        self.update_prog.hide()
        lay.addWidget(self.update_prog)

        self.plugins_scroll = QScrollArea()
        self.plugins_scroll.setWidgetResizable(True)
        self.plugins_host = QWidget()
        self.plugins_lay = QVBoxLayout(self.plugins_host)
        self.plugins_scroll.setWidget(self.plugins_host)
        lay.addWidget(self.plugins_scroll, stretch=1)

        self.tabs.addTab(tab, "🧩 Eklentiler")

    def _set_all_plugin_checks(self, state: bool) -> None:
        for cb in self.plugin_checks.values():
            cb.blockSignals(True)
            cb.setChecked(state)
            cb.blockSignals(False)
        self._sync_plugin_checks_to_meta()
        self._save_state()

    def _sync_plugin_checks_to_meta(self) -> None:
        self.meta["plugin_checked_ids"] = [tid for tid, cb in self.plugin_checks.items() if cb.isChecked()]

    def _on_single_plugin_check_changed(self) -> None:
        self._sync_plugin_checks_to_meta()
        self._save_state()

    def _refresh_plugins_tab(self) -> None:
        saved_checked_list = self.meta.get("plugin_checked_ids")
        if isinstance(saved_checked_list, list):
            checked_set = set(saved_checked_list)
        else:
            checked_set = {t.id for t in self.tools if t.enabled}

        self.plugin_checks.clear()
        while self.plugins_lay.count():
            item = self.plugins_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        upd_count = sum(1 for t in self.tools if t.has_update)
        self.btn_plugins_update_all.setText(f"⬆️ Mevcut Güncellemeleri Başlat ({upd_count})")
        self.btn_plugins_update_all.setEnabled(upd_count > 0 and not self.updating_busy)

        for t in self.tools:
            card = QFrame()
            card.setObjectName("card")
            row = QHBoxLayout(card)

            cb = QCheckBox()
            cb.setChecked(t.id in checked_set)
            cb.toggled.connect(lambda _checked: self._on_single_plugin_check_changed())
            self.plugin_checks[t.id] = cb
            row.addWidget(cb)

            cur_v = t.version.strip().lstrip("vV")
            lat_v = (t.latest_version or t.version).strip().lstrip("vV")

            if t.has_update:
                ver_html = (
                    f"<span style='color:#f59e0b; font-weight:700;'>🔔 Güncelleme Mevcut:  {cur_v}v &gt; {lat_v}v</span>"
                )
            else:
                ver_html = f"<span style='color:#22c55e; font-weight:600;'>✓ Güncel ({cur_v}v)</span>"

            info_col = QVBoxLayout()
            info_col.setSpacing(2)
            title_row = QHBoxLayout()
            title_row.setSpacing(6)
            title_row.addWidget(QLabel(f"<b>{t.name}</b>"))
            title_row.addWidget(self._make_info_btn(t))
            title_row.addWidget(QLabel(f"<span style='color:#94a3b8;'>({t.kind})</span>   {ver_html}"))
            title_row.addStretch()
            info_col.addLayout(title_row)
            if t.summary:
                desc_lbl = QLabel(t.summary)
                desc_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
                desc_lbl.setWordWrap(True)
                info_col.addWidget(desc_lbl)
            row.addLayout(info_col, stretch=1)

            if t.release_notes_url:
                notes_lbl = QLabel(f"<a style='color:#60a5fa;' href='{t.release_notes_url}'>📄 Sürüm Notları ↗</a>")
                notes_lbl.setOpenExternalLinks(True)
                notes_lbl.setToolTip(t.release_notes_url)
                row.addWidget(notes_lbl)

            if t.has_update:
                upd_one = QPushButton(f"⬆️ Güncelle ({cur_v}v > {lat_v}v)")
                upd_one.setObjectName("warnBtn")
            else:
                upd_one = QPushButton("🔄 Kur / Yenile")
            upd_one.clicked.connect(lambda _=False, tool_obj=t: self._run_batch_update([tool_obj], install_if_missing=True))
            row.addWidget(upd_one)

            copy_cmd = QPushButton("📋 Komut")
            copy_cmd.clicked.connect(
                lambda _=False, c=(t.install_cmd or t.repo_url), nm=t.name: (
                    QApplication.clipboard().setText(c),
                    self.set_status(f"{nm} kurulum komutu panoya kopyalandı: {c}"),
                )
            )
            row.addWidget(copy_cmd)
            self.plugins_lay.addWidget(card)
        self.plugins_lay.addStretch()

    # --- SEKME 3: ŞİFRELİ API KASASI (WINDOWS DPAPI) ---
    def _init_vault_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.addWidget(
            QLabel(
                "<b>🔐 Windows DPAPI Şifreli Anahtar Kasası</b> — Girilen anahtarlar açık metin olarak kaydedilmez; "
                "doğrudan Windows kullanıcı oturumunuzla (CryptProtectData) şifrelenir."
            )
        )
        self.vault_inputs: dict[str, QLineEdit] = {}
        for key_name, desc in WindowsDpapiVault.STANDARD_KEYS:
            card = QFrame()
            card.setObjectName("card")
            r = QHBoxLayout(card)
            lbl = QLabel(f"<b>{key_name}</b><br><span style='color:#94a3b8;'>{desc}</span>")
            lbl.setFixedWidth(360)
            r.addWidget(lbl)

            inp = QLineEdit()
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            inp.setPlaceholderText("Anahtarı yapıştırın (boş bırakıp kaydederseniz silinir)...")
            self.vault_inputs[key_name] = inp
            r.addWidget(inp, stretch=1)

            btn_save = QPushButton("💾 Şifrele & Kaydet")
            btn_save.setObjectName("primaryBtn")
            btn_save.clicked.connect(lambda _=False, k=key_name: self._save_vault_key(k))
            r.addWidget(btn_save)
            lay.addWidget(card)

        lay.addStretch()
        self.tabs.addTab(tab, "🔐 Şifreli Kasa")

    def _refresh_vault_tab(self) -> None:
        for k, inp in self.vault_inputs.items():
            existing = self.vault.get_secret(k)
            inp.setText(existing)

    def _save_vault_key(self, key_name: str) -> None:
        val = self.vault_inputs[key_name].text()
        self.vault.set_secret(key_name, val)
        self.logs.add("INFO", "Şifreli Kasa", f"{key_name} Windows DPAPI ile güncellendi.")
        self.set_status(f"🔐 {key_name} şifreli kasaya kaydedildi.")
        self._refresh_logs_tab()

    # --- SEKME 4: AKILLI GITHUB REPO EKLEME ---
    def _init_repo_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        bar = QHBoxLayout()
        self.repo_inp = QLineEdit("https://github.com/Linkingooo/renderdoc-mcp")
        self.repo_inp.setPlaceholderText("GitHub repo adresini yapıştırın (örn: https://github.com/owner/repo)...")
        bar.addWidget(self.repo_inp, stretch=1)

        self.btn_probe_repo = QPushButton("🔍 Sorgula & Tanı")
        self.btn_probe_repo.setObjectName("primaryBtn")
        self.btn_probe_repo.clicked.connect(self._handle_inspect_repo)
        bar.addWidget(self.btn_probe_repo)
        lay.addLayout(bar)

        quick = QHBoxLayout()
        quick.addWidget(QLabel("Hızlı Test:"))
        for sample in (
            "https://github.com/qybaihe/bla",
            "https://github.com/arjun988/blender-skills",
            "https://github.com/Linkingooo/renderdoc-mcp",
            "https://github.com/elevenlabs/elevenlabs-mcp",
        ):
            short = sample.split("github.com/")[1]
            b = QPushButton(short)
            b.clicked.connect(lambda _=False, u=sample: (self.repo_inp.setText(u), self._handle_inspect_repo()))
            quick.addWidget(b)
        quick.addStretch()
        lay.addLayout(quick)

        self.repo_result_box = QPlainTextEdit()
        self.repo_result_box.setReadOnly(True)
        self.repo_result_box.setPlaceholderText("GitHub bağlantısını sorguladığınızda algılanan kurulum yapısı burada görünecek...")
        lay.addWidget(self.repo_result_box, stretch=1)

        add_bar = QHBoxLayout()
        add_bar.addStretch()
        self.btn_add_repo = QPushButton("+ Kütüphaneye ve Ana Panele Ekle")
        self.btn_add_repo.setObjectName("successBtn")
        self.btn_add_repo.setEnabled(False)
        self.btn_add_repo.clicked.connect(self._handle_add_detected_repo)
        add_bar.addWidget(self.btn_add_repo)
        lay.addLayout(add_bar)

        self.tabs.addTab(tab, "📚 + Repo Ekle")

    # --- SEKME 5: KALICI SQLITE DEBUG & LOG + ZOMBIE PORT KURTARICI ---
    def _init_logs_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        top = QHBoxLayout()
        self.log_lvl_cmb = QComboBox()
        self.log_lvl_cmb.addItems(["ALL", "ERR", "WARN", "INFO", "DBG"])
        self.log_lvl_cmb.currentTextChanged.connect(self._refresh_logs_tab)
        top.addWidget(QLabel("Seviye:"))
        top.addWidget(self.log_lvl_cmb)

        self.log_search_inp = QLineEdit()
        self.log_search_inp.setPlaceholderText("Log geçmişinde ara...")
        self.log_search_inp.textChanged.connect(self._refresh_logs_tab)
        top.addWidget(self.log_search_inp, stretch=1)

        top.addWidget(QLabel("🔌 Asılı Portu Kapat:"))
        for port_num, lbl in [(8080, "8080 Unity"), (9876, "9876 Blender"), (9121, "9121 Serena"), (8790, "8790 Trellis")]:
            zb = QPushButton(f"🔌 {lbl}")
            zb.setToolTip(
                f"Logları silmez! Yalnızca {port_num} portu arkada asılı kalırsa o porttaki arka plan sürecini kapatır.\n"
                "(Logları temizlemek için aşağıdaki '🧹 Logları Temizle' butonunu kullanın.)"
            )
            zb.clicked.connect(lambda _=False, p=port_num: self._handle_kill_zombie_port(p))
            top.addWidget(zb)
        lay.addLayout(top)

        self.log_table = HoverTableWidget(0, 5, self)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.log_table.setHorizontalHeaderLabels(
            ["", "Zaman", "Seviye", "Araç", "Özet Teşhis (Ham çıktı için satıra tıklayın)"]
        )
        lh = self.log_table.horizontalHeader()
        lh.setMinimumHeight(32)
        lh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        lh.resizeSection(0, 38)
        self.log_table.setColumnWidth(0, 38)
        lh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.log_master_cb = QCheckBox(lh.viewport())
        self.log_master_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_master_cb.setGeometry(10, 7, 20, 18)
        self.log_master_cb.setToolTip("Listelenen tüm log satırlarını seç / seçimi kaldır")
        self.log_master_cb.clicked.connect(lambda checked: self._set_log_checks("all" if checked else "none"))

        self.log_table.itemSelectionChanged.connect(self._on_log_row_selected)
        lay.addWidget(self.log_table, stretch=1)

        # LOG SEÇİM & AI HATA ÇÖZÜM PROMPTU ÇUBUĞU
        log_act_bar = QHBoxLayout()
        log_act_bar.setContentsMargins(2, 2, 2, 2)

        self.lbl_log_sel = QLabel("☑️ Seçili Log: 0")
        self.lbl_log_sel.setStyleSheet("color: #94a3b8; font-weight: 600;")
        log_act_bar.addWidget(self.lbl_log_sel)

        btn_l_all = QPushButton("Tümünü Seç")
        btn_l_all.clicked.connect(lambda: self._set_log_checks("all"))
        log_act_bar.addWidget(btn_l_all)

        btn_l_err = QPushButton("🔴 Sadece Hata && Uyarıları Seç (ERR/WARN)")
        btn_l_err.setToolTip("Listedeki tüm kırmızı (ERR) ve sarı (WARN) kayıtları tek tıkla işaretler")
        btn_l_err.clicked.connect(lambda: self._set_log_checks("issues_only"))
        log_act_bar.addWidget(btn_l_err)

        btn_l_clr = QPushButton("Seçimi Temizle")
        btn_l_clr.clicked.connect(lambda: self._set_log_checks("none"))
        log_act_bar.addWidget(btn_l_clr)

        btn_l_wipe = QPushButton("🧹 Logları Temizle")
        btn_l_wipe.setToolTip("Eski / çözülmüş tüm log kayıtlarını veritabanından temizler")
        btn_l_wipe.clicked.connect(self._clear_all_logs)
        log_act_bar.addWidget(btn_l_wipe)

        log_act_bar.addStretch()

        self.btn_copy_logs_ai = QPushButton("🤖 Seçili Loglar İçin Hazır AI Çözüm Promptu Kopyala (0)")
        self.btn_copy_logs_ai.setObjectName("primaryBtn")
        self.btn_copy_logs_ai.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_logs_ai.setToolTip(
            "Seçtiğiniz hata/debug kayıtlarını, tam ham çıktıları (stderr/komut) ve araçların kurulu sürümlerini\n"
            "birleştirerek doğrudan AI'a yapıştırabileceğiniz hazır çözüm promptu üretir."
        )
        self.btn_copy_logs_ai.clicked.connect(self._copy_selected_logs_ai_prompt)
        log_act_bar.addWidget(self.btn_copy_logs_ai)
        lay.addLayout(log_act_bar)

        self.log_raw_view = QPlainTextEdit()
        self.log_raw_view.setReadOnly(True)
        self.log_raw_view.setFixedHeight(125)
        self.log_raw_view.setPlaceholderText(
            "Bir log satırına tıkladığınızda ham teknik çıktı (stderr / port / detay) veya üretilen hazır AI çözüm promptu burada görüntülenir."
        )
        lay.addWidget(self.log_raw_view)

        self.tabs.addTab(tab, "🐛 Debug && Log")

    def _refresh_logs_tab(self) -> None:
        lvl = self.log_lvl_cmb.currentText()
        q = self.log_search_inp.text()
        self._current_logs = self.logs.query(level=lvl, search=q)
        self.log_row_checks.clear()
        self.log_table.setRowCount(0)
        self.log_table.setRowCount(len(self._current_logs))
        for i, row in enumerate(self._current_logs):
            self.log_table.setRowHeight(i, 32)
            log_id = int(row["id"])

            cb_w = QWidget()
            cb_w.setObjectName("cellBox")
            cb_l = QHBoxLayout(cb_w)
            cb_l.setContentsMargins(10, 0, 4, 0)
            l_cb = QCheckBox()
            l_cb.setCursor(Qt.CursorShape.PointingHandCursor)
            l_cb.setChecked(log_id in self.checked_log_ids)
            l_cb.toggled.connect(lambda checked, lid=log_id: self._on_single_log_check_toggled(lid, checked))
            self.log_row_checks[log_id] = l_cb
            cb_l.addWidget(l_cb)
            self.log_table.setCellWidget(i, 0, cb_w)

            for col_i, key in enumerate(("ts", "level", "tool", "summary"), start=1):
                item = QTableWidgetItem(str(row[key]))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if key == "level":
                    if row["level"] == "ERR":
                        item.setForeground(QColor("#ef4444"))
                    elif row["level"] == "WARN":
                        item.setForeground(QColor("#f59e0b"))
                self.log_table.setItem(i, col_i, item)
        counts = self.logs.counts_by_level()
        self.tabs.setTabText(4, f"🐛 Debug && Log (🔴{counts['ERR']} 🟡{counts['WARN']})")
        self._update_log_selection_ui()

    def _on_single_log_check_toggled(self, log_id: int, checked: bool) -> None:
        if checked:
            self.checked_log_ids.add(log_id)
        else:
            self.checked_log_ids.discard(log_id)
        self._update_log_selection_ui()

    def _set_log_checks(self, mode: str) -> None:
        if mode == "all":
            for row in self._current_logs:
                self.checked_log_ids.add(int(row["id"]))
        elif mode == "issues_only":
            self.checked_log_ids = {int(row["id"]) for row in self._current_logs if row["level"] in ("ERR", "WARN")}
        else:
            self.checked_log_ids.clear()

        for lid, cb in self.log_row_checks.items():
            cb.blockSignals(True)
            cb.setChecked(lid in self.checked_log_ids)
            cb.blockSignals(False)
        self._update_log_selection_ui()

    def _update_log_selection_ui(self) -> None:
        sel_cnt = len(self.checked_log_ids)
        self.lbl_log_sel.setText(f"☑️ Seçili Log: {sel_cnt}")
        self.btn_copy_logs_ai.setText(f"🤖 Seçili Loglar İçin Hazır AI Çözüm Promptu Kopyala ({sel_cnt})")
        vis_ids = {int(r["id"]) for r in self._current_logs}
        all_vis_checked = bool(vis_ids) and vis_ids.issubset(self.checked_log_ids)
        self.log_master_cb.blockSignals(True)
        self.log_master_cb.setChecked(all_vis_checked)
        self.log_master_cb.blockSignals(False)

    def _copy_selected_logs_ai_prompt(self) -> None:
        if not self.checked_log_ids:
            # Kutucuk işaretlenmemiş ama bir satıra tıklanmışsa o satırı otomatik dahil et
            idxs = self.log_table.selectionModel().selectedRows()
            if idxs:
                r = idxs[0].row()
                if 0 <= r < len(self._current_logs):
                    lid = int(self._current_logs[r]["id"])
                    self.checked_log_ids.add(lid)
                    if lid in self.log_row_checks:
                        self.log_row_checks[lid].setChecked(True)

        if not self.checked_log_ids:
            QMessageBox.information(
                self,
                "Log Seçilmedi",
                "AI çözüm promptu oluşturmak için lütfen en az bir log satırını solundaki kutucuktan işaretleyin\n"
                "(veya '🔴 Sadece Hata & Uyarıları Seç' butonuna tıklayın).",
            )
            return

        all_recent = self.logs.query(limit=500)
        selected_entries = [e for e in all_recent if int(e["id"]) in self.checked_log_ids]
        selected_entries.sort(key=lambda x: int(x["id"]))  # Kronolojik sıra (eskiden yeniye)

        prompt = build_logs_ai_prompt(
            selected_entries,
            self.tools,
            get_current_app_version(),
            self.vram_bar.text(),
        )
        QApplication.clipboard().setText(prompt)
        self.log_raw_view.setPlainText(prompt)
        self.set_status(
            f"🤖 {len(selected_entries)} log kaydı ve araç sürümleri hazır AI çözüm promptu olarak panoya kopyalandı!"
        )

        self.btn_copy_logs_ai.setText(f"✓ AI Çözüm Promptu Kopyalandı! ({len(selected_entries)} Log)")
        self.btn_copy_logs_ai.setObjectName("successBtn")
        self.style().unpolish(self.btn_copy_logs_ai)
        self.style().polish(self.btn_copy_logs_ai)

        def _restore_log_btn() -> None:
            self.btn_copy_logs_ai.setObjectName("primaryBtn")
            self._update_log_selection_ui()
            self.style().unpolish(self.btn_copy_logs_ai)
            self.style().polish(self.btn_copy_logs_ai)

        QTimer.singleShot(1800, _restore_log_btn)

    def _clear_all_logs(self) -> None:
        self.logs.clear()
        self.checked_log_ids.clear()
        now_m = time.monotonic()
        for t in self.tools:
            self._last_warn_time[t.id] = now_m
        self._refresh_logs_tab()
        self.log_raw_view.clear()
        self.set_status("🧹 Tüm log kayıtları kalıcı olarak temizlendi.")

    def _on_log_row_selected(self) -> None:
        idxs = self.log_table.selectionModel().selectedRows()
        if not idxs:
            return
        r = idxs[0].row()
        if 0 <= r < len(self._current_logs):
            entry = self._current_logs[r]
            self.log_raw_view.setPlainText(f"[{entry['ts']}] [{entry['level']}] {entry['tool']}\n{entry['raw_detail']}")

    # --- SİSTEM TEPSİSİ (TRAY) ---
    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(create_app_icon(), self)
        self.tray.setToolTip("AI Araç & Token Ekonomisi Kontrol Merkezi")
        menu = QMenu()

        act_open = QAction("🖥️ Kontrol Merkezini Aç", self)
        act_open.triggered.connect(self._restore_from_tray)
        menu.addAction(act_open)
        menu.addSeparator()

        for p_key, p_info in PROFILES.items():
            act_p = QAction(p_info["title"], self)
            act_p.triggered.connect(lambda _=False, k=p_key: self.apply_profile(k))
            menu.addAction(act_p)

        menu.addSeparator()
        act_app_upd = QAction("🔄 Program Güncellemesini Kontrol Et", self)
        act_app_upd.triggered.connect(lambda: (self._restore_from_tray(), self._handle_quick_check_app_update()))
        menu.addAction(act_app_upd)

        act_upd_all = QAction("🔍 Eklenti Güncellemelerini Kontrol Et", self)
        act_upd_all.triggered.connect(lambda: self.run_plugin_update_check(manual=True))
        menu.addAction(act_upd_all)

        act_vram = QAction("🧹 Trellis GPU VRAM Boşalt", self)
        act_vram.triggered.connect(self._handle_free_vram)
        menu.addAction(act_vram)

        menu.addSeparator()
        act_quit = QAction("❌ Tamamen Çık", self)
        act_quit.triggered.connect(self._quit_app)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.show()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _quit_app(self) -> None:
        self.force_quit = True
        self._save_state()
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._save_state()
        if not self.force_quit and self.tray and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self.tray_notified:
                self.tray.showMessage(
                    "AI Araç Merkezi Arka Planda",
                    "Sağ alt sistem tepsisinden tek tıkla profil değiştirebilir veya tüm MCP'leri uyutabilirsiniz.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
                self.tray_notified = True
            return
        self.table.detach_filter()
        self.log_table.detach_filter()
        super().closeEvent(event)

    # --- AKSİYONLAR & İŞ MANTIĞI ---
    def set_status(self, msg: str) -> None:
        self.status_lbl.setText(msg)

    def _save_state(self) -> None:
        self.meta["sort_key"] = self.sort_key
        self.meta["sort_desc"] = self.sort_desc
        if self.plugin_checks:
            self.meta["plugin_checked_ids"] = [tid for tid, cb in self.plugin_checks.items() if cb.isChecked()]
        self.store.save(self.tools, self.active_skills, self.meta, self.default_ids)

    def _toggle_theme(self) -> None:
        nxt = "light" if self.meta.get("theme", "dark") == "dark" else "dark"
        self._apply_theme(nxt)
        self._refresh_table()
        self._refresh_plugins_tab()
        self._save_state()

    def _on_language_changed(self) -> None:
        code = str(self.lang_cmb.currentData() or "en")
        if code == self.lang:
            return
        self.lang = code
        self.meta["lang"] = code
        self._save_state()
        self._retranslate_ui()
        self._rebuild_project_filter_combo()
        self._rebuild_custom_presets_combo()
        self._refresh_table()
        self._refresh_logs_tab()
        lang_lbl = dict(SUPPORTED_LANGUAGES).get(code, code)
        self.set_status(tr(self.lang, "lang_changed", lang=lang_lbl))

    def _retranslate_ui(self) -> None:
        app_ver = get_current_app_version()
        self.setWindowTitle(tr(self.lang, "app_title", ver=app_ver))
        self.lbl_preset.setText(tr(self.lang, "preset_lbl"))
        self.auto_detect_cb.setText(tr(self.lang, "auto_detect"))
        self.btn_vram_free.setText(tr(self.lang, "vram_free"))
        self.btn_refresh.setText(tr(self.lang, "scan_now"))
        self.btn_test_conns.setText(tr(self.lang, "test_conns"))
        if not (self.latest_app_check and self.latest_app_check.has_update):
            self.btn_app_update_top.setText(tr(self.lang, "app_update"))
        self.btn_sync.setText(tr(self.lang, "sync_configs"))
        self.btn_theme.setText(tr(self.lang, "theme"))

        self.search_inp.setPlaceholderText(tr(self.lang, "search_ph"))
        if self.kind_cmb.count() > 0:
            self.kind_cmb.setItemText(0, tr(self.lang, "all_types"))
        self.lbl_proj_flt.setText(tr(self.lang, "project_lbl"))
        self.btn_add_proj.setText(tr(self.lang, "add_project"))
        self.lbl_saved_presets.setText(tr(self.lang, "saved_presets_lbl"))
        self.btn_save_preset.setText(tr(self.lang, "save_btn"))
        self.btn_do_app_upd.setText(tr(self.lang, "ver_btn", ver=app_ver))

        self.tabs.setTabText(0, tr(self.lang, "tab_panel", n=len(self.tools)))
        if not any(t.has_update for t in self.tools):
            self.tabs.setTabText(1, tr(self.lang, "tab_plugins"))
        self.tabs.setTabText(2, tr(self.lang, "tab_vault"))
        self.tabs.setTabText(3, tr(self.lang, "tab_repo"))
        self._update_panel_header_indicators()

    def _apply_theme(self, mode: str) -> None:
        self.meta["theme"] = mode
        self.setStyleSheet(LIGHT_QSS if mode == "light" else DARK_QSS)
        if hasattr(self, "bulk_client_btns"):
            self._update_bulk_client_buttons()
        if hasattr(self, "profile_btns"):
            self._update_profile_buttons_ui()

    def _on_auto_detect_toggled(self, checked: bool) -> None:
        self.meta["auto_detect_apps"] = checked
        self._save_state()

    def _sync_live_environment_async(self, target_tools: list[ToolSpec] | None = None) -> None:
        """Tablodaki AÇIK/KAPALI ve AI istemci seçimlerini anında gerçek süreçlere ve AI config dosyalarına uygular."""
        if not self.sync_live_environment:
            return
        tools_snap = list(self.tools)
        targets = list(target_tools) if target_tools is not None else tools_snap
        skills_snap = set(self.active_skills)
        proj_snap = dict(self.projects_map)

        def worker() -> None:
            for t_obj in targets:
                enforce_tool_runtime_state(t_obj, proj_snap)
            bs_tool = next((x for x in tools_snap if x.id == "blender_skills"), None)
            if bs_tool:
                sync_blender_skills_on_disk(skills_snap, bs_tool.enabled, bs_tool.project_scope, proj_snap)
            sync_mcp_json_clients(tools_snap, self.vault, proj_snap)
            live_map = scan_live_process_locations()
            self._latest_live_map = live_map
            out = []
            for x in tools_snap:
                ok, ping_str, ms, detail, loc_detail = probe_tool_health(x, len(skills_snap), proj_snap, live_map)
                out.append((x.id, ok, ping_str, ms, detail, loc_detail))
            self.bridge.health_done.emit(out, True)

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_tool(self, tool: ToolSpec) -> None:
        tool.enabled = not tool.enabled
        self._save_state()
        self.logs.add("DBG", tool.name, f"Durum değiştirildi: {'AÇIK' if tool.enabled else 'KAPALI'}")
        self.set_status(f"{tool.name} {'açıldı ve AI yapılandırmasına işlendi' if tool.enabled else 'kapatıldı ve AI yapılandırmasından çıkarıldı'}.")
        self._refresh_table()
        self._refresh_logs_tab()
        self._sync_live_environment_async(target_tools=[tool])

    def _toggle_client(self, tool: ToolSpec, client_code: str, checked: bool) -> None:
        tool.clients[client_code] = checked
        self._save_state()
        self.set_status(f"{tool.name} -> {client_code} hedefi {'aktif edildi' if checked else 'kapatıldı'} (config güncellendi).")
        self._refresh_table()
        self._sync_live_environment_async(target_tools=[])

    def _update_bulk_client_buttons(self) -> None:
        total = len(self.tools)
        is_light = self.meta.get("theme", "dark") == "light"
        for code, full_lbl in AI_CLIENTS:
            btn = self.bulk_client_btns.get(code)
            if not btn:
                continue
            on_cnt = sum(1 for t in self.tools if t.clients.get(code, False))
            btn.setText(code)
            if total > 0 and on_cnt == total:
                btn.setStyleSheet(
                    "background-color: #2563eb; color: #ffffff; border: 1px solid #93c5fd; "
                    "border-radius: 4px; font-size: 10px; font-weight: 700; padding: 1px 0px;"
                )
            elif on_cnt > 0:
                btn.setStyleSheet(
                    "background-color: #dbeafe; color: #1d4ed8; border: 1px dashed #2563eb; "
                    "border-radius: 4px; font-size: 10px; font-weight: 700; padding: 1px 0px;"
                    if is_light
                    else "background-color: #1e3a8a; color: #bfdbfe; border: 1px dashed #60a5fa; "
                    "border-radius: 4px; font-size: 10px; font-weight: 700; padding: 1px 0px;"
                )
            else:
                btn.setStyleSheet(
                    "background-color: #e2e8f0; color: #64748b; border: 1px solid #cbd5e1; "
                    "border-radius: 4px; font-size: 10px; font-weight: 600; padding: 1px 0px;"
                    if is_light
                    else "background-color: #111823; color: #64748b; border: 1px solid #2e3d54; "
                    "border-radius: 4px; font-size: 10px; font-weight: 600; padding: 1px 0px;"
                )
            btn.setToolTip(
                f"🤖 {full_lbl} ({code}): {on_cnt}/{total} araçta açık\n"
                f"• Sol tık: Tüm sütunu tek tıkla {'KAPAT' if on_cnt > 0 else 'AÇ'}\n"
                "• Sağ tık: Sadece açık araçlarda aç / Tümünde aç / Tümünde kapat"
            )

    def _toggle_client_all(self, client_code: str, mode: str = "auto") -> None:
        if mode == "auto":
            any_on = any(t.clients.get(client_code, False) for t in self.tools)
            target_state = not any_on
            for t in self.tools:
                t.clients[client_code] = target_state
            action_desc = "tüm araçlarda AÇILDI" if target_state else "tüm araçlarda komple KAPATILDI"
        elif mode == "all_on":
            for t in self.tools:
                t.clients[client_code] = True
            action_desc = "tüm araçlarda AÇILDI"
        elif mode == "active_only":
            for t in self.tools:
                t.clients[client_code] = bool(t.enabled)
            action_desc = "sadece AÇIK araçlarda aktif edildi"
        else:
            for t in self.tools:
                t.clients[client_code] = False
            action_desc = "tüm araçlarda komple KAPATILDI"

        self._save_state()
        self.logs.add("INFO", f"Toplu AI ({client_code})", f"{client_code} {action_desc}.")
        self.set_status(f"🤖 {client_code} {action_desc} (config dosyaları güncellendi).")
        self._refresh_table()
        self._refresh_logs_tab()
        self._sync_live_environment_async(target_tools=[])

    def _show_bulk_client_menu(self, client_code: str, btn: QPushButton, pos: Any) -> None:
        menu = QMenu(self)
        act_all_on = QAction(f"✓ {client_code} — Tüm Araçlarda Aç", self)
        act_act_on = QAction(f"⚡ {client_code} — Sadece Açık Araçlarda Aç", self)
        act_all_off = QAction(f"✕ {client_code} — Tüm Araçlarda Komple Kapat", self)
        act_all_on.triggered.connect(lambda: self._toggle_client_all(client_code, "all_on"))
        act_act_on.triggered.connect(lambda: self._toggle_client_all(client_code, "active_only"))
        act_all_off.triggered.connect(lambda: self._toggle_client_all(client_code, "all_off"))
        menu.addAction(act_all_on)
        menu.addAction(act_act_on)
        menu.addAction(act_all_off)
        menu.exec(btn.mapToGlobal(pos))

    def _change_mode(self, tool: ToolSpec, idx: int) -> None:
        tool.mode_index = idx
        self._save_state()
        self.set_status(f"{tool.name} çalışma modu '{tool.modes[idx]}' olarak seçildi.")

    def _get_active_profiles_set(self) -> set[str]:
        raw = self.meta.get("active_profiles")
        if isinstance(raw, list):
            return {str(k) for k in raw if str(k) in PROFILES}
        return set()

    def _update_profile_buttons_ui(self) -> None:
        active_set = self._get_active_profiles_set()
        for p_key, btn in self.profile_btns.items():
            base_lbl = PROFILES[p_key]["title"].replace("&", "&&")
            if p_key in active_set:
                btn.setText(f"✓ {base_lbl}")
                btn.setStyleSheet(
                    "QPushButton { background-color: #2563eb; color: #ffffff; border: 1.5px solid #93c5fd; "
                    "border-radius: 5px; padding: 5px 10px; font-weight: 700; }"
                    "QPushButton:hover { background-color: #1d4ed8; }"
                )
            else:
                btn.setText(base_lbl)
                btn.setStyleSheet("")

    def apply_profile(self, profile_key: str, ask_confirm: bool = True) -> None:
        prof = PROFILES[profile_key]
        active_set = self._get_active_profiles_set()
        is_currently_selected = profile_key in active_set

        if is_currently_selected:
            next_set = active_set - {profile_key}
            action_phrase = f"'{prof['title']}' hazır ayar seçimini kaldırmak"
        else:
            if profile_key == "zero_token":
                next_set = {"zero_token"}
            else:
                next_set = (active_set - {"zero_token"}) | {profile_key}
            action_phrase = f"'{prof['title']}' hazır ayarını etkinleştirmek"

        if ask_confirm:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("⚠️ Mevcut Ayarlarınız Değişecektir")
            msg_box.setText("<b>Şu anki araç ayarlarınız değişecektir!</b>")
            msg_box.setInformativeText(
                f"{action_phrase} üzeresiniz.\n"
                "Tablodaki açık/kapalı araç düzeniniz seçili hazır ayarlara göre güncellenecektir.\n\n"
                "Değiştirmeden önce şu anki ayarlarınızı dışa aktarıp kaydetmek ister misiniz?"
            )
            btn_save_go = msg_box.addButton("💾 Mevcut Ayarları Kaydet ve Uygula", QMessageBox.ButtonRole.AcceptRole)
            btn_just_go = msg_box.addButton("⚡ Kaydetmeden Değiştir", QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = msg_box.addButton("İptal", QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(btn_save_go)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked == btn_cancel or clicked is None:
                self._update_profile_buttons_ui()
                return
            if clicked == btn_save_go:
                save_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Mevcut Ayarları Kaydet (Export)",
                    "ai_arac_yedek_ayarlar.json",
                    "Ayar Dosyası (*.json *.aihub)",
                )
                if not save_path:
                    self._update_profile_buttons_ui()
                    return
                self.export_to_file(pathlib.Path(save_path))

        ordered_active = [k for k in PROFILES if k in next_set]
        self.meta["active_profiles"] = ordered_active

        combined_enable: set[str] = set()
        for k in ordered_active:
            combined_enable |= set(PROFILES[k]["enable"])

        for t in self.tools:
            t.enabled = t.id in combined_enable

        self._update_profile_buttons_ui()
        self._save_state()

        if ordered_active:
            titles = " + ".join(PROFILES[k]["title"] for k in ordered_active)
            summary_msg = f"🎯 Aktif hazır ayarlar: {titles} ({sum(1 for t in self.tools if t.enabled)} araç açık)"
        else:
            summary_msg = f"🎯 '{prof['title']}' seçimi kaldırıldı (aktif hazır ayar kalmadı, araçlar kapatıldı)."

        self.logs.add("INFO", "Hazır Ayar", summary_msg)
        self.set_status(summary_msg)
        self._refresh_table()
        self._refresh_logs_tab()
        self._sync_live_environment_async(target_tools=list(self.tools))

    def _get_custom_presets(self) -> dict[str, dict[str, Any]]:
        raw = self.meta.get("custom_presets")
        if not isinstance(raw, dict):
            raw = {}
            self.meta["custom_presets"] = raw
        return raw

    def _rebuild_custom_presets_combo(self, selected_name: str = "") -> None:
        if not hasattr(self, "saved_presets_cmb"):
            return
        presets = self._get_custom_presets()
        self.saved_presets_cmb.blockSignals(True)
        self.saved_presets_cmb.clear()
        self.saved_presets_cmb.addItem(f"— Kayıtlı Ayar Seç ({len(presets)}) —", "")
        # En son kaydedilenler üstte görünsün
        ordered = sorted(
            presets.items(),
            key=lambda kv: str(kv[1].get("saved_at", "")),
            reverse=True,
        )
        for p_name, p_data in ordered:
            en_cnt = int(p_data.get("enabled_count", 0))
            saved_at = str(p_data.get("saved_at", ""))
            short_dt = saved_at[5:16] if len(saved_at) >= 16 else saved_at
            lbl = f"📁 {p_name} ({en_cnt} açık · {short_dt})" if short_dt else f"📁 {p_name} ({en_cnt} açık)"
            self.saved_presets_cmb.addItem(lbl, p_name)

        idx = self.saved_presets_cmb.findData(selected_name) if selected_name else 0
        self.saved_presets_cmb.setCurrentIndex(max(0, idx))
        self.saved_presets_cmb.blockSignals(False)
        if hasattr(self, "btn_del_preset"):
            self.btn_del_preset.setEnabled(self.saved_presets_cmb.currentIndex() > 0)

    def _save_custom_preset(self) -> None:
        cur_sel = str(self.saved_presets_cmb.currentData() or "")
        default_name = cur_sel or (next(iter(self.projects_map.keys()), "") or "Özel Ayarım")
        name, ok = QInputDialog.getText(
            self,
            "💾 Ayar Düzenini Kaydet",
            "Bu araç/proje yapılandırmasını hangi isimle kaydetmek istersiniz?\n"
            "(Açık/kapalı araçlar, AI seçimleri, proje kapsamları ve çalışma modları saklanır)",
            text=default_name,
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Geçersiz İsim", "Lütfen boş olmayan bir kayıt adı girin.")
            return

        presets = self._get_custom_presets()
        if name in presets and name != cur_sel:
            ans = QMessageBox.question(
                self,
                "Aynı İsimde Kayıt Var",
                f"'{name}' adında bir kaydınız zaten bulunuyor. Üzerine yazmak ister misiniz?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        presets[name] = {
            "name": name,
            "saved_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "enabled_count": sum(1 for t in self.tools if t.enabled),
            "active_blender_skills": sorted(self.active_skills),
            "tools": {
                t.id: {
                    "enabled": bool(t.enabled),
                    "clients": dict(t.clients),
                    "project_scope": t.project_scope,
                    "mode_index": int(t.mode_index),
                    "param_value": t.param_value,
                    "options": {o.key: bool(o.enabled) for o in t.options},
                }
                for t in self.tools
            },
        }
        self._save_state()
        self._rebuild_custom_presets_combo(selected_name=name)
        self.logs.add("INFO", "Kayıtlı Ayarlar", f"'{name}' adıyla ayar düzeni kaydedildi ({presets[name]['enabled_count']} araç açık).")
        self.set_status(f"💾 '{name}' kaydı oluşturuldu — artık Kayıtlarım listesinden tek tıkla dönebilirsiniz.")
        self._refresh_logs_tab()

    def _on_custom_preset_selected(self, idx: int) -> None:
        if idx <= 0:
            if hasattr(self, "btn_del_preset"):
                self.btn_del_preset.setEnabled(False)
            return
        name = str(self.saved_presets_cmb.currentData() or "")
        if name:
            self.apply_custom_preset(name)

    def apply_custom_preset(self, name: str) -> None:
        presets = self._get_custom_presets()
        pdata = presets.get(name)
        if not isinstance(pdata, dict):
            return

        tools_snap = pdata.get("tools", {})
        if isinstance(tools_snap, dict):
            for t in self.tools:
                saved = tools_snap.get(t.id)
                if not isinstance(saved, dict):
                    continue
                if "enabled" in saved:
                    t.enabled = bool(saved["enabled"])
                if isinstance(saved.get("clients"), dict):
                    for k, v in saved["clients"].items():
                        if k in t.clients:
                            t.clients[k] = bool(v)
                if "project_scope" in saved and t.scope_selectable:
                    t.project_scope = str(saved["project_scope"])
                if "mode_index" in saved and t.modes:
                    t.mode_index = max(0, min(int(saved["mode_index"]), len(t.modes) - 1))
                if "param_value" in saved:
                    t.param_value = str(saved["param_value"])
                if isinstance(saved.get("options"), dict):
                    for o in t.options:
                        if o.key in saved["options"]:
                            o.enabled = bool(saved["options"][o.key])

        if isinstance(pdata.get("active_blender_skills"), list):
            self.active_skills = {str(s) for s in pdata["active_blender_skills"]}

        self.meta["active_profiles"] = []
        self._update_profile_buttons_ui()
        self._save_state()
        if hasattr(self, "btn_del_preset"):
            self.btn_del_preset.setEnabled(True)

        en_cnt = sum(1 for t in self.tools if t.enabled)
        self.logs.add("INFO", "Kayıtlı Ayarlar", f"'{name}' kaydı yüklendi ({en_cnt} araç açık).")
        self.set_status(f"💾 '{name}' kaydı uygulandı ({en_cnt} araç açık) — canlı config'ler güncelleniyor.")
        self._refresh_table()
        self._refresh_plugins_tab()
        self._refresh_logs_tab()
        self._sync_live_environment_async(target_tools=list(self.tools))

    def _delete_custom_preset(self) -> None:
        name = str(self.saved_presets_cmb.currentData() or "")
        if not name:
            return
        ans = QMessageBox.question(
            self,
            "Kaydı Sil",
            f"'{name}' adlı kayıtlı ayar düzenini silmek istediğinize emin misiniz?",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        presets = self._get_custom_presets()
        presets.pop(name, None)
        self._save_state()
        self._rebuild_custom_presets_combo()
        self.logs.add("INFO", "Kayıtlı Ayarlar", f"'{name}' kaydı silindi.")
        self.set_status(f"🗑️ '{name}' kaydı silindi.")
        self._refresh_logs_tab()

    def open_gear(self, tool: ToolSpec) -> None:
        if tool.gear_kind == "skills94":
            saved_chk = set(self.meta.get("checked_blender_skills", []))
            dlg = BlenderSkillsDialog(self, self.active_skills, saved_chk)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.saved_result is not None:
                self.active_skills = dlg.saved_result
                self.meta["checked_blender_skills"] = sorted(dlg.saved_checked)
                tool.enabled = len(self.active_skills) > 0
                ok, disk_msg = sync_blender_skills_on_disk(
                    self.active_skills,
                    tool.enabled,
                    tool.project_scope,
                    self.projects_map,
                )
                self._save_state()
                self.logs.add("INFO" if ok else "DBG", tool.name, f"94 skill seçimi kaydedildi ({len(self.active_skills)} açık).", disk_msg)
                self.set_status(f"Blender Skills kaydedildi: {len(self.active_skills)}/94 açık. {disk_msg}")
                self._refresh_table()
                self._refresh_logs_tab()
        else:
            dlg = ToolGearDialog(self, tool, self.vault, self.logs, self._format_scope_display(tool))
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._save_state()
                self.logs.add("INFO", tool.name, "Teknik çark ayarları kaydedildi.")
                self.set_status(f"⚙️ {tool.name} ayarları kaydedildi.")
                self._refresh_table()
                self._refresh_logs_tab()

    def _on_second_tick(self) -> None:
        self.seconds_left -= 1
        if self.seconds_left <= 0:
            self.run_health_scan()
        m, s = divmod(max(0, self.seconds_left), 60)
        self.timer_lbl.setText(f"{m:02d}:{s:02d}")

        # Her 3 saniyede bir sessiz canlı süreç/port izleyici: Blender veya Unity kapandığı/açıldığı an tabloyu otomatik günceller!
        if self.seconds_left > 0 and self.seconds_left % 3 == 0:
            self._run_silent_live_watch()

        if self.seconds_left % 10 == 0:
            self._update_vram_bar()
            if self.meta.get("auto_detect_apps", True):
                self._check_dcc_auto_switch()

    def _run_silent_live_watch(self) -> None:
        if self._live_watch_busy:
            return
        self._live_watch_busy = True
        snap_tools = list(self.tools)
        sk_cnt = len(self.active_skills)
        proj_snap = dict(self.projects_map)

        def worker() -> None:
            try:
                live_map = scan_live_process_locations()
                self._latest_live_map = live_map
                out = []
                for t in snap_tools:
                    ok, ping_str, ms, detail, loc_detail = probe_tool_health(t, sk_cnt, proj_snap, live_map)
                    out.append((t.id, ok, ping_str, ms, detail, loc_detail))
                self.bridge.health_done.emit(out, True)
            finally:
                self._live_watch_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _update_vram_bar(self) -> None:
        name, used_mb, total_mb = query_gpu_vram()
        if total_mb > 0:
            self.vram_bar.setMaximum(total_mb)
            self.vram_bar.setValue(used_mb)
            short_gpu = name.replace("NVIDIA GeForce ", "")
            self.vram_bar.setFormat(f"{short_gpu}: {used_mb / 1024:.1f} / {total_mb / 1024:.1f} GB")
        else:
            self.vram_bar.setMaximum(100)
            self.vram_bar.setValue(0)
            self.vram_bar.setFormat("VRAM: Yok")

    def _check_dcc_auto_switch(self) -> None:
        cur = detect_running_dcc_apps()
        if cur["unity"] and not self.last_detected_apps.get("unity"):
            self.set_status("👁️ Unity.exe algılandı — İsterseniz üstten '🎮 Unity & Shader' hazır ayarını seçebilirsiniz.")
        elif cur["blender"] and not self.last_detected_apps.get("blender"):
            self.set_status("👁️ blender.exe algılandı — İsterseniz üstten '🎨 3D & Korku Asset' hazır ayarını seçebilirsiniz.")
        self.last_detected_apps = cur

    def run_health_scan(self) -> None:
        self.seconds_left = 30
        self.set_status("Sağlık, port ve canlı süreç konumları taranıyor...")
        snap_tools = list(self.tools)
        sk_cnt = len(self.active_skills)
        proj_snap = dict(self.projects_map)

        def worker() -> None:
            live_map = scan_live_process_locations()
            self._latest_live_map = live_map
            out = []
            for t in snap_tools:
                ok, ping_str, ms, detail, loc_detail = probe_tool_health(t, sk_cnt, proj_snap, live_map)
                out.append((t.id, ok, ping_str, ms, detail, loc_detail))
            self.bridge.health_done.emit(out, False)

        threading.Thread(target=worker, daemon=True).start()

    def _on_health_results(self, results: list[tuple[str, bool, str, int, str, str]], silent: bool = False) -> None:
        by_id = {t.id: t for t in self.tools}
        state_changed = False

        def _ping_bucket(s: str) -> str:
            # Sadece saat/ms değişimini değil, gerçek durum değişimini (Çalışıyor <-> Kapalı <-> Devre Dışı) ayırt et
            if " (" in s and ":" in s[:6]:
                return "LIVE_OK"
            if s.startswith("Çalışıyor"):
                return "LIVE_OK"
            return s

        for tid, ok, ping_str, ms, detail, loc_detail in results:
            if tid in by_id:
                t = by_id[tid]
                old_bucket = _ping_bucket(t.last_ping)
                new_bucket = _ping_bucket(ping_str)
                if old_bucket != new_bucket or t.live_location_detail != loc_detail:
                    state_changed = True
                t.last_ping = ping_str
                t.last_latency_ms = ms
                t.live_location_detail = loc_detail
                if t.enabled and t.port and not ok and tid != "trellis":
                    now_mono = time.monotonic()
                    if tid in ("serena", "unity_mcp") and self.sync_live_environment:
                        if now_mono - self._auto_heal_cooldown.get(tid, 0.0) > 45.0:
                            self._auto_heal_cooldown[tid] = now_mono
                            self._auto_heal_tool_async(t)
                            continue
                    if not silent and now_mono - self._last_warn_time.get(tid, 0.0) > 300.0:
                        self._last_warn_time[tid] = now_mono
                        self.logs.add("WARN", t.name, f"Açık işaretli servis yanıt vermedi ({ping_str})", detail, t.port)

        if silent:
            if QApplication.activePopupWidget() is None:
                self._refresh_host_dep_banner()
                if state_changed:
                    self._refresh_table()
            return

        self._refresh_table()
        self._refresh_host_dep_banner()
        self._refresh_logs_tab()
        self._update_vram_bar()
        self.set_status("Canlı süreç, port ve konum taraması tamamlandı (3 sn'de bir anlık izleniyor).")

    def _refresh_host_dep_banner(self) -> None:
        if not hasattr(self, "host_dep_banner"):
            return
        missing = get_missing_host_dependencies(self.tools, self._latest_live_map, self.projects_map)
        while self.host_dep_btns_lay.count():
            item = self.host_dep_btns_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not missing:
            self.host_dep_banner.hide()
            return

        titles = "  |  ".join(m["title"] for m in missing)
        self.host_dep_lbl.setText(f"⚠️ <b>Bağımlı Program Kapalı:</b> {titles} — Tek tıkla başlatabilirsiniz:")
        for m in missing:
            btn = QPushButton(m["btn_label"])
            btn.setObjectName("warnBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(m["detail"])
            btn.clicked.connect(lambda _=False, info=m: self._handle_launch_host_app(info))
            self.host_dep_btns_lay.addWidget(btn)
        self.host_dep_banner.show()

    def _handle_launch_host_app(self, dep_info: dict[str, Any]) -> None:
        tr = next((t for t in self.tools if t.id == "trellis"), None)
        ok, msg = launch_host_app_for_tool(
            host_kind=str(dep_info.get("host", "")),
            projects_map=self.projects_map,
            target_scope=str(dep_info.get("scope", "GLOBAL")),
            headless=bool(dep_info.get("headless", True)),
            trellis_root=tr.param_value if tr else "",
        )
        self.logs.add("INFO" if ok else "WARN", "Bağımlı Program", msg)
        self.set_status(f"🚀 {msg}" if ok else f"⚠️ {msg}")
        self._refresh_logs_tab()
        QTimer.singleShot(2500, self.run_health_scan)

    def _auto_heal_tool_async(self, tool: ToolSpec) -> None:
        """AÇIK işaretli arka plan servisleri (Serena :9121, Unity MCP :8080) kapandıysa kullanıcıya sormadan otomatik başlatır."""
        proj_snap = dict(self.projects_map)

        def worker() -> None:
            note = enforce_tool_runtime_state(tool, proj_snap)
            if note:
                self.logs.add("INFO", tool.name, f"Otomatik Kurtarma:{note}")
                time.sleep(1.5)
                live_map = scan_live_process_locations()
                ok, ping_str, ms, detail, loc_detail = probe_tool_health(
                    tool, len(self.active_skills), proj_snap, live_map
                )
                self.bridge.health_done.emit([(tool.id, ok, ping_str, ms, detail, loc_detail)], True)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_free_vram(self) -> None:
        ok, msg = free_trellis_vram()
        self.logs.add("INFO" if ok else "WARN", "Trellis Sunucu & CLI", msg)
        self._update_vram_bar()
        self._refresh_logs_tab()
        self.set_status(msg)

    def _handle_kill_zombie_port(self, port: int) -> None:
        ok, msg = kill_zombie_port_process(port)
        # Port zaten boşsa veya açık editör (Blender/Unity) tarafından kullanılıyorsa sarı WARN yerine INFO yaz
        self.logs.add("INFO", f"Port {port}", msg, msg, port)
        self._refresh_logs_tab()
        self.set_status(msg)
        QTimer.singleShot(500, self.run_health_scan)

    def _handle_sync_configs(self) -> None:
        bs_tool = next((t for t in self.tools if t.id == "blender_skills"), None)
        if bs_tool:
            sync_blender_skills_on_disk(self.active_skills, bs_tool.enabled, bs_tool.project_scope, self.projects_map)
        msgs = sync_mcp_json_clients(self.tools, self.vault, self.projects_map)
        summary = " | ".join(msgs) if msgs else "Güncellenecek istemci bulunamadı."
        self.logs.add("INFO", "Config Senkronizasyon", summary)
        self._refresh_logs_tab()
        self.set_status(f"🔄 AI Config dosyaları güncellendi: {summary}")
        home = pathlib.Path.home()
        paths_info = (
            f"{summary}\n\n"
            "Yazılan / Güncellenen Konumlar:\n"
            f"• AGY: {home / '.gemini' / 'config' / 'mcp_config.json'}\n"
            f"• CDX: {home / '.codex' / 'config.toml'}\n"
            f"• CLD: {home / '.claude.json'} (ve proje içi .mcp.json)\n"
            f"• CUR: {home / '.cursor' / 'mcp.json'} (ve proje içi .cursor/mcp.json)\n"
            f"• Program Kaydı: {self.store.state_file}"
        )
        QMessageBox.information(self, "AI Config Senkronizasyonu Tamamlandı", paths_info)

    def _export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Ayarları Dışa Aktar (Export)",
            "ai_arac_ayarlar.json",
            "Ayar Dosyası (*.json *.aihub)",
        )
        if not path:
            return
        self.export_to_file(pathlib.Path(path))
        self.set_status(f"📤 Tüm ayarlar ve seçimler dışa aktarıldı: {path}")

    def export_to_file(self, target_path: pathlib.Path) -> None:
        self._save_state()
        payload = self.store.serialize(self.tools, self.active_skills, self.meta, self.default_ids)
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ayarları İçe Aktar (Import)",
            "",
            "Ayar Dosyası (*.json *.aihub)",
        )
        if not path:
            return
        try:
            self.import_from_file(pathlib.Path(path))
            self.set_status(f"📥 Ayarlar ve tüm seçimler geri yüklendi: {path}")
            QMessageBox.information(self, "Import Tamamlandı", "Tüm araç durumları, proje kapsamları, çark ayarları ve kutucuk seçimleriniz geri yüklendi.")
        except Exception as exc:
            QMessageBox.warning(self, "Import Hatası", f"Dosya okunamadı: {exc}")

    def import_from_file(self, source_path: pathlib.Path) -> None:
        txt = source_path.read_text(encoding="utf-8")
        json.loads(txt)  # Geçerli JSON doğrulaması
        self.store.state_file.write_text(txt, encoding="utf-8")
        self.tools = build_default_catalog()
        self.active_skills, self.meta = self.store.load_into(self.tools)

        self.sort_key = str(self.meta.get("sort_key", "usage"))
        self.sort_desc = bool(self.meta.get("sort_desc", True))
        self._apply_theme(self.meta.get("theme", "dark"))

        self.auto_detect_cb.blockSignals(True)
        self.auto_detect_cb.setChecked(bool(self.meta.get("auto_detect_apps", True)))
        self.auto_detect_cb.blockSignals(False)

        for t in self.tools:
            t.live_location_detail = resolve_disk_location(t, self.projects_map, {})

        bs_tool = next((t for t in self.tools if t.id == "blender_skills"), None)
        if bs_tool:
            sync_blender_skills_on_disk(self.active_skills, bs_tool.enabled, bs_tool.project_scope, self.projects_map)

        self.tabs.setTabText(0, f"📊 Araç Paneli ({len(self.tools)})")
        self._update_profile_buttons_ui()
        self._rebuild_project_filter_combo()
        self._rebuild_custom_presets_combo()
        self._refresh_table()
        self._refresh_plugins_tab()
        self.run_health_scan()

    def _handle_inspect_repo(self) -> None:
        url = self.repo_inp.text().strip()
        if not url:
            return
        self.btn_probe_repo.setEnabled(False)
        self.btn_add_repo.setEnabled(False)
        self.repo_result_box.setPlainText("GitHub API üzerinden repo yapısı sorgulanıyor...")
        tok = self.vault.get_secret("GITHUB_TOKEN")

        def worker() -> None:
            try:
                info = inspect_github_repo(url, tok)
                self.bridge.repo_done.emit({"ok": True, "info": info})
            except Exception as exc:
                self.bridge.repo_done.emit({"ok": False, "error": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _on_repo_inspected(self, payload: dict[str, Any]) -> None:
        self.btn_probe_repo.setEnabled(True)
        if not payload.get("ok"):
            self.detected_repo_candidate = None
            self.repo_result_box.setPlainText(f"Sorgulama hatası: {payload.get('error')}")
            return
        info = payload["info"]
        self.detected_repo_candidate = info
        self.btn_add_repo.setEnabled(True)
        self.repo_result_box.setPlainText(
            f"Ad: {info['name']}  (⭐ {info['stars']})\n"
            f"Algılanan Tür: {info['kind']}  |  SKILL.md Sayısı: {info['skill_count']}\n"
            f"Açıklama: {info['description']}\n"
            f"Kurulum / Çalıştırma: {info['install_cmd']}\n"
            f"API Anahtarı İhtiyacı: {'Evet (⚙️ Çark eklenecek)' if info['needs_api_key'] else 'Hayır (Sade satır — gereksiz çark eklenmeyecek)'}"
        )

    def _handle_add_detected_repo(self) -> None:
        info = self.detected_repo_candidate
        if not info:
            return
        if any(t.repo_url.lower() == info["repo_url"].lower() for t in self.tools):
            QMessageBox.information(self, "Zaten Ekli", f"{info['name']} zaten araç listenizde bulunuyor.")
            return
        has_real_gear = bool(info["needs_api_key"])
        new_tool = ToolSpec(
            id=info["id"],
            name=info["name"],
            kind=info["kind"],
            version="v1.0.0",
            repo_url=info["repo_url"],
            schema_tokens=2000,
            summary=str(info.get("description") or f"{info['name']} özel eklentisi."),
            details=f"GitHub üzerinden eklenen {info['kind']} aracı ({info['repo_url']}).",
            when_to_use="İlgili projede bu eklentinin özelliklerine ihtiyacınız olduğunda AÇIN; kullanmadığınızda şema tasarrufu için KAPATIN.",
            enabled=True,
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=has_real_gear,
            param_label="Ek Argüman / Yol" if has_real_gear else "",
            install_cmd=info["install_cmd"],
            mcp_server_key=info["id"] if info["mcp_command"] else "",
            mcp_command=info["mcp_command"],
            mcp_args=info["mcp_args"],
        )
        self.tools.append(new_tool)
        cur_p_chk = self._get_panel_checked_set()
        cur_p_chk.add(new_tool.id)
        self.meta["panel_checked_ids"] = [t.id for t in self.tools if t.id in cur_p_chk]
        self._save_state()
        self._refresh_table()
        self._refresh_plugins_tab()
        self.tabs.setTabText(0, f"📊 Araç Paneli ({len(self.tools)})")
        self.tabs.setCurrentIndex(0)
        self.set_status(f"📚 {info['name']} kütüphaneye ve ana panele eklendi!")

    def run_plugin_update_check(self, manual: bool = False) -> None:
        if self.checking_plugins_busy or self.updating_busy:
            return
        self.checking_plugins_busy = True
        self.btn_plugins_check.setEnabled(False)
        self.plugins_banner_lbl.setText("🔍 Eklenti sürümleri kontrol ediliyor...")
        self.plugins_banner_lbl.setStyleSheet("color: #94a3b8; font-weight: 600;")
        if manual:
            self.set_status("🔍 Tüm eklentiler için güncel sürüm kontrolü yapılıyor...")

        snap = list(self.tools)
        tok = self.vault.get_secret("GITHUB_TOKEN")

        def worker() -> None:
            cnt, chk_errs = check_all_tools_updates_parallel(snap, tok)
            for t_name, err_det in chk_errs:
                self.logs.add("WARN", t_name, f"Güncelleme kontrolü sırasında ağ/API hatası: {err_det.splitlines()[0]}", err_det)
            self.bridge.plugin_check_done.emit(cnt, manual)

        threading.Thread(target=worker, daemon=True).start()

    def _jump_to_error_logs(self) -> None:
        self.log_lvl_cmb.setCurrentText("ERR")
        self._refresh_logs_tab()
        self._set_log_checks("issues_only")
        self.tabs.setCurrentIndex(4)
        if self.log_table.rowCount() > 0:
            self.log_table.selectRow(0)

    def _on_plugin_check_done(self, upd_count: int, manual: bool) -> None:
        self.checking_plugins_busy = False
        self.btn_plugins_check.setEnabled(True)
        self.btn_jump_err_logs.hide()
        self._refresh_logs_tab()

        if upd_count == 0:
            self.plugins_banner_lbl.setText("✓ Tüm eklentiler güncel.")
            self.plugins_banner_lbl.setStyleSheet("color: #22c55e; font-weight: 700;")
            self.tabs.setTabText(1, "🧩 Eklentiler")
            if manual:
                self.set_status("✓ Tüm eklentiler güncel.")
        else:
            self.plugins_banner_lbl.setText(
                f"🔔 Güncelleme Mevcut ({upd_count} eklenti) — Güncellemeyi başlatmak için aşağıdaki butonları kullanabilirsiniz."
            )
            self.plugins_banner_lbl.setStyleSheet("color: #f59e0b; font-weight: 700;")
            self.tabs.setTabText(1, f"🧩 Eklentiler (🔔 {upd_count})")
            self.set_status(f"🔔 {upd_count} eklenti için güncelleme mevcut — Eklentiler sekmesinden başlatabilirsiniz.")
            if manual:
                self.tabs.setCurrentIndex(1)

        self._refresh_table()
        self._refresh_plugins_tab()

    def _handle_start_available_updates(self) -> None:
        targets = [t for t in self.tools if t.has_update]
        if not targets:
            self.set_status("✓ Tüm eklentiler zaten güncel.")
            return
        self._run_batch_update(targets, install_if_missing=True)

    def _handle_update_selected_plugins(self) -> None:
        selected = [t for t in self.tools if self.plugin_checks.get(t.id) and self.plugin_checks[t.id].isChecked()]
        if not selected:
            QMessageBox.information(self, "Araç Seçilmedi", "Lütfen listeden kurmak veya güncellemek istediğiniz araçları işaretleyin.")
            return
        self._run_batch_update(selected, install_if_missing=True)

    def _run_batch_update(self, target_tools: list[ToolSpec], install_if_missing: bool = False) -> None:
        if self.updating_busy or not target_tools:
            return
        self.updating_busy = True
        self.btn_plugins_check.setEnabled(False)
        self.btn_plugins_update_all.setEnabled(False)
        self.btn_plugins_install_sel.setEnabled(False)

        total = len(target_tools)
        self.update_prog.setMaximum(total)
        self.update_prog.setValue(0)
        self.update_prog.setFormat(f"Güncelleme uygulanıyor (0/{total})...")
        self.update_prog.show()
        self.set_status(f"⬆️ {total} araç güncelleniyor...")

        wanted_skills = set(self.active_skills)
        items = list(target_tools)

        def worker() -> None:
            ok_cnt = 0
            fail_cnt = 0
            details: list[str] = []
            for idx, tool_obj in enumerate(items, start=1):
                self.bridge.update_progress.emit(idx, total, tool_obj.name)
                prev_v = tool_obj.version.strip().lstrip("vV")
                ok, new_ver, msg, raw_log = update_single_tool(tool_obj, wanted_skills, install_if_missing=install_if_missing)
                target_v = (tool_obj.latest_version or new_ver or tool_obj.version).strip().lstrip("vV")
                if ok:
                    ok_cnt += 1
                    tool_obj.version = f"v{target_v}"
                    tool_obj.latest_version = f"v{target_v}"
                    tool_obj.has_update = False
                    ver_note = f"{prev_v}v > {target_v}v" if prev_v != target_v else f"{target_v}v"
                    self.logs.add("INFO", tool_obj.name, f"Güncellendi ({ver_note})", raw_log)
                    details.append(f"✓ {tool_obj.name} ({ver_note}): {msg}")
                else:
                    fail_cnt += 1
                    self.logs.add("ERR", tool_obj.name, f"Güncelleme Hatası: {msg}", raw_log)
                    details.append(f"🔴 {tool_obj.name}: {msg}")
            self.bridge.update_all_done.emit(ok_cnt, fail_cnt, "\n".join(details))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_progress(self, idx: int, total: int, tool_name: str) -> None:
        self.update_prog.setValue(idx - 1)
        self.update_prog.setFormat(f"Güncelleniyor ({idx}/{total}): {tool_name}...")
        self.set_status(f"⬆️ Güncelleniyor ({idx}/{total}): {tool_name}...")

    def _on_update_all_done(self, ok_cnt: int, fail_cnt: int, summary_text: str) -> None:
        self.updating_busy = False
        self.btn_plugins_check.setEnabled(True)
        self.btn_plugins_install_sel.setEnabled(True)
        self.update_prog.setValue(self.update_prog.maximum())
        self.update_prog.setFormat(f"Tamamlandı: {ok_cnt} güncellendi, {fail_cnt} hata")
        QTimer.singleShot(3500, self.update_prog.hide)

        rem = sum(1 for t in self.tools if t.has_update)
        self._on_plugin_check_done(rem, manual=False)
        if fail_cnt > 0:
            self.plugins_banner_lbl.setText(
                f"🔴 {fail_cnt} araç güncellenirken hata alındı ({ok_cnt} başarılı) — Hata detayları Debug & Log sekmesine kaydedildi."
            )
            self.plugins_banner_lbl.setStyleSheet("color: #ef4444; font-weight: 700;")
            self.btn_jump_err_logs.show()
            self.set_status(f"🔴 Güncelleme sırasında {fail_cnt} hata oluştu — Debug & Log sekmesinden tam çıktıyı görebilirsiniz.")
        else:
            self.set_status(f"✓ Güncelleme tamamlandı ({ok_cnt} araç güncellendi).")
        self._save_state()
        self._refresh_logs_tab()
        self.run_health_scan()

    def _apply_app_update_visual_state(self, res: UpdateCheckResult) -> None:
        if res.ok and res.has_update:
            ver_cmp = f"{res.local_version}v > {res.remote_version}v"
            self.btn_app_update_top.setText(f"⬆️ Yeni Program Sürümü ({ver_cmp})")
            self.btn_app_update_top.setObjectName("warnBtn")
            self.btn_do_app_upd.setText(f"🔔 Program Güncellemesi ({ver_cmp})")
            self.btn_do_app_upd.setObjectName("warnBtn")
            self.app_update_banner_lbl.setText(f"🚀 Bu programın yeni bir sürümü yayınlandı:  {ver_cmp}")
            if res.release_notes_url:
                self.app_update_notes_lbl.setText(
                    f"<a style='color:#93c5fd; font-weight:600;' href='{res.release_notes_url}'>📄 Yenilikleri Gör ↗</a>"
                )
            self.app_update_banner.show()
        elif res.ok:
            self.btn_app_update_top.setText(tr(self.lang, "app_up_to_date"))
            self.btn_app_update_top.setObjectName("primaryBtn")
            self.btn_do_app_upd.setText(tr(self.lang, "ver_btn", ver=res.local_version))
            self.btn_do_app_upd.setObjectName("")
            self.app_update_banner.hide()

        for b in (self.btn_app_update_top, self.btn_do_app_upd):
            self.style().unpolish(b)
            self.style().polish(b)

    def _run_startup_app_update_check(self) -> None:
        repo = resolve_effective_app_repo(str(self.meta.get("app_update_repo", "")))
        if not repo:
            return
        tok = self.vault.get_secret("GITHUB_TOKEN")
        self._startup_app_check = True

        def worker() -> None:
            res = check_for_app_updates(repo, tok)
            self.bridge.app_check_done.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_quick_check_app_update(self) -> None:
        if self.latest_app_check and self.latest_app_check.has_update:
            self._open_app_update_dialog(self.latest_app_check)
            return
        repo = resolve_effective_app_repo(str(self.meta.get("app_update_repo", "")))
        self.btn_app_update_top.setEnabled(False)
        self.btn_app_update_top.setText("🔍 Program Kontrol Ediliyor...")
        self.set_status(f"🔍 {repo} üzerinden bu programın yeni sürümü kontrol ediliyor...")
        tok = self.vault.get_secret("GITHUB_TOKEN")
        self._silent_app_check = True

        def worker() -> None:
            res = check_for_app_updates(repo, tok)
            self.bridge.app_check_done.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_bg_app_check_done(self, res: UpdateCheckResult) -> None:
        self.latest_app_check = res
        self.btn_app_update_top.setEnabled(True)
        self._apply_app_update_visual_state(res)

        if self._startup_app_check:
            self._startup_app_check = False
            if res.ok and res.has_update:
                self.set_status(f"🔔 Program güncellemesi mevcut: {res.local_version}v > {res.remote_version}v — Üstteki butondan güncelleyebilirsiniz.")
            return

        if not self._silent_app_check:
            return
        self._silent_app_check = False
        if res.has_update:
            self.set_status(f"🔔 Yeni program sürümü bulundu: {res.local_version}v > {res.remote_version}v")
            self._open_app_update_dialog(res)
        elif res.ok:
            self.set_status(f"✓ Kullandığınız program son sürümde ({res.local_version}v) — yeni güncelleme bulunmuyor.")
        else:
            self.btn_app_update_top.setText("🔄 Program Güncelleme")
            self.set_status(f"⚠️ {res.message}")

    def _open_connection_test_dialog(self) -> None:
        dlg = ConnectionTestDialog(self, self.tools, self.vault, self.projects_map, len(self.active_skills))
        dlg.exec()

    def _open_app_update_dialog(self, initial_res: UpdateCheckResult | None = None) -> None:
        self._silent_app_check = False
        self._startup_app_check = False
        dlg = AppUpdateDialog(self, initial_res)
        dlg.exec()
