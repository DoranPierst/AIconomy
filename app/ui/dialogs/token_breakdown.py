"""Interactive Token Usage Breakdown dialog: per-client 200K load, per-tool % shares, saver vs capability roles."""
from __future__ import annotations

import copy
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...catalog import ToolSpec
from ...diagnostics import measure_tool_schema_tokens
from ...i18n import tr
from ...tokens import SAVER_NOTE_KEYS, compute_token_breakdown, fmt_tokens, schema_cache_key
from ..widgets import ToggleSwitch
from ..workers import safe_emit

if TYPE_CHECKING:
    from ..main_window import MainWindow


class TokenBreakdownDialog(QDialog):
    """Display per-client context usage, per-tool % share bars, and instant tool toggles."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.main_win = parent
        self.lang = parent.lang
        self.setWindowTitle(tr(self.lang, "tok_dlg_title"))
        self.setMinimumSize(760, 520)
        self.resize(840, 650)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 12)

        self.clients_hdr_lbl = QLabel(f"<b>{tr(self.lang, 'tok_clients_hdr')}</b>")
        root.addWidget(self.clients_hdr_lbl)

        self.clients_host = QWidget()
        self.clients_lay = QHBoxLayout(self.clients_host)
        self.clients_lay.setContentsMargins(0, 0, 0, 0)
        self.clients_lay.setSpacing(8)
        root.addWidget(self.clients_host)

        legend_card = QFrame()
        legend_card.setObjectName("bannerInfo")
        leg_lay = QVBoxLayout(legend_card)
        leg_lay.setContentsMargins(12, 8, 12, 8)
        self.legend_lbl = QLabel(tr(self.lang, "tok_legend_banner"))
        self.legend_lbl.setWordWrap(True)
        self.legend_lbl.setStyleSheet("font-size: 11px;")
        leg_lay.addWidget(self.legend_lbl)
        root.addWidget(legend_card)

        self.shares_hdr_lbl = QLabel()
        root.addWidget(self.shares_hdr_lbl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setObjectName("cellBox")
        self.rows_host = QWidget()
        self.rows_host.setObjectName("cellBox")
        self.rows_lay = QVBoxLayout(self.rows_host)
        self.rows_lay.setContentsMargins(0, 0, 4, 0)
        self.rows_lay.setSpacing(6)
        self.scroll.setWidget(self.rows_host)
        root.addWidget(self.scroll, stretch=1)

        bot = QHBoxLayout()
        self.footer_totals_lbl = QLabel()
        bot.addWidget(self.footer_totals_lbl)
        bot.addStretch()

        self.btn_measure = QPushButton(tr(self.lang, "tok_btn_measure"))
        self.btn_measure.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_measure.clicked.connect(self._run_live_schema_measurement)
        bot.addWidget(self.btn_measure)

        btn_close = QPushButton(tr(self.lang, "btn_close"))
        btn_close.setObjectName("primaryBtn")
        btn_close.clicked.connect(self.accept)
        bot.addWidget(btn_close)
        root.addLayout(bot)

        self._measuring = False
        self._bridge_conns = [
            self.main_win.bridge.schema_measure_done.connect(self._on_measure_done),
        ]
        self._rebuild_view()

    def _disconnect_bridge_signals(self) -> None:
        conns = getattr(self, "_bridge_conns", None)
        if not conns:
            return
        self._bridge_conns = []
        for conn in conns:
            try:
                QObject.disconnect(conn)
            except (RuntimeError, TypeError):
                pass

    def done(self, result: int) -> None:
        self._disconnect_bridge_signals()
        super().done(result)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._disconnect_bridge_signals()
        super().closeEvent(event)

    @staticmethod
    def _clear_layout(lay: QHBoxLayout | QVBoxLayout) -> None:
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild_view(self) -> None:
        is_light = self.main_win.meta.get("theme", "dark") == "light"
        tok_cache = self.main_win.meta.get("schema_token_cache")
        bd = compute_token_breakdown(
            self.main_win.tools,
            len(self.main_win.active_skills),
            self.main_win.projects_map,
            missing_required_keys=self.main_win._missing_required_vault_keys(),
            installed_clients=self.main_win.installed_clients,
            schema_token_cache=tok_cache if isinstance(tok_cache, dict) else None,
        )

        # 1. Rebuild 4 AI client cards
        self._clear_layout(self.clients_lay)
        muted_col = "#64748b" if is_light else "#94a3b8"
        for cl in bd.clients:
            card = QFrame()
            card.setObjectName("card")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(11, 9, 11, 9)
            c_lay.setSpacing(5)

            top_r = QHBoxLayout()
            short_nm = cl.full_name.replace("Google ", "").replace("OpenAI ", "")
            hdr_txt = f"<b>{cl.code}</b> <span style='color:{muted_col}; font-size:11px;'>{short_nm}</span>"
            top_r.addWidget(QLabel(hdr_txt))
            top_r.addStretch()
            if not cl.is_installed:
                nd_lbl = QLabel(tr(self.lang, "client_not_detected"))
                nd_lbl.setStyleSheet("color: #64748b; font-size: 9px;")
                top_r.addWidget(nd_lbl)
            c_lay.addLayout(top_r)

            val_r = QHBoxLayout()
            tok_lbl = QLabel(fmt_tokens(cl.tokens))
            tok_lbl.setStyleSheet("font-family: Consolas, 'Segoe UI', monospace; font-size: 13px; font-weight: 700;")
            val_r.addWidget(tok_lbl)
            val_r.addStretch()
            pct_str = f"{cl.context_percent:.1f}"
            pct_lbl = QLabel(tr(self.lang, "tok_client_pct", pct=pct_str))
            pct_lbl.setStyleSheet(f"color: {muted_col}; font-size: 10px; font-weight: 600;")
            val_r.addWidget(pct_lbl)
            c_lay.addLayout(val_r)

            bar = QProgressBar()
            bar.setObjectName("slimBar")
            bar.setRange(0, bd.context_window)
            bar.setValue(min(cl.tokens, bd.context_window))
            bar.setTextVisible(False)
            if cl.context_percent >= 25.0:
                chunk_col = "#ef4444"
            elif cl.context_percent >= 12.0:
                chunk_col = "#f59e0b"
            elif cl.tokens > 0:
                chunk_col = "#10b981"
            else:
                chunk_col = "#334155"
            bar.setStyleSheet(f"QProgressBar#slimBar::chunk {{ background-color: {chunk_col}; border-radius: 3px; }}")
            c_lay.addWidget(bar)

            cnt_lbl = QLabel(tr(self.lang, "tok_client_tools", n=cl.tool_count))
            cnt_lbl.setStyleSheet(f"color: {muted_col}; font-size: 10px;")
            c_lay.addWidget(cnt_lbl)
            self.clients_lay.addWidget(card, stretch=1)

        # 2. Rebuild per-tool share rows
        self.shares_hdr_lbl.setText(
            f"<b>{tr(self.lang, 'tok_shares_hdr', tot=fmt_tokens(bd.active_tokens))}</b>"
        )
        self._clear_layout(self.rows_lay)

        saver_pill_qss = (
            "background-color: #dcfce7; color: #166534; border: 1px solid #86efac; "
            "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 700;"
            if is_light
            else "background-color: #06392c; color: #6ee7b7; border: 1px solid #059669; "
            "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 700;"
        )
        cap_pill_qss = (
            "background-color: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; "
            "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
            if is_light
            else "background-color: #152542; color: #93c5fd; border: 1px solid #2563eb; "
            "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )

        if not bd.tool_shares:
            empty_card = QFrame()
            empty_card.setObjectName("card")
            e_lay = QVBoxLayout(empty_card)
            e_lay.setContentsMargins(16, 20, 16, 20)
            e_lbl = QLabel(tr(self.lang, "tok_empty_active"))
            e_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e_lbl.setStyleSheet(f"color: {muted_col};")
            e_lay.addWidget(e_lbl)
            self.rows_lay.addWidget(empty_card)
        else:
            for share in bd.tool_shares:
                t = share.tool
                row_card = QFrame()
                row_card.setObjectName("card")
                r_lay = QHBoxLayout(row_card)
                r_lay.setContentsMargins(12, 8, 12, 8)
                r_lay.setSpacing(12)

                info_col = QVBoxLayout()
                info_col.setSpacing(3)
                title_r = QHBoxLayout()
                title_r.setSpacing(7)
                nm_lbl = QLabel(f"<b>{t.name}</b>")
                title_r.addWidget(nm_lbl)

                role_lbl = QLabel(
                    tr(self.lang, "tok_role_saver" if share.is_token_saver else "tok_role_capability")
                )
                role_lbl.setStyleSheet(saver_pill_qss if share.is_token_saver else cap_pill_qss)
                title_r.addWidget(role_lbl)

                if t.id not in ("blender_skills", "caveman"):
                    src_lbl = QLabel(
                        tr(self.lang, "tok_badge_measured" if share.is_measured else "tok_badge_estimated")
                    )
                    if share.is_measured:
                        src_qss = (
                            "background-color: #ecfdf5; color: #047857; border: 1px solid #6ee7b7; "
                            "border-radius: 4px; padding: 1px 5px; font-size: 9.5px; font-weight: 700;"
                            if is_light
                            else "background-color: #0b2e23; color: #34d399; border: 1px solid #059669; "
                            "border-radius: 4px; padding: 1px 5px; font-size: 9.5px; font-weight: 700;"
                        )
                    else:
                        src_qss = (
                            "background-color: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; "
                            "border-radius: 4px; padding: 1px 5px; font-size: 9.5px; font-weight: 600;"
                            if is_light
                            else "background-color: #162030; color: #94a3b8; border: 1px solid #263549; "
                            "border-radius: 4px; padding: 1px 5px; font-size: 9.5px; font-weight: 600;"
                        )
                    src_lbl.setStyleSheet(src_qss)
                    title_r.addWidget(src_lbl)

                title_r.addStretch()
                info_col.addLayout(title_r)

                clients_txt = " · ".join(share.active_clients) if share.active_clients else tr(self.lang, "none")
                sub_parts = [f"<span style='color:{muted_col};'>{clients_txt}</span>"]
                saver_key = SAVER_NOTE_KEYS.get(t.id)
                if saver_key:
                    note_col = "#059669" if is_light else "#34d399"
                    sub_parts.append(f"<span style='color:{note_col};'>{tr(self.lang, saver_key)}</span>")
                sub_lbl = QLabel("  —  ".join(sub_parts))
                sub_lbl.setWordWrap(True)
                sub_lbl.setStyleSheet("font-size: 10px;")
                info_col.addWidget(sub_lbl)

                info_wrap = QWidget()
                info_wrap.setObjectName("cellBox")
                info_wrap.setFixedWidth(350)
                info_wrap.setLayout(info_col)
                r_lay.addWidget(info_wrap)

                # Middle % share bar
                mid_col = QVBoxLayout()
                mid_col.setSpacing(4)
                if share.zero_reason_key:
                    z_lbl = QLabel(tr(self.lang, share.zero_reason_key))
                    z_lbl.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: 600;")
                    mid_col.addWidget(z_lbl)
                else:
                    pct_int = int(round(share.share_percent))
                    val_line = QHBoxLayout()
                    val_line.addStretch()
                    v_lbl = QLabel(
                        tr(self.lang, "tok_share_val", tok=fmt_tokens(share.effective_tokens), pct=pct_int)
                    )
                    v_lbl.setStyleSheet("font-family: Consolas, 'Segoe UI', monospace; font-size: 11px; font-weight: 700;")
                    val_line.addWidget(v_lbl)
                    mid_col.addLayout(val_line)

                    s_bar = QProgressBar()
                    s_bar.setObjectName("slimBar")
                    s_bar.setRange(0, 1000)
                    s_bar.setValue(max(16, int(round(share.share_percent * 10))))
                    s_bar.setTextVisible(False)
                    bar_col = "#10b981" if share.is_token_saver else "#3b82f6"
                    s_bar.setStyleSheet(
                        f"QProgressBar#slimBar::chunk {{ background-color: {bar_col}; border-radius: 3px; }}"
                    )
                    mid_col.addWidget(s_bar)
                r_lay.addLayout(mid_col, stretch=1)

                # Right quick actions
                act_lay = QHBoxLayout()
                act_lay.setSpacing(8)
                if t.id == "blender_skills":
                    trim_btn = QPushButton(
                        tr(self.lang, "tok_skills_trim_btn", on=len(self.main_win.active_skills))
                    )
                    trim_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    trim_btn.clicked.connect(lambda _=False, tool_obj=t: self._edit_skills(tool_obj))
                    act_lay.addWidget(trim_btn)

                sw = ToggleSwitch(checked=t.enabled, is_light=is_light)
                sw.setToolTip(tr(self.lang, "row_toggle_tip", name=t.name))
                sw.clicked.connect(lambda _=False, tool_obj=t: self._toggle_tool(tool_obj))
                act_lay.addWidget(sw)
                r_lay.addLayout(act_lay)

                self.rows_lay.addWidget(row_card)

        self.rows_lay.addStretch(1)

        tot_col = "#047857" if is_light else "#10b981"
        self.footer_totals_lbl.setStyleSheet(
            f"font-family: Consolas, 'Segoe UI', monospace; font-weight: 700; color: {tot_col};"
        )
        self.footer_totals_lbl.setText(
            tr(
                self.lang,
                "tok_footer_totals",
                act=fmt_tokens(bd.active_tokens),
                sav=fmt_tokens(bd.saved_tokens),
            )
        )

    def _toggle_tool(self, tool: ToolSpec) -> None:
        self.main_win._toggle_tool(tool, prompt_missing_key=False)
        self._rebuild_view()

    def _edit_skills(self, tool: ToolSpec) -> None:
        self.main_win.open_gear(tool)
        self._rebuild_view()

    def _run_live_schema_measurement(self) -> None:
        if self._measuring or not getattr(self.main_win, "sync_live_environment", True):
            return
        targets = [
            copy.deepcopy(t)
            for t in self.main_win.workspace_tools()
            if t.enabled and t.id not in ("blender_skills", "caveman", "unity_pipeline", "trellis")
        ]
        if not targets:
            self.main_win.set_status(tr(self.lang, "msg_tok_measure_none"))
            return
        self._measuring = True
        self.btn_measure.setEnabled(False)
        self.btn_measure.setText(tr(self.lang, "tok_btn_measuring"))
        vault = self.main_win.vault

        def worker() -> None:
            measured: dict[str, int] = {}
            for t_snap in targets:
                tok_val = measure_tool_schema_tokens(t_snap, vault)
                if isinstance(tok_val, int) and tok_val > 0:
                    measured[schema_cache_key(t_snap)] = tok_val
            safe_emit(self.main_win.bridge.schema_measure_done, measured, len(measured))

        threading.Thread(target=worker, daemon=True).start()

    def _on_measure_done(self, measured: dict[str, int], count: int) -> None:
        self._measuring = False
        if isinstance(measured, dict) and measured:
            cache = self.main_win.meta.setdefault("schema_token_cache", {})
            if isinstance(cache, dict):
                cache.update(measured)
            self.main_win._save_state()
            self.main_win._refresh_table()
            self.main_win.set_status(tr(self.lang, "msg_tok_measured", n=count))
        else:
            self.main_win.set_status(tr(self.lang, "msg_tok_measure_none"))
        if self.isVisible():
            self.btn_measure.setEnabled(True)
            self.btn_measure.setText(tr(self.lang, "tok_btn_measure"))
            self._rebuild_view()
