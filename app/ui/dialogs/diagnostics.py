"""Unified Diagnostics dialog: per-client & global E2E MCP tests, dry-run when stopped, reports, and port cleanup."""
from __future__ import annotations

import copy
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...catalog import AI_CLIENTS
from ...diagnostics import inspect_client_config_file, test_tool_for_client_e2e
from ...i18n import tr
from ..workers import WorkerBridge, safe_emit

if TYPE_CHECKING:
    from ..main_window import MainWindow


class DiagnosticsDialog(QDialog):
    """Run live or dry-run E2E MCP handshakes globally or per AI client (AGY/CDX/CLD/CUR), copy reports, free ports."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.main_win = parent
        self.lang = parent.lang
        self.tools = [copy.deepcopy(t) for t in parent.tools if getattr(t, "in_workspace", True) and t.enabled]
        self._running = False
        self._run_gen = 0
        self._bridge = WorkerBridge()
        self._bridge.conn_test_row.connect(self._on_row_result)
        self._bridge.conn_test_cfg.connect(self._on_client_cfg_status)
        self._bridge.conn_test_done.connect(self._on_all_done)

        self.setWindowTitle(tr(self.lang, "diag_title"))
        self.resize(900, 610)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        info = QLabel(tr(self.lang, "diag_desc"))
        info.setWordWrap(True)
        lay.addWidget(info)

        top_actions = QHBoxLayout()
        top_actions.setSpacing(6)

        lbl_target = QLabel(tr(self.lang, "diag_target_lbl"))
        lbl_target.setStyleSheet("font-weight: 600;")
        top_actions.addWidget(lbl_target)

        self.client_cmb = QComboBox()
        self.client_cmb.setMinimumWidth(165)
        self.client_cmb.addItem(tr(self.lang, "diag_target_all"), "ALL")
        for code, full_name in AI_CLIENTS:
            self.client_cmb.addItem(f"{full_name} ({code})", code)
        self.client_cmb.currentIndexChanged.connect(lambda _idx: self.start_tests(force_dry_run=True, interrupt_running=True))
        top_actions.addWidget(self.client_cmb)

        self.btn_retest = QPushButton(tr(self.lang, "diag_btn_retest"))
        self.btn_retest.setObjectName("primaryBtn")
        self.btn_retest.clicked.connect(lambda: self.start_tests(force_dry_run=True))
        top_actions.addWidget(self.btn_retest)

        self.btn_start_now = QPushButton(tr(self.lang, "diag_btn_start_now"))
        self.btn_start_now.setObjectName("successBtn")
        self.btn_start_now.hide()
        self.btn_start_now.clicked.connect(self._handle_start_and_retest)
        top_actions.addWidget(self.btn_start_now)

        btn_scan = QPushButton(tr(self.lang, "diag_btn_scan"))
        btn_scan.clicked.connect(self.main_win.run_health_scan)
        top_actions.addWidget(btn_scan)

        top_actions.addStretch()

        btn_copy_en = QPushButton(tr(self.lang, "diag_btn_copy_enabled"))
        btn_copy_en.clicked.connect(lambda: self.main_win.copy_tools_status_report(enabled_only=True))
        top_actions.addWidget(btn_copy_en)

        btn_copy_all = QPushButton(tr(self.lang, "diag_btn_copy_all"))
        btn_copy_all.clicked.connect(lambda: self.main_win.copy_tools_status_report(enabled_only=False))
        top_actions.addWidget(btn_copy_all)
        lay.addLayout(top_actions)

        self.client_cfg_lbl = QLabel("")
        self.client_cfg_lbl.setWordWrap(True)
        self.client_cfg_lbl.setStyleSheet("padding: 6px 10px; border-radius: 6px; font-weight: 600;")
        self.client_cfg_lbl.hide()
        lay.addWidget(self.client_cfg_lbl)

        self.tbl = QTableWidget(len(self.tools), 4, self)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setHorizontalHeaderLabels(
            [
                tr(self.lang, "diag_col_tool"),
                tr(self.lang, "diag_col_status"),
                tr(self.lang, "diag_col_latency"),
                tr(self.lang, "diag_col_detail"),
            ]
        )
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tbl.itemSelectionChanged.connect(self._on_row_selected)
        lay.addWidget(self.tbl, stretch=1)

        self.detail_box = QPlainTextEdit()
        self.detail_box.setReadOnly(True)
        self.detail_box.setFixedHeight(95)
        self.detail_box.setPlaceholderText(tr(self.lang, "diag_raw_ph"))
        lay.addWidget(self.detail_box)

        # Stuck port release bar
        port_card = QFrame()
        port_card.setObjectName("card")
        pl = QHBoxLayout(port_card)
        pl.setContentsMargins(10, 7, 10, 7)
        pl.setSpacing(6)
        pl.addWidget(QLabel(tr(self.lang, "diag_ports_hdr")))
        for port_num, name in ((8080, "Unity"), (9876, "Blender"), (9121, "Serena"), (8790, "TRELLIS")):
            pb = QPushButton(tr(self.lang, "diag_port_btn", port=port_num, name=name))
            pb.clicked.connect(lambda _=False, p=port_num: self.main_win._handle_kill_zombie_port(p, parent_widget=self))
            pl.addWidget(pb)
        pl.addStretch()
        lay.addWidget(port_card)

        bot = QHBoxLayout()
        self.summary_lbl = QLabel(tr(self.lang, "status_ready"))
        self.summary_lbl.setStyleSheet("font-weight: 600;")
        bot.addWidget(self.summary_lbl, stretch=1)

        btn_close = QPushButton(tr(self.lang, "btn_close"))
        btn_close.clicked.connect(self.accept)
        bot.addWidget(btn_close)
        lay.addLayout(bot)

        self._raw_details: list[str] = [""] * len(self.tools)
        self._ok_count = 0
        self._fail_count = 0
        self.start_tests(force_dry_run=False)

    def _selected_client_code(self) -> str:
        return str(self.client_cmb.currentData() or "ALL")

    def _handle_start_and_retest(self) -> None:
        if self.main_win._runtime_state == "stopped":
            self.main_win.start_all_tools()
            self.btn_start_now.setEnabled(False)
            self.summary_lbl.setText(tr(self.lang, "msg_tools_starting"))

            def _poll_ready() -> None:
                if not self.isVisible():
                    return
                if self.main_win._runtime_state == "running":
                    self.btn_start_now.setEnabled(True)
                    self.start_tests(force_dry_run=False)
                elif self.main_win._runtime_state == "starting":
                    QTimer.singleShot(350, _poll_ready)
                else:
                    self.btn_start_now.setEnabled(True)

            QTimer.singleShot(350, _poll_ready)
        elif self.main_win._runtime_state == "running":
            self.start_tests(force_dry_run=False)

    def start_tests(self, force_dry_run: bool = False, interrupt_running: bool = False) -> None:
        if self._running and not interrupt_running:
            return
        self._run_gen += 1
        cur_gen = self._run_gen
        self.tools = [copy.deepcopy(t) for t in self.main_win.tools if getattr(t, "in_workspace", True) and t.enabled]
        self.tbl.setRowCount(len(self.tools))
        self._running = True
        self._ok_count = 0
        self._fail_count = 0
        self.btn_retest.setEnabled(False)
        self._raw_details = [""] * len(self.tools)

        is_rt_running = self.main_win._runtime_state == "running"
        target_client = self._selected_client_code()
        self.btn_retest.setText(tr(self.lang, "diag_btn_retest" if is_rt_running else "diag_btn_dryrun"))

        if not self.tools:
            self.btn_start_now.hide()
            self.client_cfg_lbl.hide()
            self.summary_lbl.setText(tr(self.lang, "diag_no_enabled"))
            self._running = False
            self.btn_retest.setEnabled(True)
            return

        if not is_rt_running and not force_dry_run:
            self.btn_start_now.show()
            self.btn_start_now.setEnabled(self.main_win._runtime_state == "stopped")
            self.client_cfg_lbl.hide()
            stopped_lbl = tr(self.lang, "st_stopped_standby")
            stopped_det = tr(self.lang, "diag_stopped_row")
            for r, t in enumerate(self.tools):
                self.tbl.setItem(r, 0, QTableWidgetItem(t.name))
                st_item = QTableWidgetItem(stopped_lbl)
                st_item.setForeground(QColor("#f59e0b"))
                self.tbl.setItem(r, 1, st_item)
                self.tbl.setItem(r, 2, QTableWidgetItem("—"))
                self.tbl.setItem(r, 3, QTableWidgetItem(stopped_det))
                self._raw_details[r] = tr(self.lang, "diag_stopped_banner")
            self.summary_lbl.setText(tr(self.lang, "diag_stopped_banner"))
            self._running = False
            self.btn_retest.setEnabled(True)
            return

        if is_rt_running:
            self.btn_start_now.hide()
        else:
            self.btn_start_now.show()
            self.btn_start_now.setEnabled(self.main_win._runtime_state == "stopped")

        if target_client == "ALL":
            self.client_cfg_lbl.hide()

        self.summary_lbl.setText(tr(self.lang, "diag_running", n=len(self.tools)))
        for r, t in enumerate(self.tools):
            self.tbl.setItem(r, 0, QTableWidgetItem(t.name))
            self.tbl.setItem(r, 1, QTableWidgetItem(tr(self.lang, "diag_waiting")))
            self.tbl.setItem(r, 2, QTableWidgetItem("—"))
            self.tbl.setItem(r, 3, QTableWidgetItem(tr(self.lang, "diag_trying")))

        snap = list(self.tools)
        proj = dict(self.main_win.projects_map)
        sk = len(self.main_win.active_skills)
        lang = self.lang
        rt_active = bool(is_rt_running)
        client_snap = target_client

        def worker() -> None:
            from ...diagnostics import measure_tool_schema_tokens
            from ...tokens import schema_cache_key

            if client_snap != "ALL":
                parse_ok, cfg_msg, _act, _dis, _cpath = inspect_client_config_file(
                    client_snap, projects_map=proj, lang=lang
                )
                banner_txt = f"[{client_snap}] {cfg_msg}"
                if parse_ok and rt_active:
                    banner_txt = f"{banner_txt}  —  {tr(lang, 'diag_client_reload_hint')}"
                safe_emit(self._bridge.conn_test_cfg, cur_gen, parse_ok, banner_txt)

            measured: dict[str, int] = {}
            for idx, t in enumerate(snap):
                if cur_gen != self._run_gen:
                    return
                ok, ms, msg, raw, badge = test_tool_for_client_e2e(
                    t,
                    client_snap,
                    self.main_win.vault,
                    proj,
                    sk,
                    runtime_active=rt_active,
                    lang=lang,
                )
                if cur_gen != self._run_gen:
                    return
                safe_emit(self._bridge.conn_test_row, cur_gen, idx, ok, ms, msg, raw, badge)
                if ok and rt_active and client_snap == "ALL" and t.id in ("serena", "unity_mcp"):
                    tok_val = measure_tool_schema_tokens(t, self.main_win.vault)
                    if isinstance(tok_val, int) and tok_val > 0:
                        measured[schema_cache_key(t)] = tok_val
            if measured and cur_gen == self._run_gen:
                safe_emit(self.main_win.bridge.schema_measure_done, measured, len(measured))
            safe_emit(self._bridge.conn_test_done, cur_gen, not rt_active)

        threading.Thread(target=worker, daemon=True).start()

    def _on_client_cfg_status(self, gen: int, parse_ok: bool, msg: str) -> None:
        if gen != self._run_gen:
            return
        self.client_cfg_lbl.setText(msg)
        if parse_ok:
            self.client_cfg_lbl.setStyleSheet(
                "padding: 6px 10px; border-radius: 6px; font-weight: 600; "
                "background: rgba(16, 185, 129, 0.14); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35);"
            )
        else:
            self.client_cfg_lbl.setStyleSheet(
                "padding: 6px 10px; border-radius: 6px; font-weight: 600; "
                "background: rgba(239, 68, 68, 0.14); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4);"
            )
            self.main_win.logs.add("ERR", self._selected_client_code(), msg, msg)
            self.main_win._refresh_logs_tab()
        self.client_cfg_lbl.show()

    def _on_row_result(self, gen: int, row: int, ok: bool, ms: int, msg: str, raw: str, badge_state: str) -> None:
        if gen != self._run_gen or row < 0 or row >= len(self.tools):
            return
        self._raw_details[row] = raw
        if ok:
            self._ok_count += 1
        else:
            self._fail_count += 1
            t_obj = self.tools[row]
            self.main_win.logs.add(
                "WARN",
                t_obj.name,
                tr(self.lang, "log_diag_fail", msg=msg),
                raw or msg,
                t_obj.port,
            )
            self.main_win._refresh_logs_tab()

        badge_map = {
            "pass": (tr(self.lang, "diag_pass"), "#22c55e"),
            "ready_stopped": (tr(self.lang, "diag_st_ready_stopped"), "#38bdf8"),
            "stopped": (tr(self.lang, "st_stopped_standby"), "#f59e0b"),
            "off_client": (tr(self.lang, "diag_st_off_client"), "#94a3b8"),
            "fail": (tr(self.lang, "diag_fail"), "#ef4444"),
        }
        st_lbl, st_col = badge_map.get(badge_state, (tr(self.lang, "diag_pass" if ok else "diag_fail"), "#22c55e" if ok else "#ef4444"))
        st_item = QTableWidgetItem(st_lbl)
        st_item.setForeground(QColor(st_col))
        self.tbl.setItem(row, 1, st_item)
        self.tbl.setItem(row, 2, QTableWidgetItem(f"{ms}ms" if ms >= 0 else "—"))
        self.tbl.setItem(row, 3, QTableWidgetItem(msg))

    def _on_all_done(self, gen: int, was_dry_run: bool) -> None:
        if gen != self._run_gen:
            return
        self._running = False
        self.btn_retest.setEnabled(True)
        key = "diag_done_stopped" if was_dry_run else "diag_done"
        self.summary_lbl.setText(
            tr(self.lang, key, ok=self._ok_count, fail=self._fail_count, tot=len(self.tools))
        )

    def _on_row_selected(self) -> None:
        idxs = self.tbl.selectionModel().selectedRows()
        if not idxs:
            return
        r = idxs[0].row()
        if 0 <= r < len(self._raw_details):
            self.detail_box.setPlainText(self._raw_details[r])
