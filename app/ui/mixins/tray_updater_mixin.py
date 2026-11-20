"""System tray, settings backup/restore, remote catalog refresh, and SHA-256 self-updater mixin."""
from __future__ import annotations

import json
import pathlib
import threading
import time
from typing import Any

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QSystemTrayIcon

from ...catalog import PROFILES, build_default_catalog, profile_title
from ...i18n import normalize_language, tr
from ...library_catalog import build_library_catalog, refresh_remote_catalog
from ...mcp_config import (
    sync_blender_skills_on_disk,
    sync_caveman_on_disk,
    sync_custom_skill_tools_on_disk,
    sync_mcp_json_clients,
)
from ...processes import resolve_disk_location
from ...storage import _atomic_write_text
from ...updater import (
    UpdateCheckResult,
    check_for_app_updates,
    get_current_app_version,
    parse_semver,
    resolve_effective_app_repo,
)
from ..dialogs import AppUpdateDialog
from ..theme import create_app_icon
from ..workers import safe_emit


class TrayUpdaterMixin:
    """Mixin handling system tray lifecycle, adaptive wake, backup/import, catalog sync, and self-updater."""

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

        st = getattr(self, "_runtime_state", "stopped")
        if st in ("probing", "starting"):
            act_rt = QAction(tr(self.lang, "btn_starting_tools"), self)
            act_rt.setEnabled(False)
        elif st == "stopping":
            act_rt = QAction(tr(self.lang, "btn_stopping_tools"), self)
            act_rt.setEnabled(False)
        elif st == "running":
            act_rt = QAction(tr(self.lang, "btn_stop_tools"), self)
            act_rt.triggered.connect(self.stop_all_tools)
        else:
            act_rt = QAction(tr(self.lang, "btn_start_tools"), self)
            act_rt.triggered.connect(self.start_all_tools)
        menu.addAction(act_rt)
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
        was_hidden = not self.isVisible()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if was_hidden:
            # Instant refresh when waking from adaptive tray sleep
            self._tray_sleep_ticks = 0
            self.run_health_scan()
            self._update_vram_bar()

    def _quit_app(self) -> None:
        self.force_quit = True
        self._save_state()
        self._shutdown_managed_runtime_sync()
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._save_state()
        minimize_to_tray = bool(self.meta.get("minimize_to_tray", False))
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
        self._shutdown_managed_runtime_sync()
        self.table.detach_filter()
        self.log_table.detach_filter()
        super().closeEvent(event)

    # --- CONFIG SYNC, REMOTE CATALOG & IMPORT / EXPORT ---
    def _handle_refresh_remote_catalog(self) -> None:
        if getattr(self, "_remote_catalog_busy", False):
            return
        self._remote_catalog_busy = True
        data_dir_snap = self.data_dir
        lang_snap = self.lang

        def worker() -> None:
            ok, updated, msg = False, False, ""
            try:
                ok, updated, msg = refresh_remote_catalog(data_dir_snap, lang=lang_snap)
            finally:
                safe_emit(self.bridge.remote_catalog_done, ok, updated, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_remote_catalog_done(self, ok: bool, updated: bool, msg: str) -> None:
        self._remote_catalog_busy = False
        self.logs.add("INFO" if ok else "WARN", "AIconomy", msg)
        self._refresh_logs_tab()
        self.set_status(msg)
        if updated:
            by_id = {t.id: t for t in self.tools}
            for new_t in build_library_catalog(self.data_dir):
                existing = by_id.get(new_t.id)
                if existing is None:
                    self.tools.append(new_t)
                    self.default_ids.add(new_t.id)
                elif new_t.id in self.default_ids:
                    # Refresh upstream metadata/commands while preserving user's workspace/enabled/client choices
                    existing.name = new_t.name
                    existing.version = new_t.version
                    existing.repo_url = new_t.repo_url
                    existing.schema_tokens = new_t.schema_tokens
                    existing.summary = new_t.summary
                    existing.details = new_t.details
                    existing.when_to_use = new_t.when_to_use
                    existing.install_cmd = new_t.install_cmd
                    existing.mcp_server_key = new_t.mcp_server_key
                    existing.mcp_command = new_t.mcp_command
                    existing.mcp_args = list(new_t.mcp_args)
                    existing.param_label = new_t.param_label
                    existing.param_help = new_t.param_help
                    existing.param_arg_flag = new_t.param_arg_flag
                    existing.param_env_var = new_t.param_env_var
                    existing.vault_key_required = new_t.vault_key_required
                    if new_t.vault_key_name:
                        existing.vault_key_name = new_t.vault_key_name
                    existing.vault_key_desc = new_t.vault_key_desc
                    existing.has_gear = new_t.has_gear
            self._save_state()
            self._rebuild_tag_filter_combo()
            self._rebuild_plugin_filter_combos()
            self._update_tab_titles()
            self._refresh_table()
            self._refresh_plugins_tab()

    def _handle_sync_configs(self) -> None:
        with self._sync_lock:
            rt_active = bool(self.runtime_started and self._runtime_state == "running")
            bs_tool = next((t for t in self.tools if t.id == "blender_skills"), None)
            if bs_tool:
                sync_blender_skills_on_disk(
                    self.active_skills,
                    bool(getattr(bs_tool, "in_workspace", True) and bs_tool.enabled),
                    bs_tool.project_scope,
                    self.projects_map,
                    lang=self.lang,
                    clients=dict(bs_tool.clients),
                    runtime_active=rt_active,
                )
            cv_tool = next((t for t in self.tools if t.id == "caveman"), None)
            if cv_tool:
                sync_caveman_on_disk(cv_tool, lang=self.lang, runtime_active=rt_active)
            sync_custom_skill_tools_on_disk(self.tools, lang=self.lang, runtime_active=rt_active)
            msgs = sync_mcp_json_clients(
                self.tools, self.vault, self.projects_map, lang=self.lang, runtime_active=rt_active
            )
        summary = " | ".join(msgs) if msgs else tr(self.lang, "log_no_cfg_files")
        self.logs.add("INFO", tr(self.lang, "log_src_cfg_sync"), summary)
        self._refresh_logs_tab()
        self._set_config_status(tr(self.lang, "msg_configs_synced", summary=summary))
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
        raw_doc = json.loads(txt)
        if not isinstance(raw_doc, dict) or (
            not isinstance(raw_doc.get("tools"), dict) and not isinstance(raw_doc.get("meta"), dict)
        ):
            raise ValueError("Invalid AIconomy settings schema (expected 'tools' or 'meta' object).")
        _atomic_write_text(self.store.state_file, txt)
        self.tools = build_default_catalog(data_dir=self.data_dir)
        self.active_skills, self.meta = self.store.load_into(self.tools, vault=self.vault)

        self.sort_key = str(self.meta.get("sort_key", "enabled"))
        if self.sort_key not in ("name", "project", "ping", "enabled"):
            self.sort_key = "enabled"
        self.sort_desc = bool(self.meta.get("sort_desc", True))
        self.lang = normalize_language(str(self.meta.get("lang") or self.lang))
        self.meta["lang"] = self.lang
        self._apply_theme(self.meta.get("theme", "dark"))

        rt_active = bool(self.runtime_started and self._runtime_state == "running")
        for t in self.tools:
            if getattr(t, "in_workspace", True):
                t.live_location_detail = resolve_disk_location(t, self.projects_map, {}, lang=self.lang)
                if not t.enabled:
                    t.last_ping = tr(self.lang, "st_disabled")
                    t.health_state = "off"
                elif self._tool_blocked_by_locked_vault(t):
                    t.last_ping = tr(self.lang, "st_vault_locked")
                    t.health_state = "warn"
                elif not rt_active:
                    t.last_ping = tr(self.lang, "st_stopped_standby")
                    t.health_state = "idle"
            else:
                t.last_ping = tr(self.lang, "st_disabled")
                t.health_state = "off"

        if self.sync_live_environment:
            bs_tool = next((t for t in self.tools if t.id == "blender_skills"), None)
            if bs_tool:
                sync_blender_skills_on_disk(
                    self.active_skills,
                    bool(getattr(bs_tool, "in_workspace", True) and bs_tool.enabled),
                    bs_tool.project_scope,
                    self.projects_map,
                    lang=self.lang,
                    clients=dict(bs_tool.clients),
                    runtime_active=rt_active,
                )
            cv_tool = next((t for t in self.tools if t.id == "caveman"), None)
            if cv_tool:
                sync_caveman_on_disk(cv_tool, lang=self.lang, runtime_active=rt_active)
            sync_custom_skill_tools_on_disk(self.tools, lang=self.lang, runtime_active=rt_active)
            sync_mcp_json_clients(self.tools, self.vault, self.projects_map, lang=self.lang, runtime_active=rt_active)
            self._sync_live_environment_async(target_tools=list(self.tools))

        self._retranslate_ui()
        self._rebuild_kind_filter_combo()
        self._rebuild_tag_filter_combo()
        self._rebuild_project_filter_combo()
        self._rebuild_plugin_filter_combos()
        self._rebuild_profile_combo()
        self._rebuild_tray_menu()
        self._refresh_first_run_banner()
        self._refresh_table()
        self._refresh_plugins_tab()
        self.run_health_scan()

    # --- APP SELF-UPDATER (OFFICIAL REPO + SHA-256) ---
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
        repo = resolve_effective_app_repo()
        last_ts = float(self.meta.get("last_app_check_ts", 0.0) or 0.0)
        cached_remote = str(self.meta.get("cached_app_remote_ver", "") or "")
        if cached_remote and (time.time() - last_ts) < 1800:
            if parse_semver(cached_remote) <= parse_semver(get_current_app_version()):
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
        repo = resolve_effective_app_repo()
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
        if res.ok and res.remote_version:
            self.meta["last_app_check_ts"] = time.time()
            self.meta["cached_app_remote_ver"] = res.remote_version
            self._save_state()
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
