"""Main application window orchestrator for AIconomy (minimalist 3-tab UI, emoji-free, EN & TR)."""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import threading
import time
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QStandardItem, QStandardItemModel
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

from ..catalog import (
    AI_CLIENTS,
    PROFILES,
    ToolSpec,
    build_default_catalog,
    localized_tool_modes,
    profile_desc,
    profile_title,
)
from ..host_apps import get_missing_host_dependencies, launch_host_app_for_tool
from ..i18n import SUPPORTED_LANGUAGES, normalize_language, tr
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
from ..storage import (
    LOG_DB_FILENAME,
    STATE_FILENAME,
    VAULT_FILENAME,
    LogDatabase,
    StateStore,
    WindowsDpapiVault,
    migrate_legacy_data_files,
)
from ..updater import (
    UpdateCheckResult,
    check_for_app_updates,
    get_current_app_version,
    resolve_effective_app_repo,
)
from .dialogs import (
    AppUpdateDialog,
    BlenderSkillsDialog,
    DiagnosticsDialog,
    ManageProfilesDialog,
    SettingsDialog,
    ToolGearDialog,
)
from .icons import icon_color, make_icon
from .tabs import LogsTabMixin, PluginsTabMixin, ToolsTabMixin
from .theme import DARK_QSS, LIGHT_QSS, MinimalStyle, create_app_icon, get_stylesheet
from .workers import WorkerBridge, safe_emit


