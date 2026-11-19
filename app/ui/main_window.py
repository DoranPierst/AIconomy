"""Main application window orchestrator for AIconomy (modular mixins, adaptive sleep, EN & TR)."""
from __future__ import annotations

import copy
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
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..catalog import (
    AI_CLIENTS,
    DEFAULT_ACTIVE_BLENDER_SKILLS,
    ToolSpec,
    build_default_catalog,
    get_default_tool_spec,
    profile_title,
)
from ..diagnostics import measure_tool_schema_tokens
from ..host_apps import get_missing_host_dependencies, launch_host_app_for_tool
from ..i18n import SUPPORTED_LANGUAGES, normalize_language, tr
from ..mcp_config import (
    detect_installed_ai_clients,
    sync_blender_skills_on_disk,
    sync_caveman_on_disk,
    sync_custom_skill_tools_on_disk,
    sync_mcp_json_clients,
)
from ..oauth import supports_oauth
from ..plugins import can_uninstall_tool_from_disk, uninstall_library_tool
from ..processes import (
    detect_running_dcc_apps,
    enforce_tool_runtime_state,
    find_port_owner,
    free_trellis_vram,
    has_running_ai_client_processes,
    has_running_managed_services,
    kill_zombie_port_process,
    probe_tool_health,
    query_gpu_vram,
    resolve_disk_location,
    scan_live_process_locations,
    stop_all_managed_services,
    wait_for_started_ports,
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
from ..tokens import schema_cache_key
from ..updater import UpdateCheckResult, get_current_app_version
from .dialogs import (
    BlenderSkillsDialog,
    DiagnosticsDialog,
    SettingsDialog,
    TokenBreakdownDialog,
    ToolGearDialog,
)
from .icons import icon_color, make_icon
from .mixins import ProfilesMixin, TrayUpdaterMixin
from .tabs import LogsTabMixin, PluginsTabMixin, ToolsTabMixin
from .theme import MinimalStyle, create_app_icon, get_stylesheet
from .workers import WorkerBridge, safe_emit


class MainWindow(ToolsTabMixin, PluginsTabMixin, LogsTabMixin, ProfilesMixin, TrayUpdaterMixin, QMainWindow):
    """Streamlined desktop control center for MCP servers, skills, OAuth/DPAPI vault, and token budgets."""

    def __init__(self, data_dir: pathlib.Path, sync_live_environment: bool = True) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.sync_live_environment = sync_live_environment
        migrate_legacy_data_files(self.data_dir)

        self.vault = WindowsDpapiVault(self.data_dir / VAULT_FILENAME)
        self.logs = LogDatabase(self.data_dir / LOG_DB_FILENAME, vault=self.vault)
        self.store = StateStore(self.data_dir / STATE_FILENAME)

        self.tools: list[ToolSpec] = build_default_catalog()
        self.default_ids: set[str] = {t.id for t in self.tools}
        self.active_skills, self.meta = self.store.load_into(self.tools)
        self.installed_clients: set[str] = detect_installed_ai_clients()

        self.sort_key = str(self.meta.get("sort_key", "enabled"))
        if self.sort_key not in ("name", "project", "ping", "enabled"):
            self.sort_key = "enabled"
        self.sort_desc = bool(self.meta.get("sort_desc", True))
        self.seconds_left = 30
        self._tray_sleep_ticks = 0
        self._no_client_seconds = 0
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
        self.bridge.runtime_transition_done.connect(self._on_runtime_transition_done)
        self.bridge.lib_install_progress.connect(self._on_lib_install_progress)
        self.bridge.lib_install_item_done.connect(self._on_lib_install_item_done)
        self.bridge.lib_install_all_done.connect(self._on_lib_install_all_done)
        self.bridge.lib_uninstall_done.connect(self._on_lib_uninstall_done)
        self.bridge.schema_measure_done.connect(self._on_bg_schema_measure_done)
        self._installing_tool_ids: set[str] = set()
        self._uninstalling_tool_ids: set[str] = set()

        self.runtime_started = False
        self._runtime_state = "probing"  # probing | stopped | starting | running | stopping
        self._health_busy = False
        self._vram_busy = False
        self._dcc_busy = False
        self._sync_lock = threading.Lock()
        self._sync_pending_ids: set[str] = set()
        self._sync_stop_ids: set[str] = set()
        self._sync_restart_ids: set[str] = set()
        self._sync_debounce = QTimer(self)
        self._sync_debounce.setSingleShot(True)
        self._sync_debounce.setInterval(400)
        self._sync_debounce.timeout.connect(self._flush_live_sync)

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
            if not getattr(t, "in_workspace", True):
                t.enabled = False
                t.last_ping = tr(self.lang, "st_disabled")
                t.health_state = "off"
                continue
            t.live_location_detail = resolve_disk_location(t, self.projects_map, {}, lang=self.lang)
            if not t.enabled:
                t.last_ping = tr(self.lang, "st_disabled")
                t.health_state = "off"
            elif self._tool_needs_vault_key(t):
                t.last_ping = tr(self.lang, "st_missing_key")
                t.health_state = "warn"
        self._rebuild_project_filter_combo()
        self._rebuild_profile_combo()
        self._refresh_table()
        self._refresh_plugins_tab()
        self._refresh_logs_tab()
        self._update_vram_bar()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._on_second_tick)
        self.tick_timer.start(1000)

        # Passive startup: never auto-start services on open; probe live state first
        QTimer.singleShot(200, self._run_initial_runtime_probe)
        QTimer.singleShot(900, lambda: self.run_plugin_update_check(manual=False))
        QTimer.singleShot(1400, self._run_startup_app_update_check)

    @property
    def projects_map(self) -> dict[str, str]:
        return self.meta.setdefault("projects", {})

    def workspace_tools(self) -> list[ToolSpec]:
        return [t for t in self.tools if getattr(t, "in_workspace", True)]

    def get_visible_client_codes(self) -> list[str]:
        all_codes = [c for c, _ in AI_CLIENTS]
        raw = self.meta.get("visible_clients")
        if isinstance(raw, list):
            filtered = [c for c in all_codes if c in raw]
            if filtered:
                return filtered
        return all_codes

    def _tool_needs_vault_key(self, t: ToolSpec) -> bool:
        if getattr(t, "auth_mode", "key") == "oauth" and supports_oauth(t.id):
            return False
        return bool(t.vault_key_required and t.vault_key_name and not self.vault.has_secret(t.vault_key_name))

    def _missing_required_vault_keys(self) -> set[str]:
        return {
            t.vault_key_name
            for t in self.tools
            if getattr(t, "in_workspace", True)
            and self._tool_needs_vault_key(t)
        }

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

        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.lbl_profile = QLabel(tr(self.lang, "profile_lbl"))
        self.lbl_profile.setStyleSheet("font-weight: 600; color: #94a3b8;")
        top_bar.addWidget(self.lbl_profile)

        self.profile_cmb = QComboBox()
        self.profile_cmb.setMinimumWidth(230)
        self.profile_cmb.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.profile_cmb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_cmb.activated.connect(self._on_profile_combo_activated)
        top_bar.addWidget(self.profile_cmb)

        self.btn_new_profile = QPushButton(tr(self.lang, "btn_new_profile"))
        self.btn_new_profile.setObjectName("newProfileBtn")
        self.btn_new_profile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new_profile.setToolTip(tr(self.lang, "tip_new_profile"))
        self.btn_new_profile.clicked.connect(self.open_profile_wizard)
        top_bar.addWidget(self.btn_new_profile)

        self.btn_runtime = QPushButton(tr(self.lang, "btn_start_tools"))
        self.btn_runtime.setObjectName("runtimeStartBtn")
        self.btn_runtime.setMinimumWidth(148)
        self.btn_runtime.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_runtime.setEnabled(False)
        self.btn_runtime.clicked.connect(self._on_runtime_btn_clicked)
        top_bar.addWidget(self.btn_runtime)

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

        self.tabs = QTabWidget()
        main_lay.addWidget(self.tabs, stretch=1)

        self._init_panel_tab()
        self._init_plugins_tab()
        self._init_logs_tab()

        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.status_lbl = QLabel(tr(self.lang, "status_ready"))
        self.status_lbl.setMinimumWidth(160)
        self.status_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_lbl.setStyleSheet("color: #94a3b8;")
        foot.addWidget(self.status_lbl, stretch=1)

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

        self.token_summary_btn = QPushButton()
        self.token_summary_btn.setObjectName("tokenSummaryBtn")
        self.token_summary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.token_summary_btn.setToolTip(tr(self.lang, "token_summary_tip"))
        self.token_summary_btn.clicked.connect(self.open_token_breakdown)
        self.token_summary_lbl = self.token_summary_btn
        foot.addWidget(self.token_summary_btn)
        main_lay.addLayout(foot)

    def _refresh_toolbar_icons(self) -> None:
        is_light = self.meta.get("theme", "dark") == "light"
        col = icon_color(is_light, muted=False)
        self.btn_diagnostics.setIcon(make_icon("activity", col, 15))
        self.btn_settings.setIcon(make_icon("sliders", col, 15))
        self.btn_more.setIcon(make_icon("more", col, 15))
        self._apply_runtime_button_visuals()

    def _apply_runtime_button_visuals(self) -> None:
        if not hasattr(self, "btn_runtime"):
            return
        is_light = self.meta.get("theme", "dark") == "light"
        st = self._runtime_state
        if st == "probing":
            obj_name = "runtimeStartBtn"
            text = tr(self.lang, "btn_start_tools")
            tip = tr(self.lang, "tip_probing_tools")
            enabled = False
            icon_name = "play"
            ic_col = "#047857" if is_light else "#6ee7b7"
        elif st == "starting":
            obj_name = "runtimeStartBtn"
            text = tr(self.lang, "btn_starting_tools")
            tip = tr(self.lang, "msg_tools_starting")
            enabled = False
            icon_name = "play"
            ic_col = "#047857" if is_light else "#6ee7b7"
        elif st == "running":
            obj_name = "runtimeStopBtn"
            text = tr(self.lang, "btn_stop_tools")
            tip = tr(self.lang, "tip_stop_tools")
            enabled = True
            icon_name = "stop"
            ic_col = "#ffffff" if is_light else "#fef3c7"
        elif st == "stopping":
            obj_name = "runtimeStopBtn"
            text = tr(self.lang, "btn_stopping_tools")
            tip = tr(self.lang, "msg_tools_stopping")
            enabled = False
            icon_name = "stop"
            ic_col = "#92400e" if is_light else "#fcd34d"
        else:
            obj_name = "runtimeStartBtn"
            text = tr(self.lang, "btn_start_tools")
            tip = tr(self.lang, "tip_start_tools")
            enabled = True
            icon_name = "play"
            ic_col = "#ffffff"

        prev_obj = self.btn_runtime.objectName()
        self.btn_runtime.setObjectName(obj_name)
        self.btn_runtime.setText(text)
        self.btn_runtime.setToolTip(tip)
        self.btn_runtime.setEnabled(enabled)
        self.btn_runtime.setIcon(make_icon(icon_name, ic_col, 14))
        if prev_obj != obj_name:
            self.style().unpolish(self.btn_runtime)
            self.style().polish(self.btn_runtime)
        self.btn_runtime.update()

    def _set_runtime_ui_state(self, new_state: str) -> None:
        self._runtime_state = new_state
        self.runtime_started = new_state == "running"
        self._apply_runtime_button_visuals()
        self._rebuild_tray_menu()

    def _run_initial_runtime_probe(self) -> None:
        """Passive startup probe: checks whether managed services are already active without starting anything."""
        self._set_runtime_ui_state("probing")
        snap_tools = copy.deepcopy(self.workspace_tools())
        sk_cnt = len(self.active_skills)
        proj_snap = dict(self.projects_map)
        lang_snap = self.lang
        missing_keys = self._missing_required_vault_keys()

        def worker() -> None:
            live_map = scan_live_process_locations(lang=lang_snap)
            out = []
            for t in snap_tools:
                ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                    t, sk_cnt, proj_snap, live_map, lang=lang_snap, missing_required_keys=missing_keys
                )
                out.append((t.id, ok, h_state, ping_str, ms, detail, loc_detail))
            already_running = has_running_managed_services(snap_tools, live_map)
            target = "running" if already_running else "stopped"
            safe_emit(self.bridge.runtime_transition_done, target, out, live_map, "")

        threading.Thread(target=worker, daemon=True).start()

    def _on_runtime_btn_clicked(self) -> None:
        if self._runtime_state == "stopped":
            self.start_all_tools()
        elif self._runtime_state == "running":
            self.stop_all_tools()

    def start_all_tools(self) -> None:
        """Start all enabled tool servers, sync AI client configs, measure HTTP schemas, and verify ports."""
        if self._runtime_state != "stopped":
            return
        enabled_tools = [t for t in self.workspace_tools() if t.enabled]
        if not enabled_tools:
            self.set_status(tr(self.lang, "msg_no_enabled_to_start"))
            return

        self._sync_debounce.stop()
        self._sync_pending_ids.clear()
        self._sync_stop_ids.clear()
        self._sync_restart_ids.clear()
        self._set_runtime_ui_state("starting")
        self.set_status(tr(self.lang, "msg_tools_starting"))

        tools_snap = copy.deepcopy(self.tools)
        ws_snap = [x for x in tools_snap if getattr(x, "in_workspace", True)]
        skills_snap = set(self.active_skills)
        proj_snap = dict(self.projects_map)
        lang_snap = self.lang
        missing_keys = self._missing_required_vault_keys()

        def worker() -> None:
            started_ports: list[int] = []
            measured_schemas: dict[str, int] = {}
            with self._sync_lock:
                if self.sync_live_environment:
                    for t_obj in ws_snap:
                        if t_obj.enabled:
                            note = enforce_tool_runtime_state(
                                t_obj, proj_snap, allow_stop=False, allow_start=True, lang=lang_snap
                            )
                            if note and t_obj.port:
                                started_ports.append(int(t_obj.port))
                    bs_tool = next((x for x in tools_snap if x.id == "blender_skills"), None)
                    if bs_tool:
                        sync_blender_skills_on_disk(
                            skills_snap,
                            bool(getattr(bs_tool, "in_workspace", True) and bs_tool.enabled),
                            bs_tool.project_scope,
                            proj_snap,
                            lang=lang_snap,
                        )
                    cv_tool = next((x for x in tools_snap if x.id == "caveman"), None)
                    if cv_tool:
                        sync_caveman_on_disk(cv_tool, lang=lang_snap)
                    sync_mcp_json_clients(tools_snap, self.vault, proj_snap, lang=lang_snap)
                    if started_ports:
                        wait_for_started_ports(started_ports, timeout=2.5)
                    for t_obj in ws_snap:
                        if t_obj.enabled and t_obj.id in ("serena", "unity_mcp"):
                            tok_val = measure_tool_schema_tokens(t_obj, self.vault)
                            if isinstance(tok_val, int) and tok_val > 0:
                                measured_schemas[schema_cache_key(t_obj)] = tok_val

                live_map = scan_live_process_locations(lang=lang_snap)
                out = []
                for x in ws_snap:
                    ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                        x, len(skills_snap), proj_snap, live_map, lang=lang_snap, missing_required_keys=missing_keys
                    )
                    out.append((x.id, ok, h_state, ping_str, ms, detail, loc_detail))

            if measured_schemas:
                safe_emit(self.bridge.schema_measure_done, measured_schemas, len(measured_schemas))
            en_cnt = sum(1 for x in ws_snap if x.enabled)
            summary = tr(lang_snap, "msg_tools_started", n=en_cnt)
            safe_emit(self.bridge.runtime_transition_done, "running", out, live_map, summary)

        threading.Thread(target=worker, daemon=True).start()

    def stop_all_tools(self) -> None:
        """Stop all managed tool processes and keep the button locked until processes and ports close."""
        if self._runtime_state != "running":
            return
        self._sync_debounce.stop()
        self._sync_pending_ids.clear()
        self._sync_stop_ids.clear()
        self._sync_restart_ids.clear()
        self._set_runtime_ui_state("stopping")
        self.set_status(tr(self.lang, "msg_tools_stopping"))

        ws_snap = copy.deepcopy(self.workspace_tools())
        skills_snap = set(self.active_skills)
        proj_snap = dict(self.projects_map)
        lang_snap = self.lang
        missing_keys = self._missing_required_vault_keys()

        def worker() -> None:
            detail_msg = ""
            with self._sync_lock:
                if self.sync_live_environment:
                    _cnt, detail_msg = stop_all_managed_services(ws_snap, lang=lang_snap)
                live_map = scan_live_process_locations(lang=lang_snap)
                out = []
                for x in ws_snap:
                    ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                        x, len(skills_snap), proj_snap, live_map, lang=lang_snap, missing_required_keys=missing_keys
                    )
                    out.append((x.id, ok, h_state, ping_str, ms, detail, loc_detail))

            summary = tr(lang_snap, "msg_tools_stopped")
            if detail_msg:
                summary = f"{summary} ({detail_msg})"
            safe_emit(self.bridge.runtime_transition_done, "stopped", out, live_map, summary)

        threading.Thread(target=worker, daemon=True).start()

    def _on_runtime_transition_done(
        self,
        target_state: str,
        results: list[tuple[str, bool, str, str, int, str, str]],
        live_map: dict[str, str] | None,
        summary_msg: str,
    ) -> None:
        if live_map is not None:
            self._latest_live_map = live_map
        by_id = {t.id: t for t in self.tools}
        for tid, _ok, h_state, ping_str, ms, _detail, loc_detail in results:
            t = by_id.get(tid)
            if t is not None:
                t.live_location_detail = loc_detail
                if t.enabled and h_state == "off":
                    continue
                if not t.enabled and h_state != "off":
                    t.health_state = "off"
                    t.last_ping = tr(self.lang, "st_disabled")
                    t.last_latency_ms = -1
                    continue
                t.health_state = h_state
                t.last_ping = ping_str
                t.last_latency_ms = ms

        self._set_runtime_ui_state(target_state)
        self._refresh_table()
        self._refresh_host_dep_banner()
        self._update_vram_bar()
        if summary_msg:
            self.logs.add("INFO", tr(self.lang, "log_src_runtime"), summary_msg)
            self._refresh_logs_tab()
            self.set_status(summary_msg)

    def _on_bg_schema_measure_done(self, measured: dict[str, int], _count: int) -> None:
        if not isinstance(measured, dict) or not measured:
            return
        cache = self.meta.setdefault("schema_token_cache", {})
        if isinstance(cache, dict):
            cache.update(measured)
        self._save_state()
        self._refresh_table()

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        act_scan = QAction(tr(self.lang, "menu_scan_now"), self)
        act_scan.triggered.connect(self.run_health_scan)
        menu.addAction(act_scan)

        act_reapply = QAction(tr(self.lang, "menu_reapply_configs"), self)
        act_reapply.triggered.connect(self._handle_sync_configs)
        menu.addAction(act_reapply)

        act_cat = QAction(tr(self.lang, "menu_refresh_catalog"), self)
        act_cat.triggered.connect(self._handle_refresh_remote_catalog)
        menu.addAction(act_cat)

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

    # --- STATE, THEME, LANGUAGE ---
    def set_status(self, msg: str) -> None:
        self.status_lbl.setText(msg)
        self.status_lbl.setToolTip(msg)

    def _set_config_status(self, msg: str) -> None:
        self.set_status(f"{msg}  ({tr(self.lang, 'msg_cfg_reload_hint')})")

    def _save_state(self) -> None:
        self.meta["sort_key"] = self.sort_key
        self.meta["sort_desc"] = self.sort_desc
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
            if not getattr(t, "in_workspace", True):
                t.last_ping = tr(self.lang, "st_disabled")
                continue
            t.last_ping = tr(self.lang, "st_disabled") if not t.enabled else tr(self.lang, "st_scanning")
            t.live_location_detail = resolve_disk_location(t, self.projects_map, {}, lang=self.lang)
        self._save_state()
        self._retranslate_ui()
        self._rebuild_kind_filter_combo()
        self._rebuild_tag_filter_combo()
        self._rebuild_project_filter_combo()
        self._rebuild_plugin_filter_combos()
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
        ws_tools = self.workspace_tools()
        self.tabs.setTabText(0, tr(self.lang, "tab_tools", n=len(ws_tools)))
        upd_cnt = sum(1 for t in ws_tools if t.has_update)
        if upd_cnt > 0:
            key = "tab_plugins_upd_one" if upd_cnt == 1 else "tab_plugins_upd"
            self.tabs.setTabText(1, tr(self.lang, key, n=upd_cnt))
        else:
            self.tabs.setTabText(1, tr(self.lang, "tab_plugins_cnt", n=len(self.tools)))
        counts = self.logs.counts_by_level()
        if counts["ERR"] > 0 or counts["WARN"] > 0:
            self.tabs.setTabText(2, tr(self.lang, "tab_logs_counts", err=counts["ERR"], warn=counts["WARN"]))
        else:
            self.tabs.setTabText(2, tr(self.lang, "tab_logs"))

    def _retranslate_ui(self) -> None:
        app_ver = get_current_app_version()
        self.setWindowTitle(tr(self.lang, "app_title", ver=app_ver))
        self.lbl_profile.setText(tr(self.lang, "profile_lbl"))
        self.btn_new_profile.setText(tr(self.lang, "btn_new_profile"))
        self.btn_new_profile.setToolTip(tr(self.lang, "tip_new_profile"))
        self._apply_runtime_button_visuals()
        self.btn_diagnostics.setText(tr(self.lang, "btn_diagnostics"))
        self.btn_settings.setText(tr(self.lang, "btn_settings"))
        self.btn_more.setToolTip(tr(self.lang, "btn_more_tip"))
        self.btn_banner_upd.setText(tr(self.lang, "banner_update_now"))
        self.btn_vram_free.setText(tr(self.lang, "vram_free"))
        self.btn_vram_free.setToolTip(tr(self.lang, "vram_free_tip"))
        if not (self.latest_app_check and self.latest_app_check.has_update):
            self.btn_do_app_upd.setText(tr(self.lang, "ver_btn", ver=app_ver))
        self.btn_do_app_upd.setToolTip(tr(self.lang, "ver_btn_tip"))
        self.token_summary_btn.setToolTip(tr(self.lang, "token_summary_tip"))

        self.search_inp.setPlaceholderText(tr(self.lang, "search_ph"))
        self.plug_search_inp.setPlaceholderText(tr(self.lang, "plug_search_ph"))
        self.btn_plugins_check.setText(tr(self.lang, "plug_check"))
        self.btn_add_github.setText(tr(self.lang, "plug_add_github"))
        self.btn_jump_err_logs.setText(tr(self.lang, "plug_btn_view_errs"))
        if self.checking_plugins_busy:
            self.plugins_banner_lbl.setText(tr(self.lang, "plug_banner_checking"))

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
        restart_running: bool = False,
    ) -> None:
        if not self.sync_live_environment:
            return
        targets = list(target_tools) if target_tools is not None else list(self.tools)
        ids = {t.id for t in targets}
        self._sync_pending_ids.update(ids)
        if allow_stop:
            self._sync_stop_ids.update(ids)
        if restart_running:
            self._sync_restart_ids.update(ids)
        self._sync_debounce.start()

    def _flush_live_sync(self) -> None:
        target_ids = set(self._sync_pending_ids)
        stop_ids = set(self._sync_stop_ids)
        restart_ids = set(self._sync_restart_ids)
        self._sync_pending_ids.clear()
        self._sync_stop_ids.clear()
        self._sync_restart_ids.clear()

        tools_snap = copy.deepcopy(self.tools)
        ws_snap = [x for x in tools_snap if getattr(x, "in_workspace", True)]
        skills_snap = set(self.active_skills)
        proj_snap = dict(self.projects_map)
        lang_snap = self.lang
        allow_start_flag = bool(self.runtime_started and self._runtime_state == "running")
        missing_keys = self._missing_required_vault_keys()

        def worker() -> None:
            measured_schemas: dict[str, int] = {}
            with self._sync_lock:
                for t_obj in tools_snap:
                    if t_obj.id in target_ids and (getattr(t_obj, "in_workspace", True) or t_obj.id in stop_ids):
                        enforce_tool_runtime_state(
                            t_obj,
                            proj_snap,
                            allow_stop=(t_obj.id in stop_ids),
                            allow_start=(allow_start_flag and getattr(t_obj, "in_workspace", True)),
                            restart_if_running=(t_obj.id in restart_ids),
                            lang=lang_snap,
                        )
                        if t_obj.id in restart_ids and t_obj.enabled and t_obj.id in ("serena", "unity_mcp"):
                            tok_val = measure_tool_schema_tokens(t_obj, self.vault)
                            if isinstance(tok_val, int) and tok_val > 0:
                                measured_schemas[schema_cache_key(t_obj)] = tok_val
                bs_tool = next((x for x in tools_snap if x.id == "blender_skills"), None)
                if bs_tool:
                    sync_blender_skills_on_disk(
                        skills_snap,
                        bool(getattr(bs_tool, "in_workspace", True) and bs_tool.enabled),
                        bs_tool.project_scope,
                        proj_snap,
                        lang=lang_snap,
                    )
                cv_tool = next((x for x in tools_snap if x.id == "caveman"), None)
                if cv_tool:
                    sync_caveman_on_disk(cv_tool, lang=lang_snap)
                sync_custom_skill_tools_on_disk(tools_snap, lang=lang_snap)
                sync_mcp_json_clients(tools_snap, self.vault, proj_snap, lang=lang_snap)
                eff_lang = self.lang
                live_map = scan_live_process_locations(lang=eff_lang)
                out = []
                for x in ws_snap:
                    ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                        x, len(skills_snap), proj_snap, live_map, lang=eff_lang, missing_required_keys=missing_keys
                    )
                    out.append((x.id, ok, h_state, ping_str, ms, detail, loc_detail))
            if measured_schemas:
                safe_emit(self.bridge.schema_measure_done, measured_schemas, len(measured_schemas))
            if self.lang == eff_lang:
                safe_emit(self.bridge.health_done, out, live_map, True)

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_tool(self, tool: ToolSpec, prompt_missing_key: bool = True) -> None:
        tool.enabled = not tool.enabled
        self.meta["active_profile"] = ""
        self.meta["first_run_dismissed"] = True
        self._refresh_first_run_banner()
        self._rebuild_profile_combo()
        if not tool.enabled:
            tool.health_state = "off"
            tool.last_ping = tr(self.lang, "st_disabled")
        elif self._tool_needs_vault_key(tool):
            tool.health_state = "warn"
            tool.last_ping = tr(self.lang, "st_missing_key")
            if prompt_missing_key and self.isVisible():
                ans = QMessageBox.question(
                    self,
                    tr(self.lang, "key_req_prompt_title"),
                    tr(self.lang, "key_req_prompt_msg", name=tool.name, key=tool.vault_key_name),
                )
                if ans == QMessageBox.StandardButton.Yes:
                    self.open_settings(SettingsDialog.TAB_KEYS, focus_key=tool.vault_key_name)
                    if not self._tool_needs_vault_key(tool):
                        tool.health_state = "ok"
                        tool.last_ping = tr(self.lang, "st_ready")
        elif tool.port:
            tool.health_state = "idle"
            tool.last_ping = tr(self.lang, "st_scanning")
        elif tool.id == "blender_skills":
            tool.health_state = "ok"
            tool.last_ping = tr(self.lang, "st_active_count", on=len(self.active_skills))
        else:
            tool.health_state = "ok"
            tool.last_ping = tr(self.lang, "st_ready")
        self._save_state()
        if self._runtime_state == "running" and not any(t.enabled for t in self.workspace_tools()):
            self._set_runtime_ui_state("stopped")
        state_word = tr(self.lang, "client_on" if tool.enabled else "client_off").lower()
        self.logs.add("DBG", tool.name, tr(self.lang, "log_tool_toggled", state=state_word))
        self._set_config_status(tr(self.lang, "msg_tool_toggled", name=tool.name, state=state_word))
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
        self._set_config_status(tr(self.lang, "msg_client_toggled", name=tool.name, code=client_code, state=state_word))
        self._refresh_table()
        self._sync_live_environment_async(target_tools=[])

    def _update_bulk_client_buttons(self) -> None:
        ws_tools = self.workspace_tools()
        total = len(ws_tools)
        is_light = self.meta.get("theme", "dark") == "light"
        for code, full_lbl in AI_CLIENTS:
            btn = self.bulk_client_btns.get(code)
            if not btn:
                continue
            on_cnt = sum(1 for t in ws_tools if t.clients.get(code, False))
            is_installed = code in self.installed_clients
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
            elif not is_installed:
                btn.setStyleSheet(
                    "background-color: #f8fafc; color: #94a3b8; border: 1px dashed #cbd5e1; "
                    "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                    if is_light
                    else "background-color: #090d13; color: #475569; border: 1px dashed #1e293b; "
                    "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                )
            else:
                btn.setStyleSheet(
                    "background-color: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; "
                    "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                    if is_light
                    else "background-color: #0c1117; color: #64748b; border: 1px solid #263549; "
                    "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                )
            tip_lbl = full_lbl if is_installed else f"{full_lbl} ({tr(self.lang, 'client_not_detected')})"
            btn.setToolTip(
                tr(self.lang, "bulk_client_tip", full=tip_lbl, code=code, on=on_cnt, tot=total)
            )

    def _toggle_client_all(self, client_code: str, mode: str = "auto") -> None:
        ws_tools = self.workspace_tools()
        if mode == "auto":
            any_on = any(t.clients.get(client_code, False) for t in ws_tools)
            target_state = not any_on
            for t in ws_tools:
                t.clients[client_code] = target_state
        elif mode == "all_on":
            for t in ws_tools:
                t.clients[client_code] = True
        elif mode == "active_only":
            for t in ws_tools:
                t.clients[client_code] = bool(t.enabled)
        else:
            for t in ws_tools:
                t.clients[client_code] = False

        self.meta["active_profile"] = ""
        self._rebuild_profile_combo()
        self._save_state()
        msg = tr(self.lang, "msg_bulk_client", code=client_code)
        self.logs.add("INFO", tr(self.lang, "log_src_clients", code=client_code), msg)
        self._set_config_status(msg)
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

    def reset_tool_to_defaults(self, tool: ToolSpec) -> None:
        """Reset a single tool's mode, parameters, options, scope, and client bindings to factory defaults."""
        default_spec = get_default_tool_spec(tool.id)
        if tool.id == "blender_skills":
            self.active_skills = set(DEFAULT_ACTIVE_BLENDER_SKILLS)
            self.meta["checked_blender_skills"] = []

        if default_spec is not None:
            tool.clients = dict(default_spec.clients)
            if tool.scope_selectable:
                tool.project_scope = default_spec.project_scope
            tool.auth_mode = default_spec.auth_mode
            tool.mode_index = default_spec.mode_index
            tool.param_value = default_spec.param_value
            tool.port = default_spec.port
            def_opts = {o.key: o.enabled for o in default_spec.options}
            for o in tool.options:
                o.enabled = def_opts.get(o.key, False)
        else:
            tool.clients = {"AGY": True, "CDX": True, "CLD": False, "CUR": False}
            if tool.scope_selectable:
                tool.project_scope = "GLOBAL"
            tool.auth_mode = "key"
            tool.mode_index = 0
            tool.param_value = ""
            for o in tool.options:
                o.enabled = False

        self.meta["active_profile"] = ""
        self._rebuild_profile_combo()
        self._save_state()
        self.logs.add("INFO", tool.name, tr(self.lang, "log_tool_reset"))
        self._set_config_status(tr(self.lang, "msg_tool_reset", name=tool.name))
        self._refresh_table()
        self._refresh_logs_tab()
        self._sync_live_environment_async(
            target_tools=[tool],
            restart_running=(tool.id in ("serena", "unity_mcp") and tool.enabled),
        )

    def install_and_add_tool(self, tool: ToolSpec) -> None:
        """Download & install an uninstalled library plugin onto the PC, then add it to the Tools workspace."""
        if getattr(tool, "in_workspace", True):
            return
        if getattr(tool, "installed", False):
            self.add_tool_to_workspace(tool)
            return
        self._run_library_install([tool], enable_after=False)

    def add_tool_to_workspace(self, tool: ToolSpec) -> None:
        """Add an installed tool to the active Tools workspace."""
        if getattr(tool, "in_workspace", True):
            return
        tool.installed = True
        tool.in_workspace = True
        tool.enabled = False
        tool.health_state = "off"
        tool.last_ping = tr(self.lang, "st_disabled")
        tool.live_location_detail = resolve_disk_location(tool, self.projects_map, self._latest_live_map, lang=self.lang)
        self._save_state()
        self._rebuild_tag_filter_combo()
        self._rebuild_plugin_filter_combos()
        self._update_tab_titles()
        self._refresh_table()
        self._refresh_plugins_tab()
        if self._tool_needs_vault_key(tool):
            msg = tr(self.lang, "msg_ws_added_key", name=tool.name, key=tool.vault_key_name)
        else:
            msg = tr(self.lang, "msg_ws_added", name=tool.name)
        self.logs.add("INFO", tool.name, msg)
        self.set_status(msg)
        self._refresh_logs_tab()

    def remove_tool_from_workspace(self, tool: ToolSpec) -> None:
        """Remove a tool from the active Tools workspace (remains installed on disk & available in Plugins)."""
        if not getattr(tool, "in_workspace", True):
            return
        was_enabled = bool(tool.enabled)
        tool.enabled = False
        tool.in_workspace = False
        tool.health_state = "off"
        tool.last_ping = tr(self.lang, "st_disabled")
        if self._runtime_state == "running" and not any(t.enabled for t in self.workspace_tools()):
            self._set_runtime_ui_state("stopped")
        self._save_state()
        self._rebuild_tag_filter_combo()
        self._rebuild_plugin_filter_combos()
        self._update_tab_titles()
        self._refresh_table()
        self._refresh_plugins_tab()
        msg = tr(self.lang, "msg_ws_removed", name=tool.name)
        self.logs.add("INFO", tool.name, msg)
        if was_enabled:
            self._set_config_status(msg)
            self._sync_live_environment_async(target_tools=[tool])
        else:
            self.set_status(msg)
        self._refresh_logs_tab()

    def prompt_remove_or_uninstall_tool(self, tool: ToolSpec) -> None:
        """Offer 'Hide from Tools Only' vs 'Uninstall from PC' when removing a workspace tool."""
        if not getattr(tool, "in_workspace", True):
            return
        if not self.sync_live_environment or not can_uninstall_tool_from_disk(tool) or not self.isVisible():
            self.remove_tool_from_workspace(tool)
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr(self.lang, "rem_choice_title"))
        box.setText(f"<b>{tr(self.lang, 'rem_choice_hdr', name=tool.name)}</b>")
        box.setInformativeText(tr(self.lang, "rem_choice_body"))
        btn_hide = box.addButton(tr(self.lang, "rem_btn_hide_only"), QMessageBox.ButtonRole.AcceptRole)
        btn_uninst = box.addButton(tr(self.lang, "rem_btn_uninstall_pc"), QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton(tr(self.lang, "btn_cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_hide)
        box.exec()

        clicked = box.clickedButton()
        if clicked == btn_cancel or clicked is None:
            return
        if clicked == btn_hide:
            self.remove_tool_from_workspace(tool)
            return
        if clicked == btn_uninst:
            self._run_library_uninstall(tool)

    def _run_library_uninstall(self, tool: ToolSpec) -> None:
        if tool.id in self._uninstalling_tool_ids:
            return
        was_enabled = bool(tool.enabled)
        tool.enabled = False
        self._uninstalling_tool_ids.add(tool.id)
        self.set_status(tr(self.lang, "msg_tool_uninstalling", name=tool.name))
        self._refresh_plugins_tab()
        if was_enabled:
            self._sync_live_environment_async(target_tools=[tool])

        snap = copy.deepcopy(tool)
        lang_snap = self.lang

        def worker() -> None:
            ok, msg, raw_log = uninstall_library_tool(snap, lang=lang_snap)
            safe_emit(self.bridge.lib_uninstall_done, snap.id, ok, msg, raw_log)

        threading.Thread(target=worker, daemon=True).start()

    def _on_lib_uninstall_done(self, tool_id: str, ok: bool, msg: str, raw_log: str) -> None:
        self._uninstalling_tool_ids.discard(tool_id)
        tool_obj = next((t for t in self.tools if t.id == tool_id), None)
        t_name = tool_obj.name if tool_obj else tool_id
        if ok and tool_obj is not None:
            tool_obj.enabled = False
            tool_obj.in_workspace = False
            tool_obj.installed = False
            tool_obj.health_state = "off"
            tool_obj.last_ping = tr(self.lang, "st_disabled")
            if self._runtime_state == "running" and not any(t.enabled for t in self.workspace_tools()):
                self._set_runtime_ui_state("stopped")
            self._save_state()
            self._rebuild_tag_filter_combo()
            self._rebuild_plugin_filter_combos()
            self._update_tab_titles()
            self._refresh_table()
            self._refresh_plugins_tab()
            st_msg = tr(self.lang, "msg_tool_uninstalled", name=t_name)
            self.logs.add("INFO", t_name, st_msg, raw_log or msg)
            self.set_status(st_msg)
        else:
            err_msg = tr(self.lang, "msg_tool_uninstall_err", name=t_name, msg=msg)
            self.logs.add("ERR", t_name, err_msg, raw_log or msg)
            self.set_status(err_msg)
            self._refresh_plugins_tab()
        self._refresh_logs_tab()

    # --- DIALOG LAUNCHERS ---
    def open_gear(self, tool: ToolSpec) -> None:
        if tool.gear_kind == "skills94":
            saved_chk = set(self.meta.get("checked_blender_skills", []))
            dlg = BlenderSkillsDialog(self, self.active_skills, saved_chk, lang=self.lang)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.saved_result is not None:
                self.active_skills = dlg.saved_result
                self.meta["checked_blender_skills"] = sorted(dlg.saved_checked)
                tool.enabled = len(self.active_skills) > 0
                ok, disk_msg = (True, "")
                if self.sync_live_environment:
                    ok, disk_msg = sync_blender_skills_on_disk(
                        self.active_skills,
                        tool.enabled,
                        tool.project_scope,
                        self.projects_map,
                        lang=self.lang,
                    )
                self._save_state()
                self.logs.add(
                    "INFO" if ok else "DBG",
                    tool.name,
                    tr(self.lang, "log_skills_saved", n=len(self.active_skills)),
                    disk_msg,
                )
                self._set_config_status(tr(self.lang, "msg_skills_saved", on=len(self.active_skills), detail=disk_msg))
                self._refresh_table()
                self._refresh_logs_tab()
        else:
            prev_snap = (
                tool.port,
                tool.param_value,
                tool.mode_index,
                getattr(tool, "auth_mode", "key"),
                tuple(o.enabled for o in tool.options),
            )
            dlg = ToolGearDialog(self, tool, self._format_scope_display(tool))
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_snap = (
                    tool.port,
                    tool.param_value,
                    tool.mode_index,
                    getattr(tool, "auth_mode", "key"),
                    tuple(o.enabled for o in tool.options),
                )
                changed = new_snap != prev_snap
                if tool.enabled:
                    if self._tool_needs_vault_key(tool):
                        tool.health_state = "warn"
                        tool.last_ping = tr(self.lang, "st_missing_key")
                    elif tool.health_state == "warn" and not tool.port:
                        tool.health_state = "ok"
                        tool.last_ping = tr(self.lang, "st_ready")
                self._save_state()
                self.logs.add("INFO", tool.name, tr(self.lang, "log_gear_saved"))
                self._set_config_status(tr(self.lang, "msg_gear_saved", name=tool.name))
                self._refresh_table()
                self._refresh_plugins_tab()
                self._refresh_logs_tab()
                self._sync_live_environment_async(
                    target_tools=[tool],
                    restart_running=(changed and tool.id in ("serena", "unity_mcp") and tool.enabled),
                )

    def open_settings(self, initial_tab: int = 0, focus_key: str = "") -> None:
        dlg = SettingsDialog(self, initial_tab=initial_tab, focus_key=focus_key)
        dlg.exec()

    def open_diagnostics(self) -> None:
        dlg = DiagnosticsDialog(self)
        dlg.exec()

    def open_token_breakdown(self) -> None:
        dlg = TokenBreakdownDialog(self)
        dlg.exec()

    # --- PERIODIC WATCHERS, ADAPTIVE TRAY SLEEP & IDLE PORT PROTECTION ---
    def _check_idle_http_autostop(self) -> None:
        if not self.sync_live_environment or not self.meta.get("auto_stop_idle_http", False):
            self._no_client_seconds = 0
            return
        if self._runtime_state != "running":
            self._no_client_seconds = 0
            return
        if has_running_ai_client_processes():
            self._no_client_seconds = 0
            return
        self._no_client_seconds += 10
        if self._no_client_seconds >= 300:
            self._no_client_seconds = 0
            msg = tr(self.lang, "msg_idle_autostop")
            self.logs.add("INFO", tr(self.lang, "log_src_runtime"), msg)
            self._refresh_logs_tab()
            self.set_status(msg)
            self.stop_all_tools()

    def _on_second_tick(self) -> None:
        # Adaptive Tray Sleep Mode: when minimized/hidden, throttle polling to 60s and pause VRAM/DCC checks
        if not self.isVisible():
            self._tray_sleep_ticks += 1
            if self._tray_sleep_ticks % 10 == 0:
                self._check_idle_http_autostop()
            if self._tray_sleep_ticks >= 60:
                self._tray_sleep_ticks = 0
                self._run_silent_live_watch()
            return

        self._tray_sleep_ticks = 0
        self.seconds_left -= 1
        if self.seconds_left <= 0:
            self.run_health_scan()
        elif self.seconds_left % 3 == 0:
            self._run_silent_live_watch()

        if self.seconds_left % 10 == 0:
            self._update_vram_bar()
            self._check_idle_http_autostop()
            if self.meta.get("auto_detect_apps", True):
                self._check_dcc_auto_switch()

    def _run_silent_live_watch(self) -> None:
        if self._live_watch_busy:
            return
        self._live_watch_busy = True
        snap_tools = copy.deepcopy(self.workspace_tools())
        sk_cnt = len(self.active_skills)
        proj_snap = dict(self.projects_map)
        missing_keys = self._missing_required_vault_keys()

        def worker() -> None:
            try:
                eff_lang = self.lang
                live_map = scan_live_process_locations(lang=eff_lang)
                out = []
                for t in snap_tools:
                    ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                        t, sk_cnt, proj_snap, live_map, lang=eff_lang, missing_required_keys=missing_keys
                    )
                    out.append((t.id, ok, h_state, ping_str, ms, detail, loc_detail))
                if self.lang == eff_lang:
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
                tr(self.lang, "msg_dcc_detected", app="Unity Editor", prof=profile_title("unity_shader", self.lang))
            )
        elif cur.get("blender") and not self.last_detected_apps.get("blender"):
            self.set_status(
                tr(self.lang, "msg_dcc_detected", app="Blender", prof=profile_title("modeling_3d", self.lang))
            )
        self.last_detected_apps = cur
        self._update_vram_visibility()

    def run_health_scan(self) -> None:
        self.seconds_left = 30
        if self._health_busy:
            self._health_pending = True
            return
        self._health_busy = True
        self._health_pending = False
        self.set_status(tr(self.lang, "msg_scanning"))
        snap_tools = copy.deepcopy(self.workspace_tools())
        sk_cnt = len(self.active_skills)
        proj_snap = dict(self.projects_map)
        lang_snap = self.lang
        missing_keys = self._missing_required_vault_keys()

        def worker() -> None:
            out = []
            live_map: dict[str, str] = {}
            try:
                live_map = scan_live_process_locations(lang=lang_snap)
                for t in snap_tools:
                    ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                        t, sk_cnt, proj_snap, live_map, lang=lang_snap, missing_required_keys=missing_keys
                    )
                    out.append((t.id, ok, h_state, ping_str, ms, detail, loc_detail))
            finally:
                self._health_busy = False
            if self.lang == lang_snap:
                safe_emit(self.bridge.health_done, out, live_map, False)
            else:
                self._health_pending = True
                safe_emit(self.bridge.health_done, [], None, True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_health_results(
        self,
        results: list[tuple[str, bool, str, str, int, str, str]],
        live_map: dict[str, str] | None = None,
        silent: bool = False,
    ) -> None:
        if getattr(self, "_health_pending", False) and not self._health_busy:
            self._health_pending = False
            QTimer.singleShot(20, self.run_health_scan)
            if not results:
                return
        if isinstance(live_map, dict):
            self._latest_live_map = live_map
        by_id = {t.id: t for t in self.tools}
        state_changed = False

        for tid, ok, h_state, ping_str, ms, detail, loc_detail in results:
            if tid in by_id:
                t = by_id[tid]
                if t.enabled and h_state == "off":
                    t.live_location_detail = loc_detail
                    continue
                if not t.enabled and h_state != "off":
                    t.health_state = "off"
                    t.last_ping = tr(self.lang, "st_disabled")
                    t.last_latency_ms = -1
                    t.live_location_detail = loc_detail
                    continue
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
                    if (
                        tid in ("serena", "unity_mcp")
                        and self.sync_live_environment
                        and self.runtime_started
                        and self._runtime_state == "running"
                    ):
                        if now_mono - self._auto_heal_cooldown.get(tid, 0.0) > 45.0:
                            self._auto_heal_cooldown[tid] = now_mono
                            self._auto_heal_tool_async(t)
                            continue
                    if not silent and now_mono - self._last_warn_time.get(tid, 0.0) > 300.0:
                        self._last_warn_time[tid] = now_mono
                        self.logs.add(
                            "WARN",
                            t.name,
                            tr(self.lang, "log_srv_no_resp", status=ping_str),
                            detail,
                            t.port,
                        )

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
        while self.host_dep_btns_lay.count():
            item = self.host_dep_btns_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self.runtime_started:
            self.host_dep_banner.hide()
            return

        missing = get_missing_host_dependencies(
            self.workspace_tools(), self._latest_live_map, self.projects_map, lang=self.lang
        )
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
        self.logs.add("INFO" if ok else "WARN", tr(self.lang, "log_src_host"), msg)
        self.set_status(msg)
        self._refresh_logs_tab()
        QTimer.singleShot(2500, self.run_health_scan)

    def _auto_heal_tool_async(self, tool: ToolSpec) -> None:
        tool_snap = copy.deepcopy(tool)
        proj_snap = dict(self.projects_map)
        sk_cnt = len(self.active_skills)
        lang_snap = self.lang
        missing_keys = self._missing_required_vault_keys()

        def worker() -> None:
            note = enforce_tool_runtime_state(tool_snap, proj_snap, allow_stop=False, lang=lang_snap)
            if note:
                self.logs.add("INFO", tool_snap.name, tr(lang_snap, "log_auto_heal", note=note))
                time.sleep(1.5)
                live_map = scan_live_process_locations(lang=lang_snap)
                ok, h_state, ping_str, ms, detail, loc_detail = probe_tool_health(
                    tool_snap, sk_cnt, proj_snap, live_map, lang=lang_snap, missing_required_keys=missing_keys
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
                msg = tr(lang_snap, "log_port_err", port=port, err=exc)
            finally:
                safe_emit(self.bridge.port_kill_done, port, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_port_kill_done(self, port: int, _ok: bool, msg: str) -> None:
        self.logs.add("INFO", f"Port :{port}", msg, msg, port)
        self._refresh_logs_tab()
        self.set_status(msg)
        QTimer.singleShot(500, self.run_health_scan)
