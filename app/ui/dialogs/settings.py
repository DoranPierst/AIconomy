"""Unified Settings dialog: General, API Keys (DPAPI Vault), Projects, and Backup & Configs."""
from __future__ import annotations

import os
import pathlib
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...catalog import AI_CLIENTS, localized_tool_text
from ...i18n import SUPPORTED_LANGUAGES, tr
from ...updater import get_current_app_version

if TYPE_CHECKING:
    from ..main_window import MainWindow


class SettingsDialog(QDialog):
    """Application settings hosting General, API Keys, Projects, and Backup/Config controls."""

    TAB_GENERAL = 0
    TAB_KEYS = 1
    TAB_PROJECTS = 2
    TAB_BACKUP = 3

    def __init__(self, parent: "MainWindow", initial_tab: int = 0, focus_key: str = "") -> None:
        super().__init__(parent)
        self.main_win = parent
        self.lang = parent.lang
        self._focus_key = focus_key.strip()
        self.setWindowTitle(tr(self.lang, "settings_title"))
        self.setMinimumSize(700, 500)
        self.resize(760, 560)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        self._build_general_tab()
        self._build_keys_tab()
        self._build_projects_tab()
        self._build_backup_tab()

        if 0 <= initial_tab < self.tabs.count():
            self.tabs.setCurrentIndex(initial_tab)
        if self._focus_key and self._focus_key in self.vault_inputs:
            target_inp = self.vault_inputs[self._focus_key]
            self.keys_scroll.ensureWidgetVisible(target_inp)
            target_inp.setFocus()

        bot = QHBoxLayout()
        bot.addStretch()
        btn_close = QPushButton(tr(self.lang, "btn_close"))
        btn_close.setObjectName("primaryBtn")
        btn_close.clicked.connect(self.accept)
        bot.addWidget(btn_close)
        root.addLayout(bot)

    # --- TAB 0: GENERAL ---
    def _build_general_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.setContentsMargins(14, 14, 14, 14)

        form_card = QFrame()
        form_card.setObjectName("card")
        fl = QFormLayout(form_card)
        fl.setContentsMargins(14, 14, 14, 14)
        fl.setSpacing(12)

        self.lang_cmb = QComboBox()
        for code, lbl in SUPPORTED_LANGUAGES:
            self.lang_cmb.addItem(lbl, code)
        self.lang_cmb.setCurrentIndex(max(0, self.lang_cmb.findData(self.main_win.lang)))
        self.lang_cmb.currentIndexChanged.connect(self._on_lang_changed)
        fl.addRow(tr(self.lang, "set_lang_lbl"), self.lang_cmb)

        self.theme_cmb = QComboBox()
        self.theme_cmb.addItem(tr(self.lang, "set_theme_dark"), "dark")
        self.theme_cmb.addItem(tr(self.lang, "set_theme_light"), "light")
        self.theme_cmb.setCurrentIndex(0 if self.main_win.meta.get("theme", "dark") == "dark" else 1)
        self.theme_cmb.currentIndexChanged.connect(self._on_theme_changed)
        fl.addRow(tr(self.lang, "set_theme_lbl"), self.theme_cmb)

        ver_row = QHBoxLayout()
        ver_lbl = QLabel(f"v{get_current_app_version()}")
        ver_lbl.setStyleSheet("font-family: Consolas, monospace; font-weight: 600;")
        ver_row.addWidget(ver_lbl)
        ver_row.addStretch()
        btn_upd = QPushButton(tr(self.lang, "set_check_updates"))
        btn_upd.clicked.connect(lambda: self.main_win._open_app_update_dialog(self.main_win.latest_app_check))
        ver_row.addWidget(btn_upd)
        fl.addRow(tr(self.lang, "set_updates_lbl"), ver_row)

        clients_row = QHBoxLayout()
        clients_row.setSpacing(12)
        vis_now = set(self.main_win.get_visible_client_codes())
        self.client_vis_checks: dict[str, QCheckBox] = {}
        for code, full_lbl in AI_CLIENTS:
            is_det = code in self.main_win.installed_clients
            det_txt = tr(self.lang, "client_detected" if is_det else "client_not_detected")
            cb = QCheckBox(code)
            cb.setChecked(code in vis_now)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.setToolTip(f"{full_lbl} ({det_txt})")
            if not is_det:
                cb.setStyleSheet("color: #64748b;")
            cb.toggled.connect(lambda checked, c=code: self._on_visible_client_toggled(c, checked))
            self.client_vis_checks[code] = cb
            clients_row.addWidget(cb)
        clients_row.addStretch()
        fl.addRow(tr(self.lang, "set_clients_lbl"), clients_row)

        lay.addWidget(form_card)

        beh_card = QFrame()
        beh_card.setObjectName("card")
        bl = QVBoxLayout(beh_card)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(10)

        self.tray_cb = QCheckBox(tr(self.lang, "set_tray_cb"))
        self.tray_cb.setChecked(bool(self.main_win.meta.get("minimize_to_tray", True)))
        self.tray_cb.toggled.connect(self._on_tray_toggled)
        bl.addWidget(self.tray_cb)

        self.auto_detect_cb = QCheckBox(tr(self.lang, "set_autodetect_cb"))
        self.auto_detect_cb.setChecked(bool(self.main_win.meta.get("auto_detect_apps", True)))
        self.auto_detect_cb.toggled.connect(self._on_autodetect_toggled)
        bl.addWidget(self.auto_detect_cb)

        self.auto_stop_idle_cb = QCheckBox(tr(self.lang, "set_autostop_idle_cb"))
        self.auto_stop_idle_cb.setChecked(bool(self.main_win.meta.get("auto_stop_idle_http", False)))
        self.auto_stop_idle_cb.toggled.connect(self._on_autostop_idle_toggled)
        bl.addWidget(self.auto_stop_idle_cb)

        lay.addWidget(beh_card)
        lay.addStretch()
        self.tabs.addTab(w, tr(self.lang, "settings_tab_general"))

    def _on_lang_changed(self) -> None:
        code = str(self.lang_cmb.currentData() or "en")
        self.main_win.set_language(code)
        self.lang = self.main_win.lang
        self.setWindowTitle(tr(self.lang, "settings_title"))

    def _on_theme_changed(self) -> None:
        mode = str(self.theme_cmb.currentData() or "dark")
        self.main_win.set_theme(mode)

    def _on_tray_toggled(self, checked: bool) -> None:
        self.main_win.meta["minimize_to_tray"] = checked
        self.main_win._save_state()

    def _on_autodetect_toggled(self, checked: bool) -> None:
        self.main_win.meta["auto_detect_apps"] = checked
        self.main_win._save_state()

    def _on_autostop_idle_toggled(self, checked: bool) -> None:
        self.main_win.meta["auto_stop_idle_http"] = checked
        self.main_win._no_client_seconds = 0
        self.main_win._save_state()

    def _on_visible_client_toggled(self, code: str, checked: bool) -> None:
        selected = [c for c, _ in AI_CLIENTS if self.client_vis_checks[c].isChecked()]
        if not selected:
            cb = self.client_vis_checks[code]
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
            return
        self.main_win.meta["visible_clients"] = selected
        self.main_win._save_state()
        self.main_win._refresh_table()

    # --- TAB 1: API KEYS (DYNAMIC DPAPI VAULT) ---
    def _collect_vault_key_rows(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = [("GITHUB_TOKEN", tr(self.lang, "set_key_github"))]
        seen: set[str] = {"GITHUB_TOKEN"}

        for t in self.main_win.tools:
            if not getattr(t, "in_workspace", True) or not t.vault_key_name:
                continue
            k_name = t.vault_key_name.strip()
            if not k_name or k_name in seen:
                continue
            seen.add(k_name)
            desc_txt = localized_tool_text(t, "vault_key_desc", self.lang)
            if not desc_txt:
                desc_txt = tr(self.lang, "set_key_for_tool", name=t.name)
            rows.append((k_name, desc_txt))

        for saved_k in sorted(self.main_win.vault._read_map().keys()):
            if not saved_k or saved_k in seen:
                continue
            seen.add(saved_k)
            match_t = next((x for x in self.main_win.tools if x.vault_key_name == saved_k), None)
            if match_t is not None:
                desc_txt = localized_tool_text(match_t, "vault_key_desc", self.lang) or tr(
                    self.lang, "set_key_for_tool", name=match_t.name
                )
            else:
                desc_txt = tr(self.lang, "set_key_saved_custom")
            rows.append((saved_k, desc_txt))

        return rows

    def _build_keys_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        lay.setContentsMargins(14, 14, 14, 14)

        desc = QLabel(tr(self.lang, "set_vault_desc"))
        desc.setWordWrap(True)
        lay.addWidget(desc)

        warn_card = QFrame()
        warn_card.setObjectName("bannerInfo")
        wl = QVBoxLayout(warn_card)
        wl.setContentsMargins(12, 8, 12, 8)
        warn_lbl = QLabel(tr(self.lang, "set_vault_warn"))
        warn_lbl.setWordWrap(True)
        warn_lbl.setStyleSheet("font-size: 11px;")
        wl.addWidget(warn_lbl)
        lay.addWidget(warn_card)

        pin_card = QFrame()
        pin_card.setObjectName("card")
        pin_lay = QHBoxLayout(pin_card)
        pin_lay.setContentsMargins(12, 8, 12, 8)
        pin_lay.setSpacing(8)

        pin_info = QVBoxLayout()
        pin_info.setSpacing(2)
        pin_info.addWidget(QLabel(f"<b>{tr(self.lang, 'set_pin_hdr')}</b>"))
        self.pin_status_lbl = QLabel("")
        self.pin_status_lbl.setWordWrap(True)
        self.pin_status_lbl.setStyleSheet("font-size: 11px;")
        pin_info.addWidget(self.pin_status_lbl)
        pin_lay.addLayout(pin_info, stretch=1)

        self.btn_pin_set = QPushButton(tr(self.lang, "set_pin_btn_set"))
        self.btn_pin_set.clicked.connect(self._prompt_set_or_change_pin)
        pin_lay.addWidget(self.btn_pin_set)

        self.btn_pin_unlock = QPushButton(tr(self.lang, "set_pin_btn_unlock"))
        self.btn_pin_unlock.setObjectName("primaryBtn")
        self.btn_pin_unlock.clicked.connect(self._prompt_unlock_pin)
        pin_lay.addWidget(self.btn_pin_unlock)

        self.btn_pin_lock = QPushButton(tr(self.lang, "set_pin_btn_lock"))
        self.btn_pin_lock.clicked.connect(self._lock_vault_now)
        pin_lay.addWidget(self.btn_pin_lock)

        self.btn_pin_remove = QPushButton(tr(self.lang, "set_pin_btn_remove"))
        self.btn_pin_remove.clicked.connect(self._prompt_remove_pin)
        pin_lay.addWidget(self.btn_pin_remove)
        lay.addWidget(pin_card)

        self.keys_scroll = QScrollArea()
        self.keys_scroll.setWidgetResizable(True)
        self.keys_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.keys_scroll.viewport().setObjectName("cellBox")
        keys_host = QWidget()
        keys_host.setObjectName("cellBox")
        keys_lay = QVBoxLayout(keys_host)
        keys_lay.setContentsMargins(0, 0, 4, 0)
        keys_lay.setSpacing(8)
        self.keys_scroll.setWidget(keys_host)

        self.vault_inputs: dict[str, QLineEdit] = {}
        self.vault_eye_btns: dict[str, QPushButton] = {}
        self.vault_save_btns: dict[str, QPushButton] = {}
        for key_name, desc_txt in self._collect_vault_key_rows():
            card = QFrame()
            card.setObjectName("card")
            r = QHBoxLayout(card)
            r.setContentsMargins(12, 8, 12, 8)
            r.setSpacing(8)

            info = QLabel(
                f"<b>{key_name}</b><br><span style='color:#94a3b8; font-size:11px;'>{desc_txt}</span>"
            )
            info.setFixedWidth(250)
            info.setWordWrap(True)
            r.addWidget(info)

            inp = QLineEdit()
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            self.vault_inputs[key_name] = inp
            r.addWidget(inp, stretch=1)

            btn_eye = QPushButton(tr(self.lang, "set_key_show"))
            btn_eye.setFixedWidth(64)
            btn_eye.setCheckable(True)
            btn_eye.toggled.connect(
                lambda checked, ed=inp, b=btn_eye: (
                    ed.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password),
                    b.setText(tr(self.lang, "set_key_hide") if checked else tr(self.lang, "set_key_show")),
                )
            )
            self.vault_eye_btns[key_name] = btn_eye
            r.addWidget(btn_eye)

            btn_save = QPushButton(tr(self.lang, "set_key_save"))
            btn_save.setObjectName("primaryBtn")
            btn_save.setFixedWidth(80)
            btn_save.clicked.connect(lambda _=False, k=key_name: self._save_key(k))
            self.vault_save_btns[key_name] = btn_save
            r.addWidget(btn_save)
            keys_lay.addWidget(card)

        keys_lay.addStretch()
        lay.addWidget(self.keys_scroll, stretch=1)
        self._refresh_pin_and_key_rows()
        self.tabs.addTab(w, tr(self.lang, "settings_tab_keys"))

    def _refresh_pin_and_key_rows(self) -> None:
        vault = self.main_win.vault
        pin_on = vault.is_passphrase_enabled()
        locked = vault.is_locked()

        if not pin_on:
            self.pin_status_lbl.setText(f"<span style='color:#94a3b8;'>{tr(self.lang, 'set_pin_status_off')}</span>")
            self.btn_pin_set.setText(tr(self.lang, "set_pin_btn_set"))
            self.btn_pin_set.show()
            self.btn_pin_unlock.hide()
            self.btn_pin_lock.hide()
            self.btn_pin_remove.hide()
        elif locked:
            self.pin_status_lbl.setText(
                f"<span style='color:#f59e0b; font-weight:600;'>{tr(self.lang, 'set_pin_status_locked')}</span>"
            )
            self.btn_pin_set.hide()
            self.btn_pin_unlock.show()
            self.btn_pin_lock.hide()
            self.btn_pin_remove.hide()
        else:
            self.pin_status_lbl.setText(
                f"<span style='color:#10b981; font-weight:600;'>{tr(self.lang, 'set_pin_status_unlocked')}</span>"
            )
            self.btn_pin_set.setText(tr(self.lang, "set_pin_btn_change"))
            self.btn_pin_set.show()
            self.btn_pin_unlock.hide()
            self.btn_pin_lock.show()
            self.btn_pin_remove.show()

        ph = tr(self.lang, "set_key_locked_ph" if locked else "set_key_ph")
        for k_name, inp in self.vault_inputs.items():
            inp.setEnabled(not locked)
            inp.setPlaceholderText(ph)
            if locked:
                inp.setText("")
                inp.setEchoMode(QLineEdit.EchoMode.Password)
            else:
                inp.setText(vault.get_secret(k_name))
            eye = self.vault_eye_btns.get(k_name)
            if eye is not None:
                if locked and eye.isChecked():
                    eye.setChecked(False)
                eye.setEnabled(not locked)
            s_btn = self.vault_save_btns.get(k_name)
            if s_btn is not None:
                s_btn.setEnabled(not locked)

    def _prompt_unlock_pin(self) -> bool:
        pwd, ok = QInputDialog.getText(
            self,
            tr(self.lang, "set_pin_dlg_unlock_title"),
            tr(self.lang, "set_pin_dlg_unlock_prompt"),
            QLineEdit.EchoMode.Password,
        )
        if not ok or not pwd:
            return False
        if not self.main_win.vault.unlock(pwd):
            QMessageBox.warning(self, tr(self.lang, "set_pin_dlg_unlock_title"), tr(self.lang, "set_pin_err_wrong"))
            return False
        msg = tr(self.lang, "msg_pin_unlocked")
        self.main_win.logs.add("INFO", tr(self.lang, "settings_tab_keys"), msg)
        self.main_win.set_status(msg)
        self.main_win._refresh_logs_tab()
        self._refresh_pin_and_key_rows()
        return True

    def _prompt_set_or_change_pin(self) -> None:
        if self.main_win.vault.is_locked() and not self._prompt_unlock_pin():
            return
        pwd1, ok1 = QInputDialog.getText(
            self,
            tr(self.lang, "set_pin_dlg_set_title"),
            tr(self.lang, "set_pin_dlg_set_prompt"),
            QLineEdit.EchoMode.Password,
        )
        if not ok1:
            return
        if len(pwd1.strip()) < 4:
            QMessageBox.warning(self, tr(self.lang, "set_pin_dlg_set_title"), tr(self.lang, "set_pin_err_short"))
            return
        pwd2, ok2 = QInputDialog.getText(
            self,
            tr(self.lang, "set_pin_dlg_set_title"),
            tr(self.lang, "set_pin_dlg_confirm_prompt"),
            QLineEdit.EchoMode.Password,
        )
        if not ok2:
            return
        if pwd1 != pwd2:
            QMessageBox.warning(self, tr(self.lang, "set_pin_dlg_set_title"), tr(self.lang, "set_pin_err_mismatch"))
            return
        if self.main_win.vault.set_passphrase(pwd1):
            msg = tr(self.lang, "msg_pin_enabled")
            self.main_win.logs.add("INFO", tr(self.lang, "settings_tab_keys"), msg)
            self.main_win.set_status(msg)
            self.main_win._refresh_logs_tab()
            self._refresh_pin_and_key_rows()

    def _lock_vault_now(self) -> None:
        self.main_win.vault.lock()
        msg = tr(self.lang, "msg_pin_locked")
        self.main_win.logs.add("INFO", tr(self.lang, "settings_tab_keys"), msg)
        self.main_win.set_status(msg)
        self.main_win._refresh_logs_tab()
        self._refresh_pin_and_key_rows()

    def _prompt_remove_pin(self) -> None:
        if self.main_win.vault.is_locked() and not self._prompt_unlock_pin():
            return
        if self.main_win.vault.set_passphrase(""):
            msg = tr(self.lang, "msg_pin_removed")
            self.main_win.logs.add("INFO", tr(self.lang, "settings_tab_keys"), msg)
            self.main_win.set_status(msg)
            self.main_win._refresh_logs_tab()
            self._refresh_pin_and_key_rows()

    def _save_key(self, key_name: str) -> None:
        if self.main_win.vault.is_locked():
            if not self._prompt_unlock_pin():
                return
        val = self.vault_inputs[key_name].text().strip()
        self.main_win.vault.set_secret(key_name, val)
        if val:
            msg = tr(self.lang, "msg_key_saved", key=key_name)
        else:
            msg = tr(self.lang, "msg_key_cleared", key=key_name)
        self.main_win.logs.add("INFO", tr(self.lang, "settings_tab_keys"), msg)
        self.main_win.set_status(msg)
        self.main_win._refresh_logs_tab()
        self.main_win.run_health_scan()
        self.main_win._sync_live_environment_async(target_tools=list(self.main_win.tools))
        btn = self.vault_save_btns[key_name]
        btn.setText(tr(self.lang, "set_key_saved"))
        btn.setObjectName("successBtn")
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    # --- TAB 2: PROJECTS (ADD / RENAME / REMOVE) ---
    def _build_projects_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        lay.setContentsMargins(14, 14, 14, 14)

        desc = QLabel(tr(self.lang, "set_proj_desc"))
        desc.setWordWrap(True)
        lay.addWidget(desc)

        self.proj_list = QListWidget()
        self.proj_list.currentItemChanged.connect(self._update_proj_buttons)
        lay.addWidget(self.proj_list, stretch=1)

        btns = QHBoxLayout()
        btn_add = QPushButton(tr(self.lang, "set_proj_add"))
        btn_add.setObjectName("primaryBtn")
        btn_add.clicked.connect(self._add_project)
        btns.addWidget(btn_add)

        self.btn_proj_rename = QPushButton(tr(self.lang, "set_proj_rename"))
        self.btn_proj_rename.clicked.connect(self._rename_project)
        btns.addWidget(self.btn_proj_rename)

        self.btn_proj_remove = QPushButton(tr(self.lang, "set_proj_remove"))
        self.btn_proj_remove.clicked.connect(self._remove_project)
        btns.addWidget(self.btn_proj_remove)
        btns.addStretch()
        lay.addLayout(btns)

        self._reload_projects()
        self.tabs.addTab(w, tr(self.lang, "settings_tab_projects"))

    def _reload_projects(self) -> None:
        self.proj_list.clear()
        pmap = self.main_win.projects_map
        if not pmap:
            empty = QListWidgetItem(tr(self.lang, "set_proj_empty"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.proj_list.addItem(empty)
        else:
            for name in sorted(pmap.keys()):
                item = QListWidgetItem(f"{name}   —   {pmap[name]}")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.proj_list.addItem(item)
        self._update_proj_buttons()

    def _selected_project_key(self) -> str:
        cur = self.proj_list.currentItem()
        if cur is None:
            return ""
        return str(cur.data(Qt.ItemDataRole.UserRole) or "")

    def _update_proj_buttons(self) -> None:
        has_sel = bool(self._selected_project_key())
        self.btn_proj_rename.setEnabled(has_sel)
        self.btn_proj_remove.setEnabled(has_sel)

    def _add_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr(self.lang, "set_proj_pick"))
        if not folder:
            return
        p_path = pathlib.Path(folder)
        key = p_path.name
        self.main_win.projects_map[key] = str(p_path)
        self.main_win._save_state()
        self.main_win._rebuild_project_filter_combo()
        self.main_win._refresh_table()
        self.main_win.set_status(tr(self.lang, "msg_proj_added", name=key))
        self._reload_projects()

    def _rename_project(self) -> None:
        old_key = self._selected_project_key()
        if not old_key:
            return
        new_key, ok = QInputDialog.getText(
            self,
            tr(self.lang, "set_proj_rename_title"),
            tr(self.lang, "set_proj_rename_prompt", name=old_key),
            text=old_key,
        )
        if not ok:
            return
        new_key = new_key.strip()
        if not new_key or new_key == old_key or new_key == "GLOBAL":
            return
        pmap = self.main_win.projects_map
        path_val = pmap.pop(old_key, "")
        if path_val:
            pmap[new_key] = path_val
            for t in self.main_win.tools:
                if t.project_scope == old_key:
                    t.project_scope = new_key
            self.main_win._save_state()
            self.main_win._rebuild_project_filter_combo()
            self.main_win._refresh_table()
            self.main_win.set_status(tr(self.lang, "msg_proj_renamed", name=new_key))
            self._reload_projects()

    def _remove_project(self) -> None:
        key = self._selected_project_key()
        if not key:
            return
        ans = QMessageBox.question(
            self,
            tr(self.lang, "set_proj_remove_title"),
            tr(self.lang, "set_proj_remove_msg", name=key),
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.main_win.projects_map.pop(key, None)
        for t in self.main_win.tools:
            if t.project_scope == key:
                t.project_scope = "GLOBAL"
        self.main_win._save_state()
        self.main_win._rebuild_project_filter_combo()
        self.main_win._refresh_table()
        self.main_win._sync_live_environment_async(target_tools=[])
        self.main_win.set_status(tr(self.lang, "msg_proj_removed", name=key))
        self._reload_projects()

    # --- TAB 3: BACKUP & CONFIGS ---
    def _build_backup_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.setContentsMargins(14, 14, 14, 14)

        desc = QLabel(tr(self.lang, "set_cfg_desc"))
        desc.setWordWrap(True)
        lay.addWidget(desc)

        act_row = QHBoxLayout()
        btn_reapply = QPushButton(tr(self.lang, "set_cfg_reapply"))
        btn_reapply.setObjectName("primaryBtn")
        btn_reapply.clicked.connect(self.main_win._handle_sync_configs)
        act_row.addWidget(btn_reapply)

        btn_exp = QPushButton(tr(self.lang, "set_cfg_export"))
        btn_exp.clicked.connect(self.main_win._export_settings)
        act_row.addWidget(btn_exp)

        btn_imp = QPushButton(tr(self.lang, "set_cfg_import"))
        btn_imp.clicked.connect(self.main_win._import_settings)
        act_row.addWidget(btn_imp)
        act_row.addStretch()
        lay.addLayout(act_row)

        home = pathlib.Path.home()
        paths_card = QFrame()
        paths_card.setObjectName("card")
        pl = QVBoxLayout(paths_card)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.setSpacing(5)
        for client_lbl, p_str in (
            ("Antigravity (AGY)", str(home / ".gemini" / "config" / "mcp_config.json")),
            ("Codex (CDX)", str(home / ".codex" / "config.toml")),
            ("Claude Code (CLD)", f"{home / '.claude.json'}  |  <project>\\.mcp.json"),
            ("Cursor (CUR)", f"{home / '.cursor' / 'mcp.json'}  |  <project>\\.cursor\\mcp.json"),
        ):
            lbl = QLabel(f"<b>{client_lbl}:</b>  <span style='color:#94a3b8; font-family:Consolas,monospace; font-size:11px;'>{p_str}</span>")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            pl.addWidget(lbl)
        lay.addWidget(paths_card)

        data_row = QHBoxLayout()
        data_row.addWidget(QLabel(f"<b>{tr(self.lang, 'set_cfg_data_dir')}</b>"))
        dir_lbl = QLabel(str(self.main_win.data_dir))
        dir_lbl.setStyleSheet("color: #94a3b8; font-family: Consolas, monospace; font-size: 11px;")
        dir_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        data_row.addWidget(dir_lbl, stretch=1)

        btn_open = QPushButton(tr(self.lang, "set_cfg_open_dir"))
        btn_open.clicked.connect(self._open_data_dir)
        data_row.addWidget(btn_open)
        lay.addLayout(data_row)

        lay.addStretch()
        self.tabs.addTab(w, tr(self.lang, "settings_tab_backup").replace("&", "&&"))

    def _open_data_dir(self) -> None:
        try:
            os.startfile(str(self.main_win.data_dir))  # type: ignore[attr-defined]
        except Exception:
            pass
