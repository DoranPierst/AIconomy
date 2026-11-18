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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...i18n import SUPPORTED_LANGUAGES, tr
from ...storage import WindowsDpapiVault
from ...updater import get_current_app_version

if TYPE_CHECKING:
    from ..main_window import MainWindow


class SettingsDialog(QDialog):
    """Application settings hosting General, API Keys, Projects, and Backup/Config controls."""

    TAB_GENERAL = 0
    TAB_KEYS = 1
    TAB_PROJECTS = 2
    TAB_BACKUP = 3

    def __init__(self, parent: "MainWindow", initial_tab: int = 0) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.lang = parent.lang
        self.setWindowTitle(tr(self.lang, "settings_title"))
        self.setMinimumSize(680, 480)
        self.resize(720, 520)

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

    # --- TAB 1: API KEYS (DPAPI VAULT) ---
    def _build_keys_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        lay.setContentsMargins(14, 14, 14, 14)

        desc = QLabel(tr(self.lang, "set_vault_desc"))
        desc.setWordWrap(True)
        lay.addWidget(desc)

        warn_card = QFrame()
        warn_card.setObjectName("bannerWarn")
        wl = QVBoxLayout(warn_card)
        wl.setContentsMargins(12, 8, 12, 8)
        warn_lbl = QLabel(tr(self.lang, "set_vault_warn"))
        warn_lbl.setWordWrap(True)
        warn_lbl.setStyleSheet("font-size: 11px;")
        wl.addWidget(warn_lbl)
        lay.addWidget(warn_card)

        self.vault_inputs: dict[str, QLineEdit] = {}
        self.vault_save_btns: dict[str, QPushButton] = {}
        for key_name, desc_key in WindowsDpapiVault.STANDARD_KEYS:
            card = QFrame()
            card.setObjectName("card")
            r = QHBoxLayout(card)
            r.setContentsMargins(12, 8, 12, 8)
            r.setSpacing(8)

            info = QLabel(f"<b>{key_name}</b><br><span style='color:#94a3b8; font-size:11px;'>{tr(self.lang, desc_key)}</span>")
            info.setFixedWidth(240)
            info.setWordWrap(True)
            r.addWidget(info)

            inp = QLineEdit(self.main_win.vault.get_secret(key_name))
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            inp.setPlaceholderText(tr(self.lang, "set_key_ph"))
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
            r.addWidget(btn_eye)

            btn_save = QPushButton(tr(self.lang, "set_key_save"))
            btn_save.setObjectName("primaryBtn")
            btn_save.setFixedWidth(74)
            btn_save.clicked.connect(lambda _=False, k=key_name: self._save_key(k))
            self.vault_save_btns[key_name] = btn_save
            r.addWidget(btn_save)
            lay.addWidget(card)

        lay.addStretch()
        self.tabs.addTab(w, tr(self.lang, "settings_tab_keys"))

    def _save_key(self, key_name: str) -> None:
        val = self.vault_inputs[key_name].text().strip()
        self.main_win.vault.set_secret(key_name, val)
        if val:
            msg = tr(self.lang, "msg_key_saved", key=key_name)
        else:
            msg = tr(self.lang, "msg_key_cleared", key=key_name)
        self.main_win.logs.add("INFO", tr(self.lang, "settings_tab_keys"), msg)
        self.main_win.set_status(msg)
        self.main_win._refresh_logs_tab()
        self.main_win._sync_live_environment_async(target_tools=[])
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
