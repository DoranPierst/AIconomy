"""Main application window orchestrator for AIconomy."""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import threading
import time
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..catalog import AI_CLIENTS, PROFILES, ToolSpec, build_default_catalog
from ..host_apps import get_missing_host_dependencies, launch_host_app_for_tool
from ..i18n import SUPPORTED_LANGUAGES, detect_default_language, tr
from ..mcp_config import sync_blender_skills_on_disk, sync_mcp_json_clients
from ..processes import (
    detect_running_dcc_apps,
    enforce_tool_runtime_state,
    find_port_owner,
    free_trellis_vram,
    kill_zombie_port_process,
    probe_tool_health,
    query_gpu_vram,
    resolve_disk_location,
    scan_live_process_locations,
)
from ..storage import LogDatabase, StateStore, WindowsDpapiVault
from ..updater import (
    UpdateCheckResult,
    check_for_app_updates,
    get_current_app_version,
    resolve_effective_app_repo,
)
from .dialogs import AppUpdateDialog, BlenderSkillsDialog, ConnectionTestDialog, ToolGearDialog
from .tabs import LogsTabMixin, PluginsTabMixin, RepoTabMixin, ToolsTabMixin, VaultTabMixin
from .theme import DARK_QSS, LIGHT_QSS, create_app_icon
from .workers import WorkerBridge


