"""Persistent SQLite log viewer tab mixin (emoji-free, port cleanup moved to Diagnostics)."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...ai_advisor import build_logs_ai_prompt
from ...auto_heal import HealPlan, classify_log_for_auto_heal
from ...i18n import tr
from ...updater import get_current_app_version
from ..widgets import HoverTableWidget


class LogsTabMixin:
    """Mixin implementing Tab 2 (Logs)."""

    def _init_logs_tab(self) -> None:
        self._current_logs: list[dict] = []
        self._log_heal_plans: dict[int, HealPlan] = {}
        self._selected_heal_plan: HealPlan | None = None
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.lbl_log_level = QLabel(tr(self.lang, "log_level_lbl"))
        top.addWidget(self.lbl_log_level)

        self.log_lvl_cmb = QComboBox()
        self.log_lvl_cmb.addItem(tr(self.lang, "log_level_all"), "ALL")
        for _lvl in ("ERR", "WARN", "INFO", "DBG"):
            self.log_lvl_cmb.addItem(_lvl, _lvl)
        self.log_lvl_cmb.currentIndexChanged.connect(self._refresh_logs_tab)
        top.addWidget(self.log_lvl_cmb)

        self.log_search_inp = QLineEdit()
        self.log_search_inp.setPlaceholderText(tr(self.lang, "log_search_ph"))
        self.log_search_inp.textChanged.connect(self._refresh_logs_tab)
        top.addWidget(self.log_search_inp, stretch=1)

        self.btn_log_wipe = QPushButton(tr(self.lang, "log_clear_all"))
        self.btn_log_wipe.clicked.connect(self._clear_all_logs)
        top.addWidget(self.btn_log_wipe)
        lay.addLayout(top)

        self.log_table = HoverTableWidget(0, 6, self)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setShowGrid(False)
        self.log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._update_log_headers()

        lh = self.log_table.horizontalHeader()
        lh.setMinimumHeight(32)
        lh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        lh.resizeSection(0, 38)
        self.log_table.setColumnWidth(0, 38)
        lh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        lh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        self.log_master_cb = QCheckBox(lh.viewport())
        self.log_master_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_master_cb.setGeometry(10, 7, 20, 18)
        self.log_master_cb.clicked.connect(lambda checked: self._set_log_checks("all" if checked else "none"))

        self.log_table.itemSelectionChanged.connect(self._on_log_row_selected)
        lay.addWidget(self.log_table, stretch=1)

        log_act_bar = QHBoxLayout()
        log_act_bar.setContentsMargins(0, 2, 0, 2)
        log_act_bar.setSpacing(6)

        self.lbl_log_sel = QLabel(tr(self.lang, "log_sel_count", n=0))
        self.lbl_log_sel.setStyleSheet("color: #94a3b8; font-weight: 600;")
        log_act_bar.addWidget(self.lbl_log_sel)

        self.btn_log_all = QPushButton(tr(self.lang, "log_sel_all"))
        self.btn_log_all.clicked.connect(lambda: self._set_log_checks("all"))
        log_act_bar.addWidget(self.btn_log_all)

        self.btn_log_err = QPushButton(tr(self.lang, "log_sel_issues"))
        self.btn_log_err.clicked.connect(lambda: self._set_log_checks("issues_only"))
        log_act_bar.addWidget(self.btn_log_err)

        self.btn_log_clr = QPushButton(tr(self.lang, "log_sel_clear"))
        self.btn_log_clr.clicked.connect(lambda: self._set_log_checks("none"))
        log_act_bar.addWidget(self.btn_log_clr)

        log_act_bar.addStretch()

        self.btn_log_fix = QPushButton(tr(self.lang, "log_btn_fix"))
        self.btn_log_fix.setObjectName("successBtn")
        self.btn_log_fix.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_log_fix.hide()
        self.btn_log_fix.clicked.connect(self._on_selected_log_fix_clicked)
        log_act_bar.addWidget(self.btn_log_fix)

        self.btn_copy_logs_ai = QPushButton(tr(self.lang, "log_copy_ai", n=0))
        self.btn_copy_logs_ai.setObjectName("primaryBtn")
        self.btn_copy_logs_ai.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_logs_ai.clicked.connect(self._copy_selected_logs_ai_prompt)
        log_act_bar.addWidget(self.btn_copy_logs_ai)
        lay.addLayout(log_act_bar)

        self.log_raw_view = QPlainTextEdit()
        self.log_raw_view.setReadOnly(True)
        self.log_raw_view.setFixedHeight(120)
        self.log_raw_view.setPlaceholderText(tr(self.lang, "log_raw_ph"))
        lay.addWidget(self.log_raw_view)

        self.tabs.addTab(tab, tr(self.lang, "tab_logs"))

    def _update_log_headers(self) -> None:
        self.log_table.setHorizontalHeaderLabels(
            [
                "",
                tr(self.lang, "log_col_time"),
                tr(self.lang, "log_col_level"),
                tr(self.lang, "log_col_tool"),
                tr(self.lang, "log_col_summary"),
                tr(self.lang, "log_col_action"),
            ]
        )

    def _refresh_logs_tab(self) -> None:
        lvl = str(self.log_lvl_cmb.currentData() or "ALL")
        q = self.log_search_inp.text()
        self._current_logs = self.logs.query(level=lvl, search=q)
        self.log_row_checks.clear()
        self._log_heal_plans.clear()
        self._selected_heal_plan = None
        if hasattr(self, "btn_log_fix"):
            self.btn_log_fix.hide()
        self.log_table.setRowCount(0)
        self.log_table.setRowCount(len(self._current_logs))
        for i, row in enumerate(self._current_logs):
            self.log_table.setRowHeight(i, 34)
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

            plan = classify_log_for_auto_heal(row, self.tools, self.vault, lang=self.lang)
            if plan is not None:
                self._log_heal_plans[log_id] = plan
                act_w = QWidget()
                act_w.setObjectName("cellBox")
                act_l = QHBoxLayout(act_w)
                act_l.setContentsMargins(4, 2, 6, 2)
                fix_btn = QPushButton(tr(self.lang, "log_btn_fix"))
                fix_btn.setObjectName("successBtn")
                fix_btn.setFixedHeight(24)
                fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                fix_btn.setToolTip(f"{plan.label}\n{plan.detail}")
                fix_btn.clicked.connect(lambda _=False, p=plan: self._run_log_auto_heal(p))
                act_l.addWidget(fix_btn)
                self.log_table.setCellWidget(i, 5, act_w)
            else:
                blank = QTableWidgetItem("")
                blank.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.log_table.setItem(i, 5, blank)
        self._update_tab_titles()
        self._update_log_selection_ui()

    def _jump_to_error_logs(self) -> None:
        idx = self.log_lvl_cmb.findData("ERR")
        if idx >= 0:
            self.log_lvl_cmb.setCurrentIndex(idx)
        self._refresh_logs_tab()
        self._set_log_checks("issues_only")
        self.tabs.setCurrentIndex(2)
        if self.log_table.rowCount() > 0:
            self.log_table.selectRow(0)

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
        self.lbl_log_sel.setText(tr(self.lang, "log_sel_count", n=sel_cnt))
        self.btn_copy_logs_ai.setText(tr(self.lang, "log_copy_ai", n=sel_cnt))
        vis_ids = {int(r["id"]) for r in self._current_logs}
        all_vis_checked = bool(vis_ids) and vis_ids.issubset(self.checked_log_ids)
        self.log_master_cb.blockSignals(True)
        self.log_master_cb.setChecked(all_vis_checked)
        self.log_master_cb.blockSignals(False)

    def _copy_selected_logs_ai_prompt(self) -> None:
        if not self.checked_log_ids:
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
                tr(self.lang, "log_none_sel_title"),
                tr(self.lang, "log_none_sel_msg"),
            )
            return

        all_recent = self.logs.query(limit=500)
        selected_entries = [e for e in all_recent if int(e["id"]) in self.checked_log_ids]
        selected_entries.sort(key=lambda x: int(x["id"]))

        gpu_txt = self.vram_lbl.text().strip() if hasattr(self, "vram_lbl") else ""
        prompt = build_logs_ai_prompt(
            selected_entries,
            self.tools,
            get_current_app_version(),
            gpu_txt,
            lang=self.lang,
            extra_secrets=self.vault.all_unlocked_values(),
        )
        QApplication.clipboard().setText(prompt)
        self.log_raw_view.setPlainText(prompt)
        self.set_status(tr(self.lang, "msg_logs_prompt_copied", n=len(selected_entries)))

        self.btn_copy_logs_ai.setText(tr(self.lang, "log_copied_ai", n=len(selected_entries)))
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
        self.set_status(tr(self.lang, "msg_logs_cleared"))

    def _on_selected_log_fix_clicked(self) -> None:
        if self._selected_heal_plan is not None:
            self._run_log_auto_heal(self._selected_heal_plan)

    def _on_log_row_selected(self) -> None:
        idxs = self.log_table.selectionModel().selectedRows()
        if not idxs:
            self._selected_heal_plan = None
            if hasattr(self, "btn_log_fix"):
                self.btn_log_fix.hide()
            return
        r = idxs[0].row()
        if 0 <= r < len(self._current_logs):
            entry = self._current_logs[r]
            self.log_raw_view.setPlainText(f"[{entry['ts']}] [{entry['level']}] {entry['tool']}\n{entry['raw_detail']}")
            plan = self._log_heal_plans.get(int(entry["id"]))
            self._selected_heal_plan = plan
            if hasattr(self, "btn_log_fix"):
                if plan is not None:
                    self.btn_log_fix.setText(tr(self.lang, "log_btn_fix_with", label=plan.label))
                    self.btn_log_fix.setToolTip(plan.detail)
                    self.btn_log_fix.show()
                else:
                    self.btn_log_fix.hide()