class MainWindow(ToolsTabMixin, PluginsTabMixin, LogsTabMixin, QMainWindow):
    """Streamlined desktop control center for MCP servers, skills, and token budgets."""

    def __init__(self, data_dir: pathlib.Path, sync_live_environment: bool = True) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.sync_live_environment = sync_live_environment
        migrate_legacy_data_files(self.data_dir)

        self.vault = WindowsDpapiVault(self.data_dir / VAULT_FILENAME)
        self.logs = LogDatabase(self.data_dir / LOG_DB_FILENAME)
        self.store = StateStore(self.data_dir / STATE_FILENAME)

        self.tools: list[ToolSpec] = build_default_catalog()
        self.default_ids: set[str] = {t.id for t in self.tools}
        self.active_skills, self.meta = self.store.load_into(self.tools)

        self.sort_key = str(self.meta.get("sort_key", "enabled"))
        self.sort_desc = bool(self.meta.get("sort_desc", True))
        self.seconds_left = 30
        self._live_watch_busy = False
        self.last_detected_apps = {"unity": False, "blender": False, "trellis_server": False}
        self.tray_notified = False
        self.force_quit = False
        self._has_nvidia_gpu = False

        self.bridge = WorkerBridge()
        self.bridge.health_done.connect(self._on_health_results)
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
        self.checked_log_ids: set[int] = set()
        self.log_row_checks: dict[int, QCheckBox] = {}
        self._auto_heal_cooldown: dict[str, float] = {}
        self._last_warn_time: dict[str, float] = {}
        self._latest_live_map: dict[str, str] = {}

        self.lang = normalize_language(str(self.meta.get("lang") or ""))
        self.meta["lang"] = self.lang
        self.updating_busy = False
        self.checking_plugins_busy = False
        self.latest_app_check: UpdateCheckResult | None = None
        self._silent_app_check = False
        self._startup_app_check = False

        app_ver = get_current_app_version()
        self.setWindowTitle(tr(self.lang, "app_title", ver=app_ver))
        self.setWindowIcon(create_app_icon())
        self.resize(1280, 740)

        self._build_ui()
        self._build_tray()
        self._apply_theme(self.meta.get("theme", "dark"))
        self._retranslate_ui()
        for t in self.tools:
            t.live_location_detail = resolve_disk_location(t, self.projects_map, {}, lang=self.lang)
            if not t.enabled:
                t.last_ping = tr(self.lang, "st_disabled")
                t.health_state = "off"
        self._rebuild_project_filter_combo()
        self._rebuild_profile_combo()
        self._refresh_table()
        self._refresh_plugins_tab()
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
            return self._format_scope_short(t)
        if t.project_scope == "GLOBAL":
            return tr(self.lang, "scope_global")
        p_dir = self.projects_map.get(t.project_scope, "")
        return f"{t.project_scope} ({p_dir})" if p_dir else t.project_scope

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(14, 12, 14, 10)
        main_lay.setSpacing(10)

        # 1. MINIMALIST TOP BAR: Profile combobox + Diagnostics + Settings + More (...)
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.lbl_profile = QLabel(tr(self.lang, "profile_lbl"))
        self.lbl_profile.setStyleSheet("font-weight: 600; color: #94a3b8;")
        top_bar.addWidget(self.lbl_profile)

        self.profile_cmb = QComboBox()
        self.profile_cmb.setMinimumWidth(240)
        self.profile_cmb.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.profile_cmb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_cmb.activated.connect(self._on_profile_combo_activated)
        top_bar.addWidget(self.profile_cmb)

        top_bar.addStretch()

        self.btn_diagnostics = QPushButton(tr(self.lang, "btn_diagnostics"))
        self.btn_diagnostics.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_diagnostics.clicked.connect(self.open_diagnostics)
        top_bar.addWidget(self.btn_diagnostics)

        self.btn_settings = QPushButton(tr(self.lang, "btn_settings"))
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(lambda: self.open_settings(0))
        top_bar.addWidget(self.btn_settings)

        self.btn_more = QPushButton()
        self.btn_more.setFixedSize(32, 28)
        self.btn_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_more.setToolTip(tr(self.lang, "btn_more_tip"))
        self.btn_more.clicked.connect(self._show_more_menu)
        top_bar.addWidget(self.btn_more)

        main_lay.addLayout(top_bar)

        # 2. APP UPDATE BANNER (hidden unless a newer release exists)
        self.app_update_banner = QFrame()
        self.app_update_banner.setObjectName("bannerWarn")
        ub_lay = QHBoxLayout(self.app_update_banner)
        ub_lay.setContentsMargins(12, 6, 12, 6)
        self.app_update_banner_lbl = QLabel("")
        self.app_update_banner_lbl.setStyleSheet("font-weight: 600;")
        ub_lay.addWidget(self.app_update_banner_lbl, stretch=1)

        self.app_update_notes_lbl = QLabel("")
        self.app_update_notes_lbl.setOpenExternalLinks(True)
        ub_lay.addWidget(self.app_update_notes_lbl)

        self.btn_banner_upd = QPushButton(tr(self.lang, "banner_update_now"))
        self.btn_banner_upd.setObjectName("warnBtn")
        self.btn_banner_upd.clicked.connect(lambda: self._open_app_update_dialog(self.latest_app_check))
        ub_lay.addWidget(self.btn_banner_upd)
        self.app_update_banner.hide()
        main_lay.addWidget(self.app_update_banner)

        # 3. THREE STREAMLINED TABS: Tools / Plugins / Logs
        self.tabs = QTabWidget()
        main_lay.addWidget(self.tabs, stretch=1)

        self._init_panel_tab()
        self._init_plugins_tab()
        self._init_logs_tab()

        # 4. CLEAN FOOTER BAR
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.status_lbl = QLabel(tr(self.lang, "status_ready"))
        self.status_lbl.setStyleSheet("color: #94a3b8;")
        foot.addWidget(self.status_lbl, stretch=1)

        # Conditional GPU VRAM indicator + Free VRAM button (shown only when NVIDIA GPU present)
        self.vram_bar = QProgressBar()
        self.vram_bar.setFixedWidth(180)
        self.vram_bar.setFixedHeight(19)
        self.vram_bar.setFormat("")
        self.vram_bar.hide()
        foot.addWidget(self.vram_bar)

        self.vram_lbl = QLabel("")
        self.vram_lbl.hide()

        self.btn_vram_free = QPushButton(tr(self.lang, "vram_free"))
        self.btn_vram_free.setToolTip(tr(self.lang, "vram_free_tip"))
        self.btn_vram_free.clicked.connect(self._handle_free_vram)
        self.btn_vram_free.hide()
        foot.addWidget(self.btn_vram_free)

        self.btn_do_app_upd = QPushButton(tr(self.lang, "ver_btn", ver=get_current_app_version()))
        self.btn_do_app_upd.setObjectName("ghostBtn")
        self.btn_do_app_upd.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_do_app_upd.setToolTip(tr(self.lang, "ver_btn_tip"))
        self.btn_do_app_upd.clicked.connect(lambda: self._open_app_update_dialog(self.latest_app_check))
        foot.addWidget(self.btn_do_app_upd)

        self.token_summary_lbl = QLabel()
        self.token_summary_lbl.setStyleSheet("font-family: Consolas, monospace; font-weight: 600; color: #10b981;")
        foot.addWidget(self.token_summary_lbl)
        main_lay.addLayout(foot)

    def _refresh_toolbar_icons(self) -> None:
        is_light = self.meta.get("theme", "dark") == "light"
        col = icon_color(is_light, muted=False)
        self.btn_diagnostics.setIcon(make_icon("activity", col, 15))
        self.btn_settings.setIcon(make_icon("sliders", col, 15))
        self.btn_more.setIcon(make_icon("more", col, 15))

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        act_scan = QAction(tr(self.lang, "menu_scan_now"), self)
        act_scan.triggered.connect(self.run_health_scan)
        menu.addAction(act_scan)

        act_reapply = QAction(tr(self.lang, "menu_reapply_configs"), self)
        act_reapply.triggered.connect(self._handle_sync_configs)
        menu.addAction(act_reapply)

        act_upd = QAction(tr(self.lang, "menu_check_app_update"), self)
        act_upd.triggered.connect(self._handle_quick_check_app_update)
        menu.addAction(act_upd)

        menu.addSeparator()

        act_exp = QAction(tr(self.lang, "menu_export"), self)
        act_exp.triggered.connect(self._export_settings)
        menu.addAction(act_exp)

        act_imp = QAction(tr(self.lang, "menu_import"), self)
        act_imp.triggered.connect(self._import_settings)
        menu.addAction(act_imp)

        menu.exec(self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft()))

    # --- UNIFIED PROFILE COMBOBOX ---
    def _get_custom_presets(self) -> dict[str, dict[str, Any]]:
        raw = self.meta.get("custom_presets")
        if not isinstance(raw, dict):
            raw = {}
            self.meta["custom_presets"] = raw
        return raw

    def _add_combo_header(self, cmb: QComboBox, title: str) -> None:
        model = cmb.model()
        if isinstance(model, QStandardItemModel):
            item = QStandardItem(title)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setData("__HEADER__", Qt.ItemDataRole.UserRole)
            model.appendRow(item)

    def _rebuild_profile_combo(self) -> None:
        if not hasattr(self, "profile_cmb"):
            return
        cur_active = str(self.meta.get("active_profile", "") or "")
        presets = self._get_custom_presets()

        self.profile_cmb.blockSignals(True)
        self.profile_cmb.clear()

        if not cur_active:
            self.profile_cmb.addItem(tr(self.lang, "profile_custom"), "")

        self._add_combo_header(self.profile_cmb, tr(self.lang, "profile_sec_builtin"))
        for p_key in PROFILES:
            self.profile_cmb.addItem(f"  {profile_title(p_key, self.lang)}", f"builtin:{p_key}")
            idx = self.profile_cmb.count() - 1
            self.profile_cmb.setItemData(idx, profile_desc(p_key, self.lang), Qt.ItemDataRole.ToolTipRole)

        if presets:
            self._add_combo_header(self.profile_cmb, tr(self.lang, "profile_sec_custom"))
            ordered = sorted(presets.items(), key=lambda kv: str(kv[1].get("saved_at", "")), reverse=True)
            for p_name, p_data in ordered:
                en_cnt = int(p_data.get("enabled_count", 0))
                self.profile_cmb.addItem(f"  {p_name} ({en_cnt})", f"custom:{p_name}")

        self.profile_cmb.insertSeparator(self.profile_cmb.count())
        self.profile_cmb.addItem(tr(self.lang, "profile_save_as"), "__SAVE_AS__")
        self.profile_cmb.addItem(tr(self.lang, "profile_manage"), "__MANAGE__")

        target_idx = self.profile_cmb.findData(cur_active)
        if target_idx < 0:
            target_idx = 0
        self.profile_cmb.setCurrentIndex(target_idx)
        self.profile_cmb.blockSignals(False)

    def _on_profile_combo_activated(self, idx: int) -> None:
        data = str(self.profile_cmb.itemData(idx) or "")
        if not data or data == "__HEADER__":
            self._rebuild_profile_combo()
            return
        if data == "__SAVE_AS__":
            self._save_custom_preset()
            self._rebuild_profile_combo()
            return
        if data == "__MANAGE__":
            ManageProfilesDialog(self).exec()
            self._rebuild_profile_combo()
            return
        if data == self.meta.get("active_profile"):
            return
        if data.startswith("builtin:"):
            self.apply_builtin_profile(data.split(":", 1)[1], ask_confirm=True)
        elif data.startswith("custom:"):
            self.apply_custom_preset(data.split(":", 1)[1])

    def apply_builtin_profile(self, profile_key: str, ask_confirm: bool = True) -> None:
        if profile_key not in PROFILES:
            return
        title = profile_title(profile_key, self.lang)
        # Only ask confirmation if user currently has an unsaved custom setup with enabled tools
        has_custom_active = (not self.meta.get("active_profile")) and any(t.enabled for t in self.tools)
        if ask_confirm and has_custom_active:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle(tr(self.lang, "prof_confirm_title"))
            msg_box.setText(f"<b>{tr(self.lang, 'prof_confirm_hdr', name=title)}</b>")
            msg_box.setInformativeText(tr(self.lang, "prof_confirm_body"))
            btn_save_go = msg_box.addButton(tr(self.lang, "prof_btn_save_switch"), QMessageBox.ButtonRole.AcceptRole)
            btn_just_go = msg_box.addButton(tr(self.lang, "prof_btn_switch"), QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = msg_box.addButton(tr(self.lang, "btn_cancel"), QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(btn_save_go)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked == btn_cancel or clicked is None:
                self._rebuild_profile_combo()
                return
            if clicked == btn_save_go:
                if not self._save_custom_preset():
                    self._rebuild_profile_combo()
                    return

        target_enable = set(PROFILES[profile_key]["enable"])
        for t in self.tools:
            t.enabled = t.id in target_enable

        self.meta["active_profile"] = f"builtin:{profile_key}"
        self.meta["first_run_dismissed"] = True
        self._refresh_first_run_banner()
        self._save_state()
        self._rebuild_profile_combo()

        en_cnt = sum(1 for t in self.tools if t.enabled)
        msg = tr(self.lang, "msg_profile_applied", name=title, n=en_cnt)
        self.logs.add("INFO", "Profile", msg)
        self.set_status(msg)
        self._refresh_table()
        self._refresh_logs_tab()
        self._sync_live_environment_async(target_tools=list(self.tools))

    def _save_custom_preset(self) -> bool:
        cur_active = str(self.meta.get("active_profile", "") or "")
        cur_name = cur_active.split(":", 1)[1] if cur_active.startswith("custom:") else ""
        default_name = cur_name or next(iter(self.projects_map.keys()), "") or tr(self.lang, "prof_default_name")
        name, ok = QInputDialog.getText(
            self,
            tr(self.lang, "prof_save_title"),
            tr(self.lang, "prof_save_prompt"),
            text=default_name,
        )
        if not ok:
            return False
        name = name.strip()
        if not name:
            QMessageBox.warning(self, tr(self.lang, "prof_invalid_name_title"), tr(self.lang, "prof_invalid_name_msg"))
            return False

        presets = self._get_custom_presets()
        if name in presets and name != cur_name:
            ans = QMessageBox.question(
                self,
                tr(self.lang, "prof_overwrite_title"),
                tr(self.lang, "prof_overwrite_msg", name=name),
            )
            if ans != QMessageBox.StandardButton.Yes:
                return False

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
        self.meta["active_profile"] = f"custom:{name}"
        self._save_state()
        self._rebuild_profile_combo()
        self._rebuild_tray_menu()
        msg = tr(self.lang, "msg_profile_saved", name=name)
        self.logs.add("INFO", "Profile", msg)
        self.set_status(msg)
        self._refresh_logs_tab()
        return True

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
                    sc = str(saved["project_scope"])
                    t.project_scope = sc if (sc == "GLOBAL" or sc in self.projects_map) else "GLOBAL"
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

        self.meta["active_profile"] = f"custom:{name}"
        self.meta["first_run_dismissed"] = True
        self._refresh_first_run_banner()
        self._save_state()
        self._rebuild_profile_combo()

        en_cnt = sum(1 for t in self.tools if t.enabled)
        msg = tr(self.lang, "msg_profile_applied", name=name, n=en_cnt)
        self.logs.add("INFO", "Profile", msg)
        self.set_status(msg)
        self._refresh_table()
        self._refresh_plugins_tab()
        self._refresh_logs_tab()
        self._sync_live_environment_async(target_tools=list(self.tools))

    # --- SYSTEM TRAY (LOCALIZED & RESPECTS minimize_to_tray) ---
    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(create_app_icon(), self)
        self.tray.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self._rebuild_tray_menu()
        self.tray.show()

    def _rebuild_tray_menu(self) -> None:
        if not getattr(self, "tray", None):
            return
        self.tray.setToolTip(tr(self.lang, "tray_tooltip"))
        menu = QMenu()

        act_open = QAction(tr(self.lang, "tray_open"), self)
        act_open.triggered.connect(self._restore_from_tray)
        menu.addAction(act_open)
        menu.addSeparator()

        prof_menu = menu.addMenu(tr(self.lang, "tray_profiles"))
        for p_key in PROFILES:
            act_p = QAction(profile_title(p_key, self.lang), self)
            act_p.triggered.connect(lambda _=False, k=p_key: self.apply_builtin_profile(k, ask_confirm=False))
            prof_menu.addAction(act_p)

        presets = self._get_custom_presets()
        if presets:
            prof_menu.addSeparator()
            for p_name in sorted(presets.keys()):
                act_c = QAction(p_name, self)
                act_c.triggered.connect(lambda _=False, nm=p_name: self.apply_custom_preset(nm))
                prof_menu.addAction(act_c)

        menu.addSeparator()
        act_app_upd = QAction(tr(self.lang, "tray_check_app"), self)
        act_app_upd.triggered.connect(lambda: (self._restore_from_tray(), self._handle_quick_check_app_update()))
        menu.addAction(act_app_upd)

        act_upd_all = QAction(tr(self.lang, "tray_check_plugins"), self)
        act_upd_all.triggered.connect(lambda: self.run_plugin_update_check(manual=True))
        menu.addAction(act_upd_all)

        act_vram = QAction(tr(self.lang, "tray_free_vram"), self)
        act_vram.triggered.connect(self._handle_free_vram)
        menu.addAction(act_vram)

        menu.addSeparator()
        act_quit = QAction(tr(self.lang, "tray_quit"), self)
        act_quit.triggered.connect(self._quit_app)
        menu.addAction(act_quit)

        self._tray_menu = menu
        self.tray.setContextMenu(menu)

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
        minimize_to_tray = bool(self.meta.get("minimize_to_tray", True))
        if not self.force_quit and minimize_to_tray and self.tray and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self.tray_notified:
                self.tray.showMessage(
                    tr(self.lang, "tray_bg_title"),
                    tr(self.lang, "tray_bg_msg"),
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
                self.tray_notified = True
            return
        self.table.detach_filter()
        self.log_table.detach_filter()
        super().closeEvent(event)

    # --- STATE, THEME, LANGUAGE ---
    def set_status(self, msg: str) -> None:
        self.status_lbl.setText(msg)

    def _save_state(self) -> None:
        self.meta["sort_key"] = self.sort_key
        self.meta["sort_desc"] = self.sort_desc
        if self.plugin_checks:
            self.meta["plugin_checked_ids"] = [tid for tid, cb in self.plugin_checks.items() if cb.isChecked()]
        self.store.save(self.tools, self.active_skills, self.meta, self.default_ids)

    def set_theme(self, mode: str) -> None:
        if mode not in ("dark", "light"):
            return
        self._apply_theme(mode)
        self._refresh_table()
        self._refresh_plugins_tab()
        self._save_state()

    def set_language(self, code: str) -> None:
        norm = normalize_language(code)
        if norm == self.lang:
            return
        self.lang = norm
        self.meta["lang"] = norm
        for t in self.tools:
            t.last_ping = tr(self.lang, "st_disabled") if not t.enabled else tr(self.lang, "st_scanning")
            t.live_location_detail = resolve_disk_location(t, self.projects_map, {}, lang=self.lang)
        self._save_state()
        self._retranslate_ui()
        self._rebuild_kind_filter_combo()
        self._rebuild_project_filter_combo()
        self._rebuild_profile_combo()
        self._rebuild_tray_menu()
        self._refresh_first_run_banner()
        self._refresh_host_dep_banner()
        self._refresh_table()
        self._refresh_plugins_tab()
        self._refresh_logs_tab()
        self.run_health_scan()
        lang_lbl = dict(SUPPORTED_LANGUAGES).get(norm, norm)
        self.set_status(tr(self.lang, "msg_lang_changed", lang=lang_lbl))

    def _update_tab_titles(self) -> None:
        if not hasattr(self, "tabs") or self.tabs.count() < 3:
            return
        self.tabs.setTabText(0, tr(self.lang, "tab_tools", n=len(self.tools)))
        upd_cnt = sum(1 for t in self.tools if t.has_update)
        if upd_cnt > 0:
            key = "tab_plugins_upd_one" if upd_cnt == 1 else "tab_plugins_upd"
            self.tabs.setTabText(1, tr(self.lang, key, n=upd_cnt))
        else:
            self.tabs.setTabText(1, tr(self.lang, "tab_plugins"))
        counts = self.logs.counts_by_level()
        if counts["ERR"] > 0 or counts["WARN"] > 0:
            self.tabs.setTabText(2, tr(self.lang, "tab_logs_counts", err=counts["ERR"], warn=counts["WARN"]))
        else:
            self.tabs.setTabText(2, tr(self.lang, "tab_logs"))

    def _retranslate_ui(self) -> None:
        app_ver = get_current_app_version()
        self.setWindowTitle(tr(self.lang, "app_title", ver=app_ver))
        self.lbl_profile.setText(tr(self.lang, "profile_lbl"))
        self.btn_diagnostics.setText(tr(self.lang, "btn_diagnostics"))
        self.btn_settings.setText(tr(self.lang, "btn_settings"))
        self.btn_more.setToolTip(tr(self.lang, "btn_more_tip"))
        self.btn_banner_upd.setText(tr(self.lang, "banner_update_now"))
        self.btn_vram_free.setText(tr(self.lang, "vram_free"))
        self.btn_vram_free.setToolTip(tr(self.lang, "vram_free_tip"))
        if not (self.latest_app_check and self.latest_app_check.has_update):
            self.btn_do_app_upd.setText(tr(self.lang, "ver_btn", ver=app_ver))
        self.btn_do_app_upd.setToolTip(tr(self.lang, "ver_btn_tip"))

        self.search_inp.setPlaceholderText(tr(self.lang, "search_ph"))
        self.btn_plug_sel_all.setText(tr(self.lang, "plug_sel_all"))
        self.btn_plug_clr_all.setText(tr(self.lang, "plug_clr_all"))
        self.btn_plugins_check.setText(tr(self.lang, "plug_check"))
        self.btn_plugins_install_sel.setText(tr(self.lang, "plug_upd_sel"))
        self.btn_add_github.setText(tr(self.lang, "plug_add_github"))
        self.btn_jump_err_logs.setText(tr(self.lang, "plug_btn_view_errs"))
        upd_cnt = sum(1 for t in self.tools if t.has_update)
        if self.checking_plugins_busy:
            self.plugins_banner_lbl.setText(tr(self.lang, "plug_banner_checking"))
        elif upd_cnt > 0:
            self.plugins_banner_lbl.setText(tr(self.lang, "plug_banner_updates", n=upd_cnt))
        else:
            self.plugins_banner_lbl.setText(tr(self.lang, "plug_banner_all_ok"))

        self.lbl_log_level.setText(tr(self.lang, "log_level_lbl"))
        if self.log_lvl_cmb.count() > 0:
            self.log_lvl_cmb.setItemText(0, tr(self.lang, "log_level_all"))
        self.log_search_inp.setPlaceholderText(tr(self.lang, "log_search_ph"))
        self.btn_log_wipe.setText(tr(self.lang, "log_clear_all"))
        self.btn_log_all.setText(tr(self.lang, "log_sel_all"))
        self.btn_log_err.setText(tr(self.lang, "log_sel_issues"))
        self.btn_log_clr.setText(tr(self.lang, "log_sel_clear"))
        self.log_raw_view.setPlaceholderText(tr(self.lang, "log_raw_ph"))
        self._update_log_headers()
        self._update_log_selection_ui()
        self._update_panel_header_indicators()
        self._update_tab_titles()

    def _apply_theme(self, mode: str) -> None:
        self.meta["theme"] = mode
        app = QApplication.instance()
        if app is not None:
            app.setStyle(MinimalStyle(is_light=(mode == "light")))
        self.setStyleSheet(get_stylesheet(mode))
        self._refresh_toolbar_icons()
        if hasattr(self, "bulk_client_btns"):
            self._update_bulk_client_buttons()

    # --- LIVE SYNC & TOOL CONTROLS ---
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

        tools_snap = copy.deepcopy(self.tools)
        skills_snap = set(self.active_skills)
        proj_snap = dict(self.projects_map)
        lang_snap = self.lang

        def worker() -> None:
            with self._sync_lock:
                for t_obj in tools_snap:
                    if t_obj.id in target_ids:
                        enforce_tool_runtime_state(t_obj, proj_snap, allow_stop=(t_obj.id in stop_ids), lang=lang_snap)
                bs_tool = next((x for x in tools_snap if x.id == "blender_skills"), None)
                if bs_tool:
                    sync_blender_skills_on_disk(
                        skills_snap, bs_tool.enabled, bs_tool.project_scope, proj_snap, lang=lang_snap
                    )
                sync_mcp_json_clients(tools_snap, self.vault, proj_snap)
                live_map = scan_live_process_locations(lang=lang_snap)
                out = []
                for x in tools_snap:
                    ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                        x, len(skills_snap), proj_snap, live_map, lang=lang_snap
                    )
                    out.append((x.id, ok, h_state, ping_str, ms, detail, loc_detail))
            safe_emit(self.bridge.health_done, out, live_map, True)

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_tool(self, tool: ToolSpec) -> None:
        tool.enabled = not tool.enabled
        self.meta["active_profile"] = ""
        self.meta["first_run_dismissed"] = True
        self._refresh_first_run_banner()
        self._rebuild_profile_combo()
        if not tool.enabled:
            tool.health_state = "off"
            tool.last_ping = tr(self.lang, "st_disabled")
        self._save_state()
        state_word = tr(self.lang, "client_on" if tool.enabled else "client_off").lower()
        self.logs.add("DBG", tool.name, f"Toggled -> {'ON' if tool.enabled else 'OFF'}")
        self.set_status(tr(self.lang, "msg_tool_toggled", name=tool.name, state=state_word))
        self._refresh_table()
        self._refresh_logs_tab()
        self._update_vram_visibility()
        self._sync_live_environment_async(target_tools=[tool])

    def _toggle_client(self, tool: ToolSpec, client_code: str, checked: bool) -> None:
        tool.clients[client_code] = checked
        self.meta["active_profile"] = ""
        self._rebuild_profile_combo()
        self._save_state()
        state_word = tr(self.lang, "client_on" if checked else "client_off").lower()
        self.set_status(tr(self.lang, "msg_client_toggled", name=tool.name, code=client_code, state=state_word))
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
                    "background-color: #2563eb; color: #ffffff; border: 1px solid #60a5fa; "
                    "border-radius: 5px; font-size: 10px; font-weight: 700; padding: 0px;"
                )
            elif on_cnt > 0:
                btn.setStyleSheet(
                    "background-color: #dbeafe; color: #1d4ed8; border: 1px dashed #2563eb; "
                    "border-radius: 5px; font-size: 10px; font-weight: 700; padding: 0px;"
                    if is_light
                    else "background-color: #172554; color: #bfdbfe; border: 1px dashed #3b82f6; "
                    "border-radius: 5px; font-size: 10px; font-weight: 700; padding: 0px;"
                )
            else:
                btn.setStyleSheet(
                    "background-color: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; "
                    "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                    if is_light
                    else "background-color: #0c1117; color: #64748b; border: 1px solid #263549; "
                    "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                )
            btn.setToolTip(
                tr(self.lang, "bulk_client_tip", full=full_lbl, code=code, on=on_cnt, tot=total)
            )

    def _toggle_client_all(self, client_code: str, mode: str = "auto") -> None:
        if mode == "auto":
            any_on = any(t.clients.get(client_code, False) for t in self.tools)
            target_state = not any_on
            for t in self.tools:
                t.clients[client_code] = target_state
        elif mode == "all_on":
            for t in self.tools:
                t.clients[client_code] = True
        elif mode == "active_only":
            for t in self.tools:
                t.clients[client_code] = bool(t.enabled)
        else:
            for t in self.tools:
                t.clients[client_code] = False

        self.meta["active_profile"] = ""
        self._rebuild_profile_combo()
        self._save_state()
        msg = tr(self.lang, "msg_bulk_client", code=client_code)
        self.logs.add("INFO", f"Clients ({client_code})", msg)
        self.set_status(msg)
        self._refresh_table()
        self._refresh_logs_tab()
        self._sync_live_environment_async(target_tools=[])

    def _show_bulk_client_menu(self, client_code: str, btn: QPushButton, pos: Any) -> None:
        menu = QMenu(self)
        act_all_on = QAction(tr(self.lang, "bulk_all_on", code=client_code), self)
        act_act_on = QAction(tr(self.lang, "bulk_active_only", code=client_code), self)
        act_all_off = QAction(tr(self.lang, "bulk_all_off", code=client_code), self)
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
        modes = localized_tool_modes(tool, self.lang)
        mode_lbl = modes[idx] if 0 <= idx < len(modes) else ""
        self.set_status(tr(self.lang, "msg_mode_changed", name=tool.name, mode=mode_lbl))

    # --- DIALOG LAUNCHERS ---
    def open_gear(self, tool: ToolSpec) -> None:
        if tool.gear_kind == "skills94":
            saved_chk = set(self.meta.get("checked_blender_skills", []))
            dlg = BlenderSkillsDialog(self, self.active_skills, saved_chk, lang=self.lang)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.saved_result is not None:
                self.active_skills = dlg.saved_result
                self.meta["checked_blender_skills"] = sorted(dlg.saved_checked)
                tool.enabled = len(self.active_skills) > 0
                ok, disk_msg = sync_blender_skills_on_disk(
                    self.active_skills,
                    tool.enabled,
                    tool.project_scope,
                    self.projects_map,
                    lang=self.lang,
                )
                self._save_state()
                self.logs.add("INFO" if ok else "DBG", tool.name, f"Saved {len(self.active_skills)}/94 skills.", disk_msg)
                self.set_status(tr(self.lang, "msg_skills_saved", on=len(self.active_skills), detail=disk_msg))
                self._refresh_table()
                self._refresh_logs_tab()
        else:
            dlg = ToolGearDialog(self, tool, self._format_scope_display(tool))
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._save_state()
                self.logs.add("INFO", tool.name, "Tool settings saved.")
                self.set_status(tr(self.lang, "msg_gear_saved", name=tool.name))
                self._refresh_table()
                self._refresh_logs_tab()
                self._sync_live_environment_async(target_tools=[tool])

    def open_settings(self, initial_tab: int = 0) -> None:
        dlg = SettingsDialog(self, initial_tab=initial_tab)
        dlg.exec()

    def open_diagnostics(self) -> None:
        dlg = DiagnosticsDialog(self)
        dlg.exec()

    # --- PERIODIC WATCHERS & HEALTH SCAN ---
    def _on_second_tick(self) -> None:
        self.seconds_left -= 1
        if self.seconds_left <= 0:
            self.run_health_scan()
        elif self.seconds_left % 3 == 0:
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
        lang_snap = self.lang

        def worker() -> None:
            try:
                live_map = scan_live_process_locations(lang=lang_snap)
                out = []
                for t in snap_tools:
                    ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                        t, sk_cnt, proj_snap, live_map, lang=lang_snap
                    )
                    out.append((t.id, ok, h_state, ping_str, ms, detail, loc_detail))
                safe_emit(self.bridge.health_done, out, live_map, True)
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
                safe_emit(self.bridge.vram_done, name, used_mb, total_mb)

        threading.Thread(target=worker, daemon=True).start()

    def _update_vram_visibility(self) -> None:
        trellis_on = any(t.id == "trellis" and t.enabled for t in self.tools)
        trellis_running = bool(self.last_detected_apps.get("trellis_server")) or ("trellis" in self._latest_live_map)
        show_vram = self._has_nvidia_gpu and (trellis_on or trellis_running)
        self.vram_bar.setVisible(show_vram)
        self.btn_vram_free.setVisible(show_vram)

    def _on_vram_done(self, name: str, used_mb: int, total_mb: int) -> None:
        self._vram_busy = False
        self._has_nvidia_gpu = total_mb > 0
        if total_mb > 0:
            self.vram_bar.setMaximum(total_mb)
            self.vram_bar.setValue(used_mb)
            short_gpu = name.replace("NVIDIA GeForce ", "")
            fmt = f"{short_gpu}: {used_mb / 1024:.1f} / {total_mb / 1024:.1f} GB"
            self.vram_bar.setFormat(fmt)
            self.vram_lbl.setText(fmt)
        else:
            self.vram_bar.setMaximum(100)
            self.vram_bar.setValue(0)
            self.vram_bar.setFormat("")
            self.vram_lbl.setText("")
        self._update_vram_visibility()

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
                safe_emit(self.bridge.dcc_done, cur)

        threading.Thread(target=worker, daemon=True).start()

    def _on_dcc_done(self, cur: dict[str, bool]) -> None:
        self._dcc_busy = False
        if cur.get("unity") and not self.last_detected_apps.get("unity"):
            self.set_status(
                tr(self.lang, "msg_dcc_detected", app="Unity Editor", prof=profile_title("unity_game", self.lang))
            )
        elif cur.get("blender") and not self.last_detected_apps.get("blender"):
            self.set_status(
                tr(self.lang, "msg_dcc_detected", app="Blender", prof=profile_title("asset_3d", self.lang))
            )
        self.last_detected_apps = cur
        self._update_vram_visibility()

    def run_health_scan(self) -> None:
        self.seconds_left = 30
        if self._health_busy:
            return
        self._health_busy = True
        self.set_status(tr(self.lang, "msg_scanning"))
        snap_tools = copy.deepcopy(self.tools)
        sk_cnt = len(self.active_skills)
        proj_snap = dict(self.projects_map)
        lang_snap = self.lang

        def worker() -> None:
            out = []
            live_map: dict[str, str] = {}
            try:
                live_map = scan_live_process_locations(lang=lang_snap)
                for t in snap_tools:
                    ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                        t, sk_cnt, proj_snap, live_map, lang=lang_snap
                    )
                    out.append((t.id, ok, h_state, ping_str, ms, detail, loc_detail))
            finally:
                self._health_busy = False
            safe_emit(self.bridge.health_done, out, live_map, False)

        threading.Thread(target=worker, daemon=True).start()

    def _on_health_results(
        self,
        results: list[tuple[str, bool, str, str, int, str, str]],
        live_map: dict[str, str] | None = None,
        silent: bool = False,
    ) -> None:
        if isinstance(live_map, dict):
            self._latest_live_map = live_map
        by_id = {t.id: t for t in self.tools}
        state_changed = False

        for tid, ok, h_state, ping_str, ms, detail, loc_detail in results:
            if tid in by_id:
                t = by_id[tid]
                if t.health_state != h_state or t.live_location_detail != loc_detail or (
                    h_state != "ok" and t.last_ping != ping_str
                ):
                    state_changed = True
                t.health_state = h_state
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
                        self.logs.add("WARN", t.name, f"Service not responding ({ping_str})", detail, t.port)

        self._update_vram_visibility()
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
        self.set_status(tr(self.lang, "msg_scan_done"))

    def _refresh_host_dep_banner(self) -> None:
        if not hasattr(self, "host_dep_banner"):
            return
        missing = get_missing_host_dependencies(self.tools, self._latest_live_map, self.projects_map, lang=self.lang)
        while self.host_dep_btns_lay.count():
            item = self.host_dep_btns_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not missing:
            self.host_dep_banner.hide()
            return

        titles = "  |  ".join(m["title"] for m in missing)
        self.host_dep_lbl.setText(tr(self.lang, "banner_host_missing", titles=titles))
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
            headless=bool(dep_info.get("headless", False)),
            trellis_root=tr_tool.param_value if tr_tool else "",
            lang=self.lang,
        )
        self.logs.add("INFO" if ok else "WARN", "Host App", msg)
        self.set_status(msg)
        self._refresh_logs_tab()
        QTimer.singleShot(2500, self.run_health_scan)

    def _auto_heal_tool_async(self, tool: ToolSpec) -> None:
        tool_snap = copy.deepcopy(tool)
        proj_snap = dict(self.projects_map)
        sk_cnt = len(self.active_skills)
        lang_snap = self.lang

        def worker() -> None:
            note = enforce_tool_runtime_state(tool_snap, proj_snap, allow_stop=False, lang=lang_snap)
            if note:
                self.logs.add("INFO", tool_snap.name, f"Auto-heal:{note}")
                time.sleep(1.5)
                live_map = scan_live_process_locations(lang=lang_snap)
                ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                    tool_snap, sk_cnt, proj_snap, live_map, lang=lang_snap
                )
                safe_emit(
                    self.bridge.health_done,
                    [(tool_snap.id, ok, h_state, ping_str, ms, detail, loc_detail)],
                    live_map,
                    True,
                )

        threading.Thread(target=worker, daemon=True).start()

    def _handle_free_vram(self) -> None:
        ok, msg = free_trellis_vram(lang=self.lang)
        self.logs.add("INFO" if ok else "WARN", "TRELLIS", msg)
        self._update_vram_bar()
        self._refresh_logs_tab()
        self.set_status(msg)

    def _handle_kill_zombie_port(self, port: int, parent_widget: QWidget | None = None) -> None:
        owner_pid, owner_name = find_port_owner(port)
        if owner_pid:
            ans = QMessageBox.question(
                parent_widget or self,
                tr(self.lang, "diag_port_confirm_title"),
                tr(self.lang, "diag_port_confirm_msg", port=port, name=owner_name, pid=owner_pid),
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.set_status(tr(self.lang, "msg_port_cleaning", port=port))
        lang_snap = self.lang

        def worker() -> None:
            ok, msg = False, ""
            try:
                ok, msg = kill_zombie_port_process(port, lang=lang_snap)
            except Exception as exc:
                msg = f"Port :{port} error: {exc}"
            finally:
                safe_emit(self.bridge.port_kill_done, port, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_port_kill_done(self, port: int, _ok: bool, msg: str) -> None:
        self.logs.add("INFO", f"Port :{port}", msg, msg, port)
        self._refresh_logs_tab()
        self.set_status(msg)
        QTimer.singleShot(500, self.run_health_scan)

    # --- CONFIG SYNC & IMPORT / EXPORT ---
    def _handle_sync_configs(self) -> None:
        bs_tool = next((t for t in self.tools if t.id == "blender_skills"), None)
        if bs_tool:
            sync_blender_skills_on_disk(
                self.active_skills, bs_tool.enabled, bs_tool.project_scope, self.projects_map, lang=self.lang
            )
        msgs = sync_mcp_json_clients(self.tools, self.vault, self.projects_map)
        summary = " | ".join(msgs) if msgs else "No client config files found."
        self.logs.add("INFO", "Config Sync", summary)
        self._refresh_logs_tab()
        self.set_status(tr(self.lang, "msg_configs_synced", summary=summary))
        home = pathlib.Path.home()
        paths_info = (
            f"{summary}\n\n"
            f"AGY: {home / '.gemini' / 'config' / 'mcp_config.json'}\n"
            f"CDX: {home / '.codex' / 'config.toml'}\n"
            f"CLD: {home / '.claude.json'} (+ <project>/.mcp.json)\n"
            f"CUR: {home / '.cursor' / 'mcp.json'} (+ <project>/.cursor/mcp.json)\n"
            f"State: {self.store.state_file}"
        )
        QMessageBox.information(self, tr(self.lang, "msg_configs_synced_title"), paths_info)

    def _export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr(self.lang, "menu_export"),
            "aiconomy-settings.json",
            "AIconomy Settings (*.json *.aiconomy *.aihub)",
        )
        if not path:
            return
        self.export_to_file(pathlib.Path(path))
        self.set_status(tr(self.lang, "msg_exported", path=path))

    def export_to_file(self, target_path: pathlib.Path) -> None:
        self._save_state()
        payload = self.store.serialize(self.tools, self.active_skills, self.meta, self.default_ids)
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr(self.lang, "menu_import"),
            "",
            "AIconomy Settings (*.json *.aiconomy *.aihub)",
        )
        if not path:
            return
        try:
            self.import_from_file(pathlib.Path(path))
            self.set_status(tr(self.lang, "msg_imported", path=path))
            QMessageBox.information(self, tr(self.lang, "msg_import_ok_title"), tr(self.lang, "msg_import_ok_msg"))
        except Exception as exc:
            QMessageBox.warning(self, tr(self.lang, "msg_import_err_title"), tr(self.lang, "msg_import_err_msg", err=exc))

    def import_from_file(self, source_path: pathlib.Path) -> None:
        txt = source_path.read_text(encoding="utf-8")
        json.loads(txt)
        self.store.state_file.write_text(txt, encoding="utf-8")
        self.tools = build_default_catalog()
        self.active_skills, self.meta = self.store.load_into(self.tools)

        self.sort_key = str(self.meta.get("sort_key", "enabled"))
        self.sort_desc = bool(self.meta.get("sort_desc", True))
        self.lang = normalize_language(str(self.meta.get("lang") or self.lang))
        self.meta["lang"] = self.lang
        self._apply_theme(self.meta.get("theme", "dark"))

        for t in self.tools:
            t.live_location_detail = resolve_disk_location(t, self.projects_map, {}, lang=self.lang)

        bs_tool = next((t for t in self.tools if t.id == "blender_skills"), None)
        if bs_tool:
            sync_blender_skills_on_disk(
                self.active_skills, bs_tool.enabled, bs_tool.project_scope, self.projects_map, lang=self.lang
            )

        self._retranslate_ui()
        self._rebuild_kind_filter_combo()
        self._rebuild_project_filter_combo()
        self._rebuild_profile_combo()
        self._rebuild_tray_menu()
        self._refresh_first_run_banner()
        self._refresh_table()
        self._refresh_plugins_tab()
        self.run_health_scan()

    # --- APP SELF-UPDATER ---
    def _apply_app_update_visual_state(self, res: UpdateCheckResult) -> None:
        if res.ok and res.has_update:
            self.btn_do_app_upd.setText(tr(self.lang, "ver_btn_update", remote=res.remote_version))
            self.btn_do_app_upd.setObjectName("warnBtn")
            self.app_update_banner_lbl.setText(
                tr(self.lang, "banner_app_update", local=res.local_version, remote=res.remote_version)
            )
            if res.release_notes_url:
                self.app_update_notes_lbl.setText(
                    f"<a style='color:#93c5fd; font-weight:600;' href='{res.release_notes_url}'>{tr(self.lang, 'banner_release_notes')}</a>"
                )
            self.app_update_banner.show()
        elif res.ok:
            self.btn_do_app_upd.setText(tr(self.lang, "ver_btn", ver=res.local_version))
            self.btn_do_app_upd.setObjectName("ghostBtn")
            self.app_update_banner.hide()

        self.style().unpolish(self.btn_do_app_upd)
        self.style().polish(self.btn_do_app_upd)

    def _run_startup_app_update_check(self) -> None:
        repo = resolve_effective_app_repo(str(self.meta.get("app_update_repo", "")))
        if not repo:
            return
        tok = self.vault.get_secret("GITHUB_TOKEN")
        self._startup_app_check = True

        lang_snap = self.lang

        def worker() -> None:
            res = check_for_app_updates(repo, tok, lang=lang_snap)
            safe_emit(self.bridge.app_check_done, res)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_quick_check_app_update(self) -> None:
        if self.latest_app_check and self.latest_app_check.has_update:
            self._open_app_update_dialog(self.latest_app_check)
            return
        repo = resolve_effective_app_repo(str(self.meta.get("app_update_repo", "")))
        self.set_status(tr(self.lang, "msg_app_checking"))
        tok = self.vault.get_secret("GITHUB_TOKEN")
        self._silent_app_check = True

        lang_snap = self.lang

        def worker() -> None:
            res = check_for_app_updates(repo, tok, lang=lang_snap)
            safe_emit(self.bridge.app_check_done, res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_bg_app_check_done(self, res: UpdateCheckResult) -> None:
        self.latest_app_check = res
        self._apply_app_update_visual_state(res)

        if self._startup_app_check:
            self._startup_app_check = False
            if res.ok and res.has_update:
                self.set_status(
                    tr(self.lang, "msg_app_update_found", local=res.local_version, remote=res.remote_version)
                )
            return

        if not self._silent_app_check:
            return
        self._silent_app_check = False
        if res.has_update:
            self.set_status(
                tr(self.lang, "msg_app_update_found", local=res.local_version, remote=res.remote_version)
            )
            self._open_app_update_dialog(res)
        elif res.ok:
            self.set_status(tr(self.lang, "msg_app_up_to_date", ver=res.local_version))
        else:
            self.set_status(res.message)

    def _open_app_update_dialog(self, initial_res: UpdateCheckResult | None = None) -> None:
        self._silent_app_check = False
        self._startup_app_check = False
        dlg = AppUpdateDialog(self, initial_res)
        dlg.exec()