class MainWindow(ToolsTabMixin, PluginsTabMixin, VaultTabMixin, RepoTabMixin, LogsTabMixin, QMainWindow):
    """Main desktop control center window."""

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
        self.bridge.update_item_done.connect(self._on_update_item_done)
        self.bridge.update_all_done.connect(self._on_update_all_done)
        self.bridge.app_check_done.connect(self._on_bg_app_check_done)
        self.bridge.vram_done.connect(self._on_vram_done)
        self.bridge.dcc_done.connect(self._on_dcc_done)
        self.bridge.port_kill_done.connect(self._on_port_kill_done)

        self._health_busy = False
        self._vram_busy = False
        self._dcc_busy = False
        self._sync_lock = threading.Lock()
        self._sync_pending_ids: set[str] = set()
        self._sync_stop_ids: set[str] = set()
        self._sync_debounce = QTimer(self)
        self._sync_debounce.setSingleShot(True)
        self._sync_debounce.setInterval(400)
        self._sync_debounce.timeout.connect(self._flush_live_sync)

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
            QTimer.singleShot(
                250, lambda: self._sync_live_environment_async(target_tools=list(self.tools), allow_stop=False)
            )
        else:
            QTimer.singleShot(250, self.run_health_scan)
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
        self.btn_app_update_top.customContextMenuRequested.connect(
            lambda _pos: self._open_app_update_dialog(self.latest_app_check)
        )
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

        self.tabs = QTabWidget()
        main_lay.addWidget(self.tabs, stretch=1)

        self._init_panel_tab()
        self._init_plugins_tab()
        self._init_vault_tab()
        self._init_repo_tab()
        self._init_logs_tab()

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

    def _sync_live_environment_async(
        self,
        target_tools: list[ToolSpec] | None = None,
        allow_stop: bool = True,
    ) -> None:
        if not self.sync_live_environment:
            return
        targets = list(target_tools) if target_tools is not None else list(self.tools)
        ids = {t.id for t in targets}
        self._sync_pending_ids.update(ids)
        if allow_stop:
            self._sync_stop_ids.update(ids)
        self._sync_debounce.start()

    def _flush_live_sync(self) -> None:
        target_ids = set(self._sync_pending_ids)
        stop_ids = set(self._sync_stop_ids)
        self._sync_pending_ids.clear()
        self._sync_stop_ids.clear()

        # K9: pass deep copies so background worker never shares mutable ToolSpec instances
        tools_snap = copy.deepcopy(self.tools)
        skills_snap = set(self.active_skills)
        proj_snap = dict(self.projects_map)

        def worker() -> None:
            with self._sync_lock:
                for t_obj in tools_snap:
                    if t_obj.id in target_ids:
                        enforce_tool_runtime_state(t_obj, proj_snap, allow_stop=(t_obj.id in stop_ids))
                bs_tool = next((x for x in tools_snap if x.id == "blender_skills"), None)
                if bs_tool:
                    sync_blender_skills_on_disk(skills_snap, bs_tool.enabled, bs_tool.project_scope, proj_snap)
                sync_mcp_json_clients(tools_snap, self.vault, proj_snap)
                live_map = scan_live_process_locations()
                out = []
                for x in tools_snap:
                    ok, ping_str, ms, detail, loc_detail = probe_tool_health(x, len(skills_snap), proj_snap, live_map)
                    out.append((x.id, ok, ping_str, ms, detail, loc_detail))
            self.bridge.health_done.emit(out, live_map, True)

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
        snap_tools = copy.deepcopy(self.tools)
        sk_cnt = len(self.active_skills)
        proj_snap = dict(self.projects_map)

        def worker() -> None:
            try:
                live_map = scan_live_process_locations()
                out = []
                for t in snap_tools:
                    ok, ping_str, ms, detail, loc_detail = probe_tool_health(t, sk_cnt, proj_snap, live_map)
                    out.append((t.id, ok, ping_str, ms, detail, loc_detail))
                self.bridge.health_done.emit(out, live_map, True)
            finally:
                self._live_watch_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _update_vram_bar(self) -> None:
        if self._vram_busy:
            return
        self._vram_busy = True

        def worker() -> None:
            name, used_mb, total_mb = "", 0, 0
            try:
                name, used_mb, total_mb = query_gpu_vram()
            finally:
                self.bridge.vram_done.emit(name, used_mb, total_mb)

        threading.Thread(target=worker, daemon=True).start()

    def _on_vram_done(self, name: str, used_mb: int, total_mb: int) -> None:
        self._vram_busy = False
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
        if self._dcc_busy:
            return
        self._dcc_busy = True
        fallback = dict(self.last_detected_apps)

        def worker() -> None:
            cur = fallback
            try:
                cur = detect_running_dcc_apps()
            finally:
                self.bridge.dcc_done.emit(cur)

        threading.Thread(target=worker, daemon=True).start()

    def _on_dcc_done(self, cur: dict[str, bool]) -> None:
        self._dcc_busy = False
        if cur.get("unity") and not self.last_detected_apps.get("unity"):
            self.set_status("👁️ Unity.exe algılandı — İsterseniz üstten '🎮 Unity & Shader' hazır ayarını seçebilirsiniz.")
        elif cur.get("blender") and not self.last_detected_apps.get("blender"):
            self.set_status("👁️ blender.exe algılandı — İsterseniz üstten '🎨 3D & Korku Asset' hazır ayarını seçebilirsiniz.")
        self.last_detected_apps = cur

    def run_health_scan(self) -> None:
        self.seconds_left = 30
        if self._health_busy:
            return
        self._health_busy = True
        self.set_status("Sağlık, port ve canlı süreç konumları taranıyor...")
        snap_tools = copy.deepcopy(self.tools)
        sk_cnt = len(self.active_skills)
        proj_snap = dict(self.projects_map)

        def worker() -> None:
            out = []
            live_map: dict[str, str] = {}
            try:
                live_map = scan_live_process_locations()
                for t in snap_tools:
                    ok, ping_str, ms, detail, loc_detail = probe_tool_health(t, sk_cnt, proj_snap, live_map)
                    out.append((t.id, ok, ping_str, ms, detail, loc_detail))
            finally:
                self._health_busy = False
            self.bridge.health_done.emit(out, live_map, False)

        threading.Thread(target=worker, daemon=True).start()

    def _on_health_results(
        self,
        results: list[tuple[str, bool, str, int, str, str]],
        live_map: dict[str, str] | None = None,
        silent: bool = False,
    ) -> None:
        if isinstance(live_map, dict):
            self._latest_live_map = live_map
        by_id = {t.id: t for t in self.tools}
        state_changed = False

        def _ping_bucket(s: str) -> str:
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
        tr_tool = next((t for t in self.tools if t.id == "trellis"), None)
        ok, msg = launch_host_app_for_tool(
            host_kind=str(dep_info.get("host", "")),
            projects_map=self.projects_map,
            target_scope=str(dep_info.get("scope", "GLOBAL")),
            headless=bool(dep_info.get("headless", True)),
            trellis_root=tr_tool.param_value if tr_tool else "",
        )
        self.logs.add("INFO" if ok else "WARN", "Bağımlı Program", msg)
        self.set_status(f"🚀 {msg}" if ok else f"⚠️ {msg}")
        self._refresh_logs_tab()
        QTimer.singleShot(2500, self.run_health_scan)

    def _auto_heal_tool_async(self, tool: ToolSpec) -> None:
        # K9: copy snapshots before spawning worker thread
        tool_snap = copy.deepcopy(tool)
        proj_snap = dict(self.projects_map)
        sk_cnt = len(self.active_skills)

        def worker() -> None:
            note = enforce_tool_runtime_state(tool_snap, proj_snap, allow_stop=False)
            if note:
                self.logs.add("INFO", tool_snap.name, f"Otomatik Kurtarma:{note}")
                time.sleep(1.5)
                live_map = scan_live_process_locations()
                ok, ping_str, ms, detail, loc_detail = probe_tool_health(tool_snap, sk_cnt, proj_snap, live_map)
                self.bridge.health_done.emit([(tool_snap.id, ok, ping_str, ms, detail, loc_detail)], live_map, True)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_free_vram(self) -> None:
        ok, msg = free_trellis_vram()
        self.logs.add("INFO" if ok else "WARN", "Trellis Sunucu & CLI", msg)
        self._update_vram_bar()
        self._refresh_logs_tab()
        self.set_status(msg)

    def _handle_kill_zombie_port(self, port: int) -> None:
        owner_pid, owner_name = find_port_owner(port)
        if owner_pid:
            ans = QMessageBox.question(
                self,
                "Asılı Portu Kapat",
                f"Port {port} şu an '{owner_name}' (PID {owner_pid}) tarafından kullanılıyor.\n\n"
                "Bu süreci sonlandırmak istediğinize emin misiniz? Bu süreç başka bir programa aitse "
                "kaydedilmemiş verileri kaybolabilir.",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.set_status(f"Port {port} temizleniyor...")

        def worker() -> None:
            ok, msg = False, ""
            try:
                ok, msg = kill_zombie_port_process(port)
            except Exception as exc:
                msg = f"Port {port} temizlenemedi: {exc}"
            finally:
                self.bridge.port_kill_done.emit(port, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_port_kill_done(self, port: int, _ok: bool, msg: str) -> None:
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
            QMessageBox.information(
                self,
                "Import Tamamlandı",
                "Tüm araç durumları, proje kapsamları, çark ayarları ve kutucuk seçimleriniz geri yüklendi.",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Import Hatası", f"Dosya okunamadı: {exc}")

    def import_from_file(self, source_path: pathlib.Path) -> None:
        txt = source_path.read_text(encoding="utf-8")
        json.loads(txt)
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
