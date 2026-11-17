"""PySide6 (Qt 6) Yerel Masaüstü Arayüzü: Proje/Konum Sütunu, 94-Skill Çark Yöneticisi, Çift Yönlü AI Danışman ve Sistem Tepsisi."""
from __future__ import annotations

import json
import pathlib
import threading
from typing import Any

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
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
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .ai_advisor import (
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
)
from .storage import LogDatabase, StateStore, WindowsDpapiVault
from .system_ops import (
    check_all_tools_updates_parallel,
    detect_running_dcc_apps,
    free_trellis_vram,
    inspect_github_repo,
    kill_zombie_port_process,
    probe_tool_health,
    query_gpu_vram,
    resolve_disk_location,
    scan_live_process_locations,
    sync_blender_skills_on_disk,
    sync_mcp_json_clients,
    update_single_tool,
)
from .updater import (
    UpdateCheckResult,
    apply_self_update,
    check_for_app_updates,
    detect_git_origin_url,
    get_current_app_version,
    restart_running_python_app,
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
QHeaderView::section { background-color: #182232; color: #94a3b8; padding: 6px; border: none; border-bottom: 1px solid #243042; font-weight: 600; }
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
QHeaderView::section { background-color: #f1f5f9; color: #475569; padding: 6px; border: none; border-bottom: 1px solid #cbd5e1; font-weight: 600; }
QFrame#card { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; }
"""


def create_app_icon() -> QIcon:
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
    health_done = Signal(object)
    repo_done = Signal(object)
    plugin_check_done = Signal(int, bool)
    update_progress = Signal(int, int, str)
    update_all_done = Signal(int, int, str)
    app_check_done = Signal(object)
    app_dl_progress = Signal(int, int)
    app_apply_done = Signal(bool, str, str)


class AiMatrixHeaderView(QHeaderView):
    """Sütun 5 başlığının tam içine alt satırlarla birebir hizalı [AGY] [CDX] [CLD] [CUR] toplu kontrol butonları yerleştirir."""

    AI_COL = 5
    AI_COL_WIDTH = 161  # 4px sol + 4x36px buton + 3x3px boşluk + 4px sağ = 161px

    def __init__(self, parent_table: QTableWidget, main_win: "MainWindow") -> None:
        super().__init__(Qt.Orientation.Horizontal, parent_table)
        self.main_win = main_win
        self.setSectionsClickable(True)
        self.setMinimumHeight(34)

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
        if self.count() <= self.AI_COL or self.isSectionHidden(self.AI_COL):
            self.ai_bar.hide()
            return
        x = self.sectionViewportPosition(self.AI_COL)
        w = self.sectionSize(self.AI_COL)
        vh = self.viewport().height() or self.height()
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


class AppUpdateDialog(QDialog):
    """GitHub Üzerinden Açık Kaynak Program Güncelleme Kontrol & Tek Tık İndirme Penceresi."""

    def __init__(self, parent: "MainWindow", initial_result: UpdateCheckResult | None = None) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.last_check: UpdateCheckResult | None = initial_result
        self.setWindowTitle(f"🔄 Program Güncelleme Merkezi (Mevcut: v{get_current_app_version()})")
        self.resize(620, 360)

        lay = QVBoxLayout(self)

        repo_card = QFrame()
        repo_card.setObjectName("card")
        r_lay = QVBoxLayout(repo_card)
        r_lay.addWidget(QLabel("<b>GitHub Kaynak Repo Adresi (Açık Kaynak Güncelleme Kanalı)</b>"))
        row = QHBoxLayout()
        cur_repo = str(parent.meta.get("app_update_repo") or detect_git_origin_url())
        self.repo_inp = QLineEdit(cur_repo)
        self.repo_inp.setPlaceholderText("https://github.com/kullanici_adiniz/ai-arac-merkezi")
        row.addWidget(self.repo_inp, stretch=1)

        self.btn_check = QPushButton("🔍 Güncelleme Kontrol Et")
        self.btn_check.setObjectName("primaryBtn")
        self.btn_check.clicked.connect(self.run_check)
        row.addWidget(self.btn_check)
        r_lay.addLayout(row)
        lay.addWidget(repo_card)

        status_row = QHBoxLayout()
        self.status_badge = QLabel("Durum kontrol bekliyor...")
        self.status_badge.setStyleSheet("font-weight: 700; font-size: 13px;")
        status_row.addWidget(self.status_badge, stretch=1)

        self.notes_link_lbl = QLabel("")
        self.notes_link_lbl.setOpenExternalLinks(True)
        status_row.addWidget(self.notes_link_lbl)
        lay.addLayout(status_row)

        self.info_box = QPlainTextEdit()
        self.info_box.setReadOnly(True)
        self.info_box.setPlaceholderText("Güncelleme kontrolü yaptığınızda sürüm karşılaştırması ve değişiklik notları burada görünür...")
        lay.addWidget(self.info_box, stretch=1)

        self.dl_bar = QProgressBar()
        self.dl_bar.hide()
        lay.addWidget(self.dl_bar)

        bot = QHBoxLayout()
        bot.addStretch()
        btn_close = QPushButton("Kapat")
        btn_close.clicked.connect(self.reject)
        self.btn_apply = QPushButton("⚡ Programı Şimdi Güncelle")
        self.btn_apply.setObjectName("successBtn")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.run_apply)
        bot.addWidget(btn_close)
        bot.addWidget(self.btn_apply)
        lay.addLayout(bot)

        parent.bridge.app_check_done.connect(self._on_checked)
        parent.bridge.app_dl_progress.connect(self._on_dl_prog)
        parent.bridge.app_apply_done.connect(self._on_applied)

        if initial_result is not None:
            self._render_result(initial_result)
        elif cur_repo:
            QTimer.singleShot(150, self.run_check)

    def run_check(self) -> None:
        repo = self.repo_inp.text().strip()
        self.main_win.meta["app_update_repo"] = repo
        self.main_win._save_state()
        self.btn_check.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.info_box.setPlainText("GitHub üzerinden son sürüm kontrol ediliyor...")
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
        elif res.has_update:
            self.status_badge.setText(f"🔔 Güncelleme Mevcut:  {res.local_version}v > {res.remote_version}v")
            self.status_badge.setStyleSheet("color: #f59e0b; font-weight: 700; font-size: 13px;")
            if res.release_notes_url:
                self.notes_link_lbl.setText(f"<a style='color:#60a5fa;' href='{res.release_notes_url}'>📄 Güncelleme Notları ↗</a>")
        else:
            self.status_badge.setText(f"✓ Program güncel ({res.local_version}v)")
            self.status_badge.setStyleSheet("color: #22c55e; font-weight: 700; font-size: 13px;")
            if res.release_notes_url:
                self.notes_link_lbl.setText(f"<a style='color:#60a5fa;' href='{res.release_notes_url}'>📄 Sürüm Geçmişi ↗</a>")

        lines = [
            f"Sürüm Karşılaştırması: {res.local_version}v > {res.remote_version}v" if res.has_update else f"Mevcut Sürüm: {res.local_version}v (Güncel)",
        ]
        if res.repo_url:
            lines.append(f"GitHub Deposu: {res.repo_url}")
        if res.release_notes_url:
            lines.append(f"Güncelleme Notları: {res.release_notes_url}")
        if res.exe_download_url:
            lines.append("İndirme Türü: Hazır AI-Arac-Merkezi.exe (Tek tıkla otomatik yenileme)")
        elif res.can_git_pull:
            lines.append("İndirme Türü: Git Kaynak Deposu (git pull)")
        if res.changelog:
            lines.extend(["", "--- Değişiklik Özeti ---", res.changelog])
        self.info_box.setPlainText("\n".join(lines))

        self.btn_apply.setEnabled(res.ok and res.has_update)
        if res.has_update:
            self.btn_apply.setText(f"⚡ Güncellemeyi Başlat ({res.local_version}v > {res.remote_version}v)")
        else:
            self.btn_apply.setText("✓ Sürüm Güncel")

    def run_apply(self) -> None:
        if not self.last_check:
            return
        self.btn_apply.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.dl_bar.setMaximum(100)
        self.dl_bar.setValue(0)
        self.dl_bar.setFormat("GitHub'dan çekiliyor...")
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
        QMessageBox.information(self, "Güncelleme Tamamlandı", msg)
        if mode == "swap_exe":
            self.accept()
            self.main_win._quit_app()
        elif mode == "restart_py":
            self.accept()
            self.main_win._save_state()
            restart_running_python_app()


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
        apply_btn = QPushButton("📥 Analiz Et & Seçime Uygula")
        apply_btn.setObjectName("primaryBtn")
        apply_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(apply_btn)
        lay.addLayout(btns)


class BlenderSkillsDialog(QDialog):
    """⚙️ Blender Skills (arjun988) — 94 Skill Çoklu Seçim + Çift Yönlü AI Danışma Penceresi."""

    def __init__(self, parent: QWidget, active_skills: set[str], checked_skills: set[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚙️ Blender Skills (arjun988) — 94 Skill Yöneticisi")
        self.resize(880, 620)
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
        self.btn_paste_ai = QPushButton("📥 AI Yanıtını Yapıştır & Uygula")
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

            cb = QCheckBox(sk)
            cb.setChecked(sk in self.checked_items)
            cb.toggled.connect(lambda checked, name=sk: self._on_check_toggled(name, checked))
            row_lay.addWidget(cb, stretch=1)

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
    """⚙️ Standart Araç Teknik Ayarları + Konum Bilgisi + Çift Yönlü AI Danışma Penceresi."""

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
        self.resize(650, 460)

        lay = QVBoxLayout(self)

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

        if tool.param_label:
            p_card = QFrame()
            p_card.setObjectName("card")
            p_lay = QVBoxLayout(p_card)
            p_lay.addWidget(QLabel(f"<b>{tool.param_label}</b>"))
            self.param_inp = QLineEdit(tool.param_value)
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

        opt_card = QFrame()
        opt_card.setObjectName("card")
        opt_lay = QVBoxLayout(opt_card)
        opt_lay.addWidget(QLabel("<b>Özellikler & Çalışma İzinleri</b>"))
        self.opt_checks: dict[str, QCheckBox] = {}
        for opt in tool.options:
            cb = QCheckBox(opt.label)
            cb.setChecked(opt.enabled)
            self.opt_checks[opt.key] = cb
            opt_lay.addWidget(cb)
        lay.addWidget(opt_card)

        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setFixedHeight(95)
        self.prompt_preview.hide()
        lay.addWidget(self.prompt_preview)

        lay.addStretch()

        bot = QHBoxLayout()
        btn_ask = QPushButton("🤖 AI'a Danış (Prompt Kopyala)")
        btn_paste = QPushButton("📥 AI Yanıtını Yapıştır & Uygula")
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


class MainWindow(QMainWindow):
    """AI Araç & Token Ekonomisi Masaüstü Kontrol Merkezi Ana Penceresi."""

    def __init__(self, data_dir: pathlib.Path) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.vault = WindowsDpapiVault(self.data_dir / "vault.dpapi.json")
        self.logs = LogDatabase(self.data_dir / "ai_hub_logs.db")
        self.store = StateStore(self.data_dir / "hub_state.json")

        self.tools: list[ToolSpec] = build_default_catalog()
        self.default_ids: set[str] = {t.id for t in self.tools}
        self.active_skills, self.meta = self.store.load_into(self.tools)

        self.sort_key = str(self.meta.get("sort_key", "usage"))
        self.sort_desc = bool(self.meta.get("sort_desc", True))
        self.seconds_left = 600
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
        self.updating_busy = False
        self.checking_plugins_busy = False
        self.latest_app_check: UpdateCheckResult | None = None
        self._silent_app_check = False
        self._startup_app_check = False

        app_ver = get_current_app_version()
        self.setWindowTitle(f"AI Araç & Token Ekonomisi Kontrol Merkezi v{app_ver}")
        self.setWindowIcon(create_app_icon())
        self.resize(1340, 760)

        self._build_ui()
        self._build_tray()
        self._apply_theme(self.meta.get("theme", "dark"))
        for t in self.tools:
            t.live_location_detail = resolve_disk_location(t, self.projects_map, {})
        self._rebuild_project_filter_combo()
        self._refresh_table()
        self._refresh_plugins_tab()
        self._refresh_vault_tab()
        self._refresh_logs_tab()
        self._update_vram_bar()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._on_second_tick)
        self.tick_timer.start(1000)

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

        # 1. ÜST BAR: Hazır İş Modu Profilleri + Oto-Algılama + VRAM + Sayaç
        prof_bar = QHBoxLayout()
        prof_bar.addWidget(QLabel("<b>🎯 İş Modu:</b>"))
        for p_key, p_info in PROFILES.items():
            btn = QPushButton(p_info["title"].replace("&", "&&"))
            btn.setToolTip(p_info["desc"])
            btn.clicked.connect(lambda _=False, k=p_key: self.apply_profile(k))
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

        btn_vram_free = QPushButton("🧹 VRAM Boşalt")
        btn_vram_free.setToolTip("Arka planda açık kalan Trellis GPU sunucusunu uyutup VRAM'i boşaltır")
        btn_vram_free.clicked.connect(self._handle_free_vram)
        prof_bar.addWidget(btn_vram_free)

        self.timer_lbl = QLabel("10:00")
        self.timer_lbl.setStyleSheet("font-family: Consolas, monospace; font-weight: 700; padding: 4px 8px;")
        prof_bar.addWidget(self.timer_lbl)

        btn_refresh = QPushButton("↻ Durum Tara")
        btn_refresh.setToolTip("Tüm araçların port, sağlık, VRAM ve canlı süreç durumlarını anında yeniler")
        btn_refresh.clicked.connect(self.run_health_scan)
        prof_bar.addWidget(btn_refresh)

        self.btn_top_update_all = QPushButton("🔍 Eklenti Güncelleme Kontrol")
        self.btn_top_update_all.setObjectName("primaryBtn")
        self.btn_top_update_all.setToolTip("Eklentiler için yeni sürüm var mı kontrol eder (güncelleme varsa Eklentiler ekranını açar)")
        self.btn_top_update_all.clicked.connect(self._handle_top_plugin_update_btn)
        prof_bar.addWidget(self.btn_top_update_all)

        btn_sync = QPushButton("🔄 AI Config'lere Yaz")
        btn_sync.setObjectName("successBtn")
        btn_sync.setToolTip("Global ve Proje Bazlı (.mcp.json / .agents/skills) yapılandırmaları yedek alarak uygular")
        btn_sync.clicked.connect(self._handle_sync_configs)
        prof_bar.addWidget(btn_sync)

        btn_theme = QPushButton("🌗 Tema")
        btn_theme.clicked.connect(self._toggle_theme)
        prof_bar.addWidget(btn_theme)

        main_lay.addLayout(prof_bar)

        # 2. SEKMELER
        self.tabs = QTabWidget()
        main_lay.addWidget(self.tabs, stretch=1)

        self._init_panel_tab()
        self._init_plugins_tab()
        self._init_vault_tab()
        self._init_repo_tab()
        self._init_logs_tab()

        # 3. ALT DURUM ÇUBUĞU + PROGRAM GÜNCELLEME BUTONLARI
        foot = QHBoxLayout()
        self.status_lbl = QLabel("Hazır — Sağ alt sistem tepsisinde (Tray) kesintisiz çalışır.")
        foot.addWidget(self.status_lbl, stretch=1)

        self.btn_chk_app_upd = QPushButton(f"🔍 Güncelleme Kontrol (v{get_current_app_version()})")
        self.btn_chk_app_upd.setToolTip("GitHub deposundan programın yeni bir sürümü olup olmadığını kontrol eder")
        self.btn_chk_app_upd.clicked.connect(self._handle_quick_check_app_update)
        foot.addWidget(self.btn_chk_app_upd)

        self.btn_do_app_upd = QPushButton("⚡ Programı Güncelle")
        self.btn_do_app_upd.setToolTip("Tekrar el ile indirmeden doğrudan GitHub üzerinden programı günceller")
        self.btn_do_app_upd.clicked.connect(lambda: self._open_app_update_dialog(self.latest_app_check))
        foot.addWidget(self.btn_do_app_upd)

        self.token_summary_lbl = QLabel()
        self.token_summary_lbl.setStyleSheet("font-family: Consolas, monospace; font-weight: 600; color: #22c55e;")
        foot.addWidget(self.token_summary_lbl)
        main_lay.addLayout(foot)

    # --- SEKME 1: ANA PANEL (8 SÜTUN — PROJE / KONUM DAHİL) ---
    def _init_panel_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        flt = QHBoxLayout()
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("Araç veya konum ara (örn: Serena, project-train, BLA)...")
        self.search_inp.setFixedWidth(250)
        self.search_inp.textChanged.connect(self._refresh_table)
        flt.addWidget(self.search_inp)

        self.kind_cmb = QComboBox()
        self.kind_cmb.addItems(["Tüm Türler", "Skill Paketi", "Skill / Kural", "stdio MCP", "HTTP Servis", "CLI / GPU"])
        self.kind_cmb.currentTextChanged.connect(self._refresh_table)
        flt.addWidget(self.kind_cmb)

        flt.addWidget(QLabel("Proje:"))
        self.proj_filter_cmb = QComboBox()
        self.proj_filter_cmb.currentIndexChanged.connect(self._refresh_table)
        flt.addWidget(self.proj_filter_cmb)

        btn_add_proj = QPushButton("➕ Proje Klasörü Tanımla")
        btn_add_proj.setToolTip("Yeni bir oyun veya web sitesi klasörünü proje listesine ekler")
        btn_add_proj.clicked.connect(lambda: self._prompt_add_project_folder(assign_tool=None))
        flt.addWidget(btn_add_proj)

        flt.addStretch()
        hint_lbl = QLabel("📍 / 🟢 ikonunun üzerine gelerek canlı süreç ve dosya konumunu görebilirsiniz.")
        hint_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        flt.addWidget(hint_lbl)
        lay.addLayout(flt)

        self.table = QTableWidget(0, 8)
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
        hdr.sectionClicked.connect(self._on_header_clicked)
        self.table.horizontalScrollBar().valueChanged.connect(lambda *_: hdr.sync_ai_bar_geometry())
        lay.addWidget(self.table, stretch=1)

        self.tabs.addTab(tab, "📊 Araç Paneli (14)")

    def _rebuild_project_filter_combo(self) -> None:
        cur_data = self.proj_filter_cmb.currentData() if self.proj_filter_cmb.count() else "ALL"
        self.proj_filter_cmb.blockSignals(True)
        self.proj_filter_cmb.clear()
        self.proj_filter_cmb.addItem("Tüm Kapsamlar", "ALL")
        self.proj_filter_cmb.addItem("🌐 Sadece Global (Tüm Projeler)", "GLOBAL")
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
        key_map = {0: "name", 1: "kind", 2: "project", 3: "ping", 4: "usage"}
        if col not in key_map:
            return
        k = key_map[col]
        if self.sort_key == k:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = k
            self.sort_desc = col in (3, 4)
        self._refresh_table()

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
        kf = self.kind_cmb.currentText()
        pf = self.proj_filter_cmb.currentData() or "ALL"

        rows: list[ToolSpec] = []
        for t in self.tools:
            if q and (
                q not in t.name.lower()
                and q not in t.kind.lower()
                and q not in t.project_scope.lower()
                and q not in t.live_location_detail.lower()
            ):
                continue
            if kf != "Tüm Türler" and t.kind != kf:
                continue
            if pf == "GLOBAL" and (not t.scope_selectable or t.project_scope != "GLOBAL"):
                continue
            if pf not in ("ALL", "GLOBAL"):
                # Belirli bir proje filtresi seçildiğinde hem o projeye özel araçları hem de tüm projelerde çalışan GLOBAL araçları göster
                if t.scope_selectable and t.project_scope not in (pf, "GLOBAL"):
                    continue
            rows.append(t)

        def sort_val(item: ToolSpec) -> Any:
            if self.sort_key == "name":
                return item.name.lower()
            if self.sort_key == "kind":
                return item.kind.lower()
            if self.sort_key == "project":
                return (item.project_scope if item.scope_selectable else item.fixed_location_label).lower()
            if self.sort_key == "ping":
                return item.last_latency_ms if item.last_latency_ms >= 0 else 999999
            return item.usage_count

        rows.sort(key=sort_val, reverse=self.sort_desc)
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))

        for r_idx, t in enumerate(rows):
            self.table.setRowHeight(r_idx, 38)

            nm_item = QTableWidgetItem(t.name)
            nm_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = nm_item.font()
            font.setBold(True)
            nm_item.setFont(font)
            if t.live_location_detail:
                nm_item.setToolTip(t.live_location_detail)
            self.table.setItem(r_idx, 0, nm_item)

            kd_item = QTableWidgetItem(t.kind)
            kd_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r_idx, 1, kd_item)

            # Sütun 2: PROJE / KONUM (Seçilebilir olanlarda proje kutusu + canlı konum rozeti; sabit servislerde gerçek konum etiketi)
            proj_w = QWidget()
            proj_l = QHBoxLayout(proj_w)
            proj_l.setContentsMargins(4, 2, 4, 2)
            proj_l.setSpacing(4)

            is_live = t.live_location_detail.startswith("🟢")
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

            loc_btn = QPushButton("🟢" if is_live else "📍")
            loc_btn.setFixedWidth(28)
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
            act_l = QHBoxLayout(act_w)
            act_l.setContentsMargins(4, 2, 4, 2)
            act_l.setSpacing(5)
            act_l.addStretch()
            if t.has_gear:
                g_btn = QPushButton("⚙️")
                g_btn.setFixedWidth(34)
                g_btn.setToolTip(f"{t.name} Detaylı Ayarlar, Konum & AI'a Danış")
                g_btn.clicked.connect(lambda _=False, tool_obj=t: self.open_gear(tool_obj))
                act_l.addWidget(g_btn)

            t_btn = QPushButton("AÇIK" if t.enabled else "KAPALI")
            t_btn.setFixedWidth(66)
            if t.enabled:
                t_btn.setObjectName("primaryBtn")
            t_btn.clicked.connect(lambda _=False, tool_obj=t: self._toggle_tool(tool_obj))
            act_l.addWidget(t_btn)
            self.table.setCellWidget(r_idx, 7, act_w)

        active_k, saved_k = self._calculate_token_economy()
        self.token_summary_lbl.setText(
            f"Aktif Şema Yükü: ~{active_k}K tok  |  Korunan (Tasarruf): +{saved_k}K tok"
        )
        self.table.resizeColumnToContents(6)
        self._update_bulk_client_buttons()
        self.ai_header.sync_ai_bar_geometry()

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

            row.addWidget(QLabel(f"<b>{t.name}</b>  <span style='color:#94a3b8;'>({t.kind})</span>   {ver_html}"))
            row.addStretch()

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

        top.addWidget(QLabel("⚡ Port Kurtarıcı:"))
        for port_num, lbl in [(8080, "8080 Unity"), (9876, "9876 Blender"), (9121, "9121 Serena"), (8790, "8790 Trellis")]:
            zb = QPushButton(f"⚡ {lbl}")
            zb.setObjectName("warnBtn")
            zb.setToolTip(f"Port {port_num} üzerinde asılı kalan arka plan sürecini güvenli temizler")
            zb.clicked.connect(lambda _=False, p=port_num: self._handle_kill_zombie_port(p))
            top.addWidget(zb)
        lay.addLayout(top)

        self.log_table = QTableWidget(0, 4)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setHorizontalHeaderLabels(["Zaman", "Seviye", "Araç", "Özet Teşhis (Detay için satıra tıklayın)"])
        lh = self.log_table.horizontalHeader()
        lh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.log_table.itemSelectionChanged.connect(self._on_log_row_selected)
        lay.addWidget(self.log_table, stretch=1)

        self.log_raw_view = QPlainTextEdit()
        self.log_raw_view.setReadOnly(True)
        self.log_raw_view.setFixedHeight(95)
        self.log_raw_view.setPlaceholderText("Bir log satırına tıkladığınızda ham teknik çıktı (stderr / port / detay) burada açılır.")
        lay.addWidget(self.log_raw_view)

        self.tabs.addTab(tab, "🐛 Debug & Log")

    def _refresh_logs_tab(self) -> None:
        lvl = self.log_lvl_cmb.currentText()
        q = self.log_search_inp.text()
        self._current_logs = self.logs.query(level=lvl, search=q)
        self.log_table.setRowCount(len(self._current_logs))
        for i, row in enumerate(self._current_logs):
            for col_i, key in enumerate(("ts", "level", "tool", "summary")):
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
        self._save_state()

    def _apply_theme(self, mode: str) -> None:
        self.meta["theme"] = mode
        self.setStyleSheet(LIGHT_QSS if mode == "light" else DARK_QSS)
        if hasattr(self, "bulk_client_btns"):
            self._update_bulk_client_buttons()

    def _on_auto_detect_toggled(self, checked: bool) -> None:
        self.meta["auto_detect_apps"] = checked
        self._save_state()

    def _toggle_tool(self, tool: ToolSpec) -> None:
        tool.enabled = not tool.enabled
        self._save_state()
        self.logs.add("DBG", tool.name, f"Durum değiştirildi: {'AÇIK' if tool.enabled else 'KAPALI'}")
        self.set_status(f"{tool.name} {'açıldı' if tool.enabled else 'kapatıldı'}.")
        self._refresh_table()
        self._refresh_logs_tab()

    def _toggle_client(self, tool: ToolSpec, client_code: str, checked: bool) -> None:
        tool.clients[client_code] = checked
        self._save_state()
        self.set_status(f"{tool.name} -> {client_code} hedefi {'aktif' if checked else 'devre dışı'}.")
        self._refresh_table()

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
        self.set_status(f"🤖 {client_code} {action_desc}.")
        self._refresh_table()
        self._refresh_logs_tab()

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

    def apply_profile(self, profile_key: str) -> None:
        prof = PROFILES[profile_key]
        en_set = prof["enable"]
        for t in self.tools:
            t.enabled = t.id in en_set
        self._save_state()
        self.logs.add("INFO", "Profil", f"{prof['title']} profili etkinleştirildi.", prof["desc"])
        self.set_status(f"🎯 {prof['title']} etkinleştirildi — {prof['desc']}")
        self._refresh_table()
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

        if self.seconds_left % 10 == 0:
            self._update_vram_bar()
            if self.meta.get("auto_detect_apps", True):
                self._check_dcc_auto_switch()

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
            self.set_status("👁️ Unity.exe algılandı — İsterseniz üstten '🎮 Unity & Shader' profiline geçebilirsiniz.")
        elif cur["blender"] and not self.last_detected_apps.get("blender"):
            self.set_status("👁️ blender.exe algılandı — İsterseniz üstten '🎨 3D & Korku Asset' profiline geçebilirsiniz.")
        self.last_detected_apps = cur

    def run_health_scan(self) -> None:
        self.seconds_left = 600
        self.set_status("Sağlık, port ve canlı süreç konumları taranıyor...")
        snap_tools = list(self.tools)
        sk_cnt = len(self.active_skills)
        proj_snap = dict(self.projects_map)

        def worker() -> None:
            live_map = scan_live_process_locations()
            out = []
            for t in snap_tools:
                ok, ping_str, ms, detail, loc_detail = probe_tool_health(t, sk_cnt, proj_snap, live_map)
                out.append((t.id, ok, ping_str, ms, detail, loc_detail))
            self.bridge.health_done.emit(out)

        threading.Thread(target=worker, daemon=True).start()

    def _on_health_results(self, results: list[tuple[str, bool, str, int, str, str]]) -> None:
        by_id = {t.id: t for t in self.tools}
        for tid, ok, ping_str, ms, detail, loc_detail in results:
            if tid in by_id:
                t = by_id[tid]
                t.last_ping = ping_str
                t.last_latency_ms = ms
                t.live_location_detail = loc_detail
                if t.enabled and t.port and not ok and tid != "trellis":
                    self.logs.add("WARN", t.name, f"Açık işaretli servis yanıt vermedi ({ping_str})", detail, t.port)
        self._refresh_table()
        self._refresh_logs_tab()
        self._update_vram_bar()
        self.set_status("Sağlık ve konum taraması tamamlandı. Sayaç 10:00'a sıfırlandı.")

    def _handle_free_vram(self) -> None:
        ok, msg = free_trellis_vram()
        self.logs.add("INFO" if ok else "WARN", "Trellis Sunucu & CLI", msg)
        self._update_vram_bar()
        self._refresh_logs_tab()
        self.set_status(msg)

    def _handle_kill_zombie_port(self, port: int) -> None:
        ok, msg = kill_zombie_port_process(port)
        self.logs.add("INFO" if ok else "WARN", f"Port {port}", msg, msg, port)
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
        QMessageBox.information(self, "AI Config Senkronizasyonu Tamamlandı", summary)

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
        self._rebuild_project_filter_combo()
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
        self._save_state()
        self._refresh_table()
        self._refresh_plugins_tab()
        self.tabs.setTabText(0, f"📊 Araç Paneli ({len(self.tools)})")
        self.tabs.setCurrentIndex(0)
        self.set_status(f"📚 {info['name']} kütüphaneye ve ana panele eklendi!")

    def _handle_top_plugin_update_btn(self) -> None:
        if any(t.has_update for t in self.tools):
            self.tabs.setCurrentIndex(1)
            return
        self.run_plugin_update_check(manual=True)

    def run_plugin_update_check(self, manual: bool = False) -> None:
        if self.checking_plugins_busy or self.updating_busy:
            return
        self.checking_plugins_busy = True
        self.btn_plugins_check.setEnabled(False)
        self.btn_top_update_all.setEnabled(False)
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
        self.tabs.setCurrentIndex(4)
        if self.log_table.rowCount() > 0:
            self.log_table.selectRow(0)

    def _on_plugin_check_done(self, upd_count: int, manual: bool) -> None:
        self.checking_plugins_busy = False
        self.btn_plugins_check.setEnabled(True)
        self.btn_top_update_all.setEnabled(True)
        self.btn_jump_err_logs.hide()
        self._refresh_logs_tab()

        if upd_count == 0:
            self.plugins_banner_lbl.setText("✓ Tüm eklentiler güncel.")
            self.plugins_banner_lbl.setStyleSheet("color: #22c55e; font-weight: 700;")
            self.tabs.setTabText(1, "🧩 Eklentiler")
            self.btn_top_update_all.setText("🔍 Eklenti Güncelleme Kontrol")
            self.btn_top_update_all.setObjectName("primaryBtn")
            self.set_status("✓ Tüm eklentiler güncel.")
        else:
            self.plugins_banner_lbl.setText(
                f"🔔 Güncelleme Mevcut ({upd_count} eklenti) — Güncellemeyi başlatmak için aşağıdaki butonları kullanabilirsiniz."
            )
            self.plugins_banner_lbl.setStyleSheet("color: #f59e0b; font-weight: 700;")
            self.tabs.setTabText(1, f"🧩 Eklentiler (🔔 {upd_count})")
            self.btn_top_update_all.setText(f"🔔 Güncelleme Mevcut ({upd_count})")
            self.btn_top_update_all.setObjectName("warnBtn")
            self.set_status(f"🔔 {upd_count} eklenti için güncelleme mevcut — başlatmak size bağlıdır.")
            if manual:
                self.tabs.setCurrentIndex(1)

        self.style().unpolish(self.btn_top_update_all)
        self.style().polish(self.btn_top_update_all)
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
        self.btn_top_update_all.setEnabled(False)
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
        self.btn_top_update_all.setEnabled(True)
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

    def _run_startup_app_update_check(self) -> None:
        repo = str(self.meta.get("app_update_repo") or detect_git_origin_url()).strip()
        if not repo:
            return
        tok = self.vault.get_secret("GITHUB_TOKEN")
        self._startup_app_check = True

        def worker() -> None:
            res = check_for_app_updates(repo, tok)
            self.bridge.app_check_done.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_quick_check_app_update(self) -> None:
        repo = str(self.meta.get("app_update_repo") or detect_git_origin_url()).strip()
        if not repo:
            self._open_app_update_dialog(None)
            return
        self.btn_chk_app_upd.setEnabled(False)
        self.set_status("🔍 GitHub üzerinden program güncellemesi kontrol ediliyor...")
        tok = self.vault.get_secret("GITHUB_TOKEN")
        self._silent_app_check = True

        def worker() -> None:
            res = check_for_app_updates(repo, tok)
            self.bridge.app_check_done.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_bg_app_check_done(self, res: UpdateCheckResult) -> None:
        self.latest_app_check = res
        self.btn_chk_app_upd.setEnabled(True)

        if self._startup_app_check:
            self._startup_app_check = False
            if res.ok and res.has_update:
                self.btn_do_app_upd.setText(f"🔔 Güncelleme Mevcut ({res.local_version}v > {res.remote_version}v)")
                self.btn_do_app_upd.setObjectName("warnBtn")
                self.style().unpolish(self.btn_do_app_upd)
                self.style().polish(self.btn_do_app_upd)
                self.set_status(f"🔔 Program güncellemesi mevcut: {res.local_version}v > {res.remote_version}v")
            return

        if not self._silent_app_check:
            return
        self._silent_app_check = False
        self.set_status(res.message)
        if res.has_update:
            self.btn_do_app_upd.setText(f"🔔 Güncelleme Mevcut ({res.local_version}v > {res.remote_version}v)")
            self.btn_do_app_upd.setObjectName("warnBtn")
            self.style().unpolish(self.btn_do_app_upd)
            self.style().polish(self.btn_do_app_upd)
            self._open_app_update_dialog(res)
        elif res.ok:
            self.set_status(f"✓ Program güncel ({res.local_version}v).")
        else:
            self._open_app_update_dialog(res)

    def _open_app_update_dialog(self, initial_res: UpdateCheckResult | None = None) -> None:
        self._silent_app_check = False
        self._startup_app_check = False
        dlg = AppUpdateDialog(self, initial_res)
        dlg.exec()
