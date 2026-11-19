"""Profile management mixin: built-in profiles, custom presets, and task-wizard profile application."""
from __future__ import annotations

import datetime as dt
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QDialog, QInputDialog, QMessageBox

from ...catalog import PROFILES, ToolSpec, profile_desc, profile_title
from ...i18n import tr
from ...processes import resolve_disk_location
from ..dialogs import ManageProfilesDialog, ProfileWizardDialog


class ProfilesMixin:
    """Mixin handling profile selector combobox, custom presets, and task-wizard profiles."""

    def _get_custom_presets(self) -> dict[str, dict[str, Any]]:
        raw = self.meta.get("custom_presets")
        if not isinstance(raw, dict):
            raw = {}
            self.meta["custom_presets"] = raw
        return raw

    def get_active_profile_tags(self) -> set[str]:
        """Return the canonical tag IDs associated with the currently selected top profile, if any."""
        cur_active = str(self.meta.get("active_profile", "") or "")
        if cur_active.startswith("builtin:"):
            p_key = cur_active.split(":", 1)[1]
            return {str(x) for x in PROFILES.get(p_key, {}).get("tags", [])}
        if cur_active.startswith("custom:"):
            p_name = cur_active.split(":", 1)[1]
            pdata = self._get_custom_presets().get(p_name, {})
            if isinstance(pdata, dict) and isinstance(pdata.get("tags"), list):
                return {str(x) for x in pdata["tags"]}
        return set()

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
        self.profile_cmb.addItem(tr(self.lang, "profile_create_wizard"), "__WIZARD__")
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
        if data == "__WIZARD__":
            self._rebuild_profile_combo()
            self.open_profile_wizard()
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
        has_custom_active = (not self.meta.get("active_profile")) and any(t.enabled for t in self.workspace_tools())
        if ask_confirm and has_custom_active:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle(tr(self.lang, "prof_confirm_title"))
            msg_box.setText(f"<b>{tr(self.lang, 'prof_confirm_hdr', name=title)}</b>")
            msg_box.setInformativeText(tr(self.lang, "prof_confirm_body"))
            btn_save_go = msg_box.addButton(tr(self.lang, "prof_btn_save_switch"), QMessageBox.ButtonRole.AcceptRole)
            msg_box.addButton(tr(self.lang, "prof_btn_switch"), QMessageBox.ButtonRole.DestructiveRole)
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
            if t.id in target_enable and not getattr(t, "in_workspace", True):
                t.in_workspace = True
        for t in self.tools:
            if not getattr(t, "in_workspace", True):
                t.enabled = False
                continue
            t.enabled = t.id in target_enable
            if not t.enabled:
                t.health_state = "off"
                t.last_ping = tr(self.lang, "st_disabled")
            elif self._tool_needs_vault_key(t):
                t.health_state = "warn"
                t.last_ping = tr(self.lang, "st_missing_key")

        self.meta["active_profile"] = f"builtin:{profile_key}"
        self.meta["first_run_dismissed"] = True
        self._refresh_first_run_banner()
        self._save_state()
        self._rebuild_tag_filter_combo()
        self._rebuild_plugin_filter_combos()
        self._update_tab_titles()
        self._rebuild_profile_combo()

        en_cnt = sum(1 for t in self.workspace_tools() if t.enabled)
        msg = tr(self.lang, "msg_profile_applied", name=title, n=en_cnt)
        self.logs.add("INFO", tr(self.lang, "log_src_profile"), msg)
        self._set_config_status(msg)
        self._refresh_table()
        self._refresh_plugins_tab()
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
            "enabled_count": sum(1 for t in self.workspace_tools() if t.enabled),
            "active_blender_skills": sorted(self.active_skills),
            "tools": {
                t.id: {
                    "in_workspace": True,
                    "enabled": bool(t.enabled),
                    "auth_mode": str(getattr(t, "auth_mode", "key")),
                    "clients": dict(t.clients),
                    "project_scope": t.project_scope,
                    "mode_index": int(t.mode_index),
                    "param_value": t.param_value,
                    "options": {o.key: bool(o.enabled) for o in t.options},
                }
                for t in self.workspace_tools()
            },
        }
        self.meta["active_profile"] = f"custom:{name}"
        self._save_state()
        self._rebuild_profile_combo()
        self._rebuild_tray_menu()
        msg = tr(self.lang, "msg_profile_saved", name=name)
        self.logs.add("INFO", tr(self.lang, "log_src_profile"), msg)
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
                    t.enabled = False
                    continue
                if saved.get("enabled") or saved.get("in_workspace"):
                    t.in_workspace = True
                if "enabled" in saved:
                    t.enabled = bool(saved["enabled"]) and bool(getattr(t, "in_workspace", True))
                if saved.get("auth_mode") in ("key", "oauth"):
                    t.auth_mode = str(saved["auth_mode"])
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
                    if t.id in ("serena", "unity_mcp", "blender_mcp") and t.param_value.isdigit():
                        p_int = int(t.param_value)
                        if 1 <= p_int <= 65535:
                            t.port = p_int
                if isinstance(saved.get("options"), dict):
                    for o in t.options:
                        if o.key in saved["options"]:
                            o.enabled = bool(saved["options"][o.key])

        for t in self.workspace_tools():
            if not t.enabled:
                t.health_state = "off"
                t.last_ping = tr(self.lang, "st_disabled")
            elif self._tool_needs_vault_key(t):
                t.health_state = "warn"
                t.last_ping = tr(self.lang, "st_missing_key")

        if isinstance(pdata.get("active_blender_skills"), list):
            self.active_skills = {str(s) for s in pdata["active_blender_skills"]}

        self.meta["active_profile"] = f"custom:{name}"
        self.meta["first_run_dismissed"] = True
        self._refresh_first_run_banner()
        self._save_state()
        self._rebuild_tag_filter_combo()
        self._rebuild_plugin_filter_combos()
        self._update_tab_titles()
        self._rebuild_profile_combo()

        en_cnt = sum(1 for t in self.workspace_tools() if t.enabled)
        msg = tr(self.lang, "msg_profile_applied", name=name, n=en_cnt)
        self.logs.add("INFO", tr(self.lang, "log_src_profile"), msg)
        self._set_config_status(msg)
        self._refresh_table()
        self._refresh_plugins_tab()
        self._refresh_logs_tab()
        self._sync_live_environment_async(target_tools=list(self.tools))

    def open_profile_wizard(self) -> None:
        dlg = ProfileWizardDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_name:
            self.apply_wizard_profile(
                dlg.result_name,
                dlg.result_tool_ids,
                dlg.result_skills,
                dlg.result_tags,
            )

    def apply_wizard_profile(
        self,
        name: str,
        enabled_tool_ids: set[str],
        blender_skills: set[str],
        selected_tags: list[str] | None = None,
    ) -> None:
        """Save a task-wizard profile, activate installed tools, and download any newly selected library tools."""
        need_download: list[ToolSpec] = []
        for t in self.tools:
            if t.id in enabled_tool_ids and not getattr(t, "in_workspace", True):
                if not getattr(t, "installed", False) and self.sync_live_environment:
                    need_download.append(t)
                else:
                    t.installed = True
                    t.in_workspace = True
                    t.live_location_detail = resolve_disk_location(
                        t, self.projects_map, self._latest_live_map, lang=self.lang
                    )

        for t in self.tools:
            if not getattr(t, "in_workspace", True):
                t.enabled = False
                continue
            t.enabled = t.id in enabled_tool_ids
            if t.enabled and not any(t.clients.values()):
                t.clients["AGY"] = True
            if not t.enabled:
                t.health_state = "off"
                t.last_ping = tr(self.lang, "st_disabled")
            elif self._tool_needs_vault_key(t):
                t.health_state = "warn"
                t.last_ping = tr(self.lang, "st_missing_key")
            elif t.port:
                t.health_state = "idle"
                t.last_ping = tr(self.lang, "st_scanning")
            elif t.id == "blender_skills":
                t.health_state = "ok"
                t.last_ping = tr(self.lang, "st_active_count", on=len(blender_skills))
            else:
                t.health_state = "ok"
                t.last_ping = tr(self.lang, "st_ready")

        self.active_skills = set(blender_skills)
        presets = self._get_custom_presets()
        presets[name] = {
            "name": name,
            "saved_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "enabled_count": sum(1 for t in self.workspace_tools() if t.enabled),
            "tags": list(selected_tags or []),
            "active_blender_skills": sorted(self.active_skills),
            "tools": {
                t.id: {
                    "in_workspace": True,
                    "enabled": bool(t.enabled),
                    "auth_mode": str(getattr(t, "auth_mode", "key")),
                    "clients": dict(t.clients),
                    "project_scope": t.project_scope,
                    "mode_index": int(t.mode_index),
                    "param_value": t.param_value,
                    "options": {o.key: bool(o.enabled) for o in t.options},
                }
                for t in self.workspace_tools()
            },
        }
        self.meta["active_profile"] = f"custom:{name}"
        self.meta["first_run_dismissed"] = True
        self._refresh_first_run_banner()
        self._save_state()
        self._rebuild_tag_filter_combo()
        self._rebuild_plugin_filter_combos()
        self._update_tab_titles()
        self._rebuild_profile_combo()
        self._rebuild_tray_menu()

        en_cnt = sum(1 for t in self.workspace_tools() if t.enabled)
        msg = tr(self.lang, "msg_profile_applied", name=name, n=en_cnt)
        self.logs.add("INFO", tr(self.lang, "log_src_profile"), msg)
        self._set_config_status(msg)
        self._refresh_table()
        self._refresh_plugins_tab()
        self._refresh_logs_tab()
        self._sync_live_environment_async(target_tools=list(self.tools))
        if need_download:
            self.tabs.setCurrentIndex(1)
            self._run_library_install(need_download, enable_after=True)
