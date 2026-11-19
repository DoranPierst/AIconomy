"""Manage saved user profiles dialog (Apply, Rename, Delete, Export, Import)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...i18n import tr

if TYPE_CHECKING:
    from ..main_window import MainWindow


class ManageProfilesDialog(QDialog):
    """Apply, rename, delete, export, or import saved user profiles."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.main_win = parent
        self.lang = parent.lang
        self.setWindowTitle(tr(self.lang, "prof_manage_title"))
        self.resize(520, 360)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        self.list_w = QListWidget()
        self.list_w.currentItemChanged.connect(self._update_buttons)
        self.list_w.itemDoubleClicked.connect(lambda _item: self._apply_selected())
        lay.addWidget(self.list_w, stretch=1)

        row1 = QHBoxLayout()
        self.btn_apply = QPushButton(tr(self.lang, "prof_btn_apply"))
        self.btn_apply.setObjectName("primaryBtn")
        self.btn_apply.clicked.connect(self._apply_selected)
        row1.addWidget(self.btn_apply)

        self.btn_rename = QPushButton(tr(self.lang, "prof_btn_rename"))
        self.btn_rename.clicked.connect(self._rename_selected)
        row1.addWidget(self.btn_rename)

        self.btn_delete = QPushButton(tr(self.lang, "prof_btn_delete"))
        self.btn_delete.clicked.connect(self._delete_selected)
        row1.addWidget(self.btn_delete)

        row1.addStretch()
        btn_exp = QPushButton(tr(self.lang, "set_cfg_export"))
        btn_exp.clicked.connect(self.main_win._export_settings)
        row1.addWidget(btn_exp)

        btn_imp = QPushButton(tr(self.lang, "set_cfg_import"))
        btn_imp.clicked.connect(lambda: (self.main_win._import_settings(), self._reload()))
        row1.addWidget(btn_imp)
        lay.addLayout(row1)

        bot = QHBoxLayout()
        btn_new = QPushButton(tr(self.lang, "btn_new_profile"))
        btn_new.setObjectName("newProfileBtn")
        btn_new.clicked.connect(lambda: (self.accept(), self.main_win.open_profile_wizard()))
        bot.addWidget(btn_new)
        bot.addStretch()
        btn_close = QPushButton(tr(self.lang, "btn_close"))
        btn_close.clicked.connect(self.accept)
        bot.addWidget(btn_close)
        lay.addLayout(bot)

        self._reload()

    def _reload(self) -> None:
        self.list_w.clear()
        presets = self.main_win._get_custom_presets()
        if not presets:
            empty = QListWidgetItem(tr(self.lang, "prof_manage_empty"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_w.addItem(empty)
        else:
            ordered = sorted(presets.items(), key=lambda kv: str(kv[1].get("saved_at", "")), reverse=True)
            for name, pdata in ordered:
                cnt = int(pdata.get("enabled_count", 0))
                ts = str(pdata.get("saved_at", ""))
                sub = tr(self.lang, "prof_manage_info", count=cnt, ts=ts)
                item = QListWidgetItem(f"{name}   ({sub})")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.list_w.addItem(item)
        self._update_buttons()

    def _selected_name(self) -> str:
        cur = self.list_w.currentItem()
        if cur is None:
            return ""
        return str(cur.data(Qt.ItemDataRole.UserRole) or "")

    def _update_buttons(self) -> None:
        has = bool(self._selected_name())
        self.btn_apply.setEnabled(has)
        self.btn_rename.setEnabled(has)
        self.btn_delete.setEnabled(has)

    def _apply_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        self.main_win.apply_custom_preset(name)
        self.accept()

    def _rename_selected(self) -> None:
        old = self._selected_name()
        if not old:
            return
        new_name, ok = QInputDialog.getText(
            self,
            tr(self.lang, "prof_rename_title"),
            tr(self.lang, "prof_rename_prompt", name=old),
            text=old,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old:
            return
        presets = self.main_win._get_custom_presets()
        pdata = presets.pop(old, None)
        if isinstance(pdata, dict):
            pdata["name"] = new_name
            presets[new_name] = pdata
            if self.main_win.meta.get("active_profile") == f"custom:{old}":
                self.main_win.meta["active_profile"] = f"custom:{new_name}"
            self.main_win._save_state()
            self.main_win._rebuild_profile_combo()
            self._reload()

    def _delete_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        ans = QMessageBox.question(
            self,
            tr(self.lang, "prof_delete_title"),
            tr(self.lang, "prof_delete_msg", name=name),
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        presets = self.main_win._get_custom_presets()
        presets.pop(name, None)
        if self.main_win.meta.get("active_profile") == f"custom:{name}":
            self.main_win.meta["active_profile"] = ""
        self.main_win._save_state()
        self.main_win._rebuild_profile_combo()
        self.main_win.set_status(tr(self.lang, "msg_profile_deleted", name=name))
        self._reload()
