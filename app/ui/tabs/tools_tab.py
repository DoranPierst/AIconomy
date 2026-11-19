"""Tools tab mixin (5-column minimalist matrix, ToggleSwitch, clickable mode/skill/update pills, zero emojis)."""
from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ...catalog import (
    AI_CLIENTS,
    BLENDER_SKILLS_94,
    PROFILES,
    TOOL_KINDS,
    ToolSpec,
    localized_tool_modes,
    localized_tool_text,
    normalize_tool_kind,
    profile_title,
    tool_kind_label,
)
from ...i18n import tr
from ...processes import probe_tool_health, scan_live_process_locations
from ...tokens import compute_token_breakdown, fmt_tokens
from ..dialogs.tool_info import ToolInfoDialog
from ..icons import icon_color, make_icon
from ..widgets import AiMatrixHeaderView, HoverTableWidget, StatusBadgeWidget, ToggleSwitch


class ToolsTabMixin:
    """Mixin implementing Tab 0 (Tools)."""

    def _init_panel_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # Clean single-line filter bar
        flt = QHBoxLayout()
        flt.setSpacing(8)
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText(tr(self.lang, "search_ph"))
        self.search_inp.setMinimumWidth(260)
        self.search_inp.textChanged.connect(self._refresh_table)
        flt.addWidget(self.search_inp, stretch=1)

        self.kind_cmb = QComboBox()
        self.kind_cmb.setMinimumWidth(120)
        self.kind_cmb.currentIndexChanged.connect(self._refresh_table)
        flt.addWidget(self.kind_cmb)

        self.proj_filter_cmb = QComboBox()
        self.proj_filter_cmb.setMinimumWidth(145)
        self.proj_filter_cmb.currentIndexChanged.connect(self._refresh_table)
        flt.addWidget(self.proj_filter_cmb)
        lay.addLayout(flt)

        # First-run quick-start banner (shown once on fresh installs until dismissed or profile picked)
        self.first_run_banner = QFrame()
        self.first_run_banner.setObjectName("bannerInfo")
        fr_lay = QHBoxLayout(self.first_run_banner)
        fr_lay.setContentsMargins(12, 8, 12, 8)
        fr_lay.setSpacing(8)
        self.first_run_lbl = QLabel(tr(self.lang, "banner_first_run"))
        self.first_run_lbl.setWordWrap(True)
        fr_lay.addWidget(self.first_run_lbl, stretch=1)
        self.first_run_btns_lay = QHBoxLayout()
        self.first_run_btns_lay.setSpacing(6)
        fr_lay.addLayout(self.first_run_btns_lay)
        self.btn_first_run_dismiss = QPushButton(tr(self.lang, "banner_dismiss"))
        self.btn_first_run_dismiss.setObjectName("ghostBtn")
        self.btn_first_run_dismiss.clicked.connect(self._dismiss_first_run)
        fr_lay.addWidget(self.btn_first_run_dismiss)
        self.first_run_banner.hide()
        lay.addWidget(self.first_run_banner)

        # Host-app dependency banner (shown only when an enabled tool needs a closed host app)
        self.host_dep_banner = QFrame()
        self.host_dep_banner.setObjectName("bannerWarn")
        hdb_lay = QHBoxLayout(self.host_dep_banner)
        hdb_lay.setContentsMargins(12, 7, 12, 7)
        hdb_lay.setSpacing(8)
        self.host_dep_lbl = QLabel("")
        self.host_dep_lbl.setStyleSheet("font-weight: 600;")
        self.host_dep_lbl.setWordWrap(True)
        hdb_lay.addWidget(self.host_dep_lbl, stretch=1)
        self.host_dep_btns_lay = QHBoxLayout()
        self.host_dep_btns_lay.setSpacing(6)
        hdb_lay.addLayout(self.host_dep_btns_lay)
        self.host_dep_banner.hide()
        lay.addWidget(self.host_dep_banner)

        # 5-column minimalist Tools table (Tool | Scope | Status | AI Clients | Enabled)
        self.table = HoverTableWidget(0, 5, self)
        self.ai_header = AiMatrixHeaderView(self.table, self)
        self.bulk_client_btns: dict[str, QPushButton] = self.ai_header.buttons
        self.table.setHorizontalHeader(self.ai_header)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)

        hdr = self.ai_header
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(3, AiMatrixHeaderView.AI_COL_WIDTH)
        self.table.setColumnWidth(3, AiMatrixHeaderView.AI_COL_WIDTH)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(4, 108)
        self.table.setColumnWidth(4, 108)
        hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr.sectionClicked.connect(self._on_header_clicked)
        self.table.horizontalScrollBar().valueChanged.connect(lambda *_: hdr.sync_ai_bar_geometry())
        lay.addWidget(self.table, stretch=1)

        self._displayed_tools: list[ToolSpec] = []
        self._rebuild_kind_filter_combo()
        self._refresh_first_run_banner()
        self.tabs.addTab(tab, tr(self.lang, "tab_tools", n=len(self.tools)))

    def _rebuild_kind_filter_combo(self) -> None:
        cur_data = self.kind_cmb.currentData() if self.kind_cmb.count() else "ALL"
        self.kind_cmb.blockSignals(True)
        self.kind_cmb.clear()
        self.kind_cmb.addItem(tr(self.lang, "kind_all"), "ALL")
        for kind_code in TOOL_KINDS:
            self.kind_cmb.addItem(tool_kind_label(kind_code, self.lang), kind_code)
        idx = self.kind_cmb.findData(cur_data)
        self.kind_cmb.setCurrentIndex(max(0, idx))
        self.kind_cmb.blockSignals(False)

    def _rebuild_project_filter_combo(self) -> None:
        cur_data = self.proj_filter_cmb.currentData() if self.proj_filter_cmb.count() else "ALL"
        self.proj_filter_cmb.blockSignals(True)
        self.proj_filter_cmb.clear()
        self.proj_filter_cmb.addItem(tr(self.lang, "scope_all"), "ALL")
        self.proj_filter_cmb.addItem(tr(self.lang, "scope_global"), "GLOBAL")
        for p_name in sorted(self.projects_map.keys()):
            self.proj_filter_cmb.addItem(p_name, p_name)
        idx = self.proj_filter_cmb.findData(cur_data)
        self.proj_filter_cmb.setCurrentIndex(max(0, idx))
        self.proj_filter_cmb.blockSignals(False)

    def _refresh_first_run_banner(self) -> None:
        if not hasattr(self, "first_run_banner"):
            return
        if self.meta.get("first_run_dismissed", True):
            self.first_run_banner.hide()
            return
        self.first_run_lbl.setText(tr(self.lang, "banner_first_run"))
        self.btn_first_run_dismiss.setText(tr(self.lang, "banner_dismiss"))
        while self.first_run_btns_lay.count():
            item = self.first_run_btns_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for p_key in PROFILES:
            btn = QPushButton(profile_title(p_key, self.lang).replace("&", "&&"))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=p_key: self._apply_first_run_profile(k))
            self.first_run_btns_lay.addWidget(btn)
        self.first_run_banner.show()

    def _apply_first_run_profile(self, profile_key: str) -> None:
        self.meta["first_run_dismissed"] = True
        self.first_run_banner.hide()
        self.apply_builtin_profile(profile_key, ask_confirm=False)

    def _dismiss_first_run(self) -> None:
        self.meta["first_run_dismissed"] = True
        self.first_run_banner.hide()
        self._save_state()

    def _prompt_add_project_folder(self, assign_tool: ToolSpec | None) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr(self.lang, "set_proj_pick"))
        if not folder:
            if assign_tool is not None:
                self._refresh_table()
            return
        p_path = pathlib.Path(folder)
        proj_key = p_path.name
        self.projects_map[proj_key] = str(p_path)
        if assign_tool is not None and assign_tool.scope_selectable:
            assign_tool.project_scope = proj_key
        self._save_state()
        self._rebuild_project_filter_combo()
        self.run_health_scan()
        self.set_status(tr(self.lang, "msg_proj_added", name=proj_key))

    def _on_header_clicked(self, col: int) -> None:
        key_map = {0: "name", 1: "project", 2: "ping", 4: "enabled"}
        if col not in key_map:
            return
        k = key_map[col]
        if self.sort_key == k:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = k
            self.sort_desc = col in (2, 4)
        self._save_state()
        self._refresh_table()

    def _update_panel_header_indicators(self) -> None:
        base_labels = [
            tr(self.lang, "col_tool"),
            tr(self.lang, "col_scope"),
            tr(self.lang, "col_status"),
            "",
            tr(self.lang, "col_state"),
        ]
        key_to_col = {
            "name": 0,
            "project": 1,
            "ping": 2,
            "enabled": 4,
        }
        active_col = key_to_col.get(self.sort_key, -1)
        arrow = " ↓" if self.sort_desc else " ↑"
        labels = [
            f"{lbl}{arrow}" if (idx == active_col and lbl) else lbl
            for idx, lbl in enumerate(base_labels)
        ]
        self.table.setHorizontalHeaderLabels(labels)

    def _tool_sort_value(self, item: ToolSpec) -> Any:
        if self.sort_key == "name":
            return item.name.lower()
        if self.sort_key == "project":
            vis = self._format_scope_short(item).lower()
            return (vis, item.name.lower())
        if self.sort_key == "ping":
            rank = {"ok": 4, "idle": 3, "warn": 2, "error": 1, "off": 0}.get(item.health_state, 0)
            return (rank, -item.last_latency_ms if item.last_latency_ms >= 0 else -9999, item.name.lower())
        return (1 if item.enabled else 0, item.name.lower())

    def _calculate_token_economy(self) -> tuple[int, int]:
        bd = compute_token_breakdown(
            self.tools,
            len(self.active_skills),
            self.projects_map,
            missing_required_keys=self._missing_required_vault_keys(),
            installed_clients=self.installed_clients,
        )
        return bd.active_tokens, bd.saved_tokens

    def _format_scope_short(self, t: ToolSpec) -> str:
        if not t.scope_selectable:
            lbl = t.fixed_location_label
            if lbl and lbl.startswith("fixed_"):
                return tr(self.lang, lbl)
            return lbl or tr(self.lang, "fixed_system")
        if t.project_scope == "GLOBAL":
            return tr(self.lang, "scope_global")
        return t.project_scope

    def _refresh_table(self) -> None:
        q = self.search_inp.text().strip().lower()
        kf = str(self.kind_cmb.currentData() or "ALL")
        pf = self.proj_filter_cmb.currentData() or "ALL"
        is_light = self.meta.get("theme", "dark") == "light"

        vis_codes = self.get_visible_client_codes()
        ai_col_w = self.ai_header.refresh_visible_clients(vis_codes)
        self.ai_header.resizeSection(3, ai_col_w)
        self.table.setColumnWidth(3, ai_col_w)

        rows: list[ToolSpec] = []
        for t in self.tools:
            t_kind = normalize_tool_kind(t.kind)
            t_summary = localized_tool_text(t, "summary", self.lang)
            if q and (
                q not in t.name.lower()
                and q not in tool_kind_label(t_kind, self.lang).lower()
                and q not in t_summary.lower()
                and q not in t.project_scope.lower()
                and q not in t.live_location_detail.lower()
            ):
                continue
            if kf != "ALL" and t_kind != kf:
                continue
            if pf == "GLOBAL" and (not t.scope_selectable or t.project_scope != "GLOBAL"):
                continue
            if pf not in ("ALL", "GLOBAL"):
                if t.scope_selectable and t.project_scope not in (pf, "GLOBAL"):
                    continue
            rows.append(t)

        self._update_panel_header_indicators()
        if self.sort_key == "enabled":
            rows.sort(
                key=lambda x: ((0 if x.enabled else 1) if self.sort_desc else (1 if x.enabled else 0), x.name.lower())
            )
        else:
            rows.sort(key=self._tool_sort_value, reverse=self.sort_desc)
        self._displayed_tools = rows

        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        gear_ico = make_icon("gear", icon_color(is_light, muted=True), 15)

        pill_style = (
            "background-color: #e2e8f0; color: #475569; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
            if is_light
            else "background-color: #1a2434; color: #94a3b8; border: 1px solid #263549; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )
        mode_btn_style = (
            "QPushButton { background-color: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; border-radius: 4px; padding: 1px 7px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background-color: #dbeafe; border-color: #60a5fa; }"
            if is_light
            else "QPushButton { background-color: #132036; color: #93c5fd; border: 1px solid #1e3a5f; border-radius: 4px; padding: 1px 7px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background-color: #1e3a5f; border-color: #3b82f6; }"
        )

        for r_idx, t in enumerate(rows):
            self.table.setRowHeight(r_idx, 42)
            t_summary = localized_tool_text(t, "summary", self.lang)
            tooltip_full = f"{t.name}\n{t_summary}".strip()
            if t.live_location_detail:
                tooltip_full = f"{tooltip_full}\n\n{t.live_location_detail}"

            # Col 0: Name + type pill + version + compact active skill/mode pill
            nm_w = QWidget()
            nm_w.setObjectName("cellBox")
            nm_w.setMinimumWidth(310)
            nm_l = QHBoxLayout(nm_w)
            nm_l.setContentsMargins(12, 6, 8, 6)
            nm_l.setSpacing(7)

            nm_lbl = QLabel(f"<b>{t.name}</b>")
            nm_lbl.setToolTip(tooltip_full)
            nm_l.addWidget(nm_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

            kind_pill = QLabel(tool_kind_label(t.kind, self.lang))
            kind_pill.setFixedHeight(20)
            kind_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            kind_pill.setStyleSheet(pill_style)
            nm_l.addWidget(kind_pill, alignment=Qt.AlignmentFlag.AlignVCenter)

            cur_v = t.version.strip().lstrip("vV")
            lat_v = (t.latest_version or t.version).strip().lstrip("vV")
            if t.has_update and lat_v != cur_v:
                upd_btn = QPushButton(f"v{cur_v} -> v{lat_v}")
                upd_btn.setObjectName("updatePillBtn")
                upd_btn.setFixedHeight(20)
                upd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                upd_btn.setToolTip(tr(self.lang, "row_update_tip", cur=cur_v, lat=lat_v))
                upd_btn.clicked.connect(
                    lambda _=False, tool_obj=t: self._run_batch_update([tool_obj], install_if_missing=True)
                )
                nm_l.addWidget(upd_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
            else:
                ver_lbl = QLabel(f"v{cur_v}")
                ver_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
                ver_lbl.setToolTip(tr(self.lang, "row_ver_tip", cur=cur_v))
                nm_l.addWidget(ver_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

            if t.id == "blender_skills":
                sk_btn = QPushButton(tr(self.lang, "skills_btn", on=len(self.active_skills), tot=len(BLENDER_SKILLS_94)))
                sk_btn.setFixedHeight(20)
                sk_btn.setStyleSheet(mode_btn_style)
                sk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                sk_btn.setToolTip(tr(self.lang, "row_gear_tip", name=t.name))
                sk_btn.clicked.connect(lambda _=False, tool_obj=t: self.open_gear(tool_obj))
                nm_l.addWidget(sk_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
            elif len(t.modes) > 1:
                modes_loc = localized_tool_modes(t, self.lang)
                cur_m = modes_loc[max(0, min(t.mode_index, len(modes_loc) - 1))]
                m_btn = QPushButton(cur_m)
                m_btn.setFixedHeight(20)
                m_btn.setStyleSheet(mode_btn_style)
                m_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                m_btn.setToolTip(tr(self.lang, "row_gear_tip", name=t.name))
                m_btn.clicked.connect(lambda _=False, tool_obj=t: self.open_gear(tool_obj))
                nm_l.addWidget(m_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

            nm_l.addStretch()
            self.table.setCellWidget(r_idx, 0, nm_w)

            # Col 1: Scope (clean combobox or muted fixed label)
            scope_tip = f"{self._format_scope_display(t)}\n{t.live_location_detail}".strip()
            proj_w = QWidget()
            proj_w.setObjectName("cellBox")
            proj_l = QHBoxLayout(proj_w)
            proj_l.setContentsMargins(6, 4, 6, 4)
            proj_l.setSpacing(0)

            if t.scope_selectable:
                p_cmb = QComboBox()
                p_cmb.setMinimumWidth(135)
                p_cmb.addItem(tr(self.lang, "scope_global"), "GLOBAL")
                for p_name in sorted(self.projects_map.keys()):
                    p_cmb.addItem(p_name, p_name)
                p_cmb.addItem(tr(self.lang, "scope_add_folder"), "__ADD_NEW__")
                cur_idx = p_cmb.findData(t.project_scope)
                p_cmb.setCurrentIndex(cur_idx if cur_idx >= 0 else 0)
                p_cmb.setToolTip(scope_tip)
                p_cmb.currentIndexChanged.connect(
                    lambda _idx, cmb=p_cmb, tool_obj=t: self._on_tool_scope_changed(tool_obj, str(cmb.currentData()))
                )
                proj_l.addWidget(p_cmb)
            else:
                fixed_lbl = QLabel(self._format_scope_short(t))
                fixed_lbl.setStyleSheet("color: #94a3b8; padding-left: 4px;")
                fixed_lbl.setToolTip(scope_tip)
                proj_l.addWidget(fixed_lbl)
            self.table.setCellWidget(r_idx, 1, proj_w)

            # Col 2: Status (anti-aliased colored dot + concise label)
            st_state = t.health_state if t.enabled else "off"
            st_text = t.last_ping if t.last_ping else tr(self.lang, "st_disabled")
            st_tip = f"{st_text}\n{t.live_location_detail}".strip()
            self.table.setCellWidget(r_idx, 2, StatusBadgeWidget(st_state, st_text, st_tip))

            # Col 3: AI Clients Matrix (visible clients; uninstalled clients dimmed)
            mat_w = QWidget()
            mat_w.setObjectName("cellBox")
            mat_l = QHBoxLayout(mat_w)
            mat_l.setContentsMargins(6, 4, 6, 4)
            mat_l.setSpacing(4)
            for code, full_lbl in AI_CLIENTS:
                if code not in vis_codes:
                    continue
                is_installed = code in self.installed_clients
                c_btn = QPushButton(code)
                c_btn.setCheckable(True)
                is_c_on = t.clients.get(code, False)
                c_btn.setChecked(is_c_on)
                c_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                tip_str = f"{full_lbl}: {tr(self.lang, 'client_on' if is_c_on else 'client_off')}"
                if not is_installed:
                    tip_str = f"{tip_str} ({tr(self.lang, 'client_not_detected')})"
                c_btn.setToolTip(tip_str)
                c_btn.setFixedSize(36, 24)
                if is_c_on:
                    c_btn.setStyleSheet(
                        "background-color: #2563eb; color: #ffffff; border: 1px solid #3b82f6; "
                        "border-radius: 5px; font-size: 10px; font-weight: 700; padding: 0px;"
                    )
                elif not is_installed:
                    c_btn.setStyleSheet(
                        "background-color: #f8fafc; color: #cbd5e1; border: 1px dashed #e2e8f0; "
                        "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                        if is_light
                        else "background-color: #090d13; color: #334155; border: 1px dashed #162030; "
                        "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                    )
                else:
                    c_btn.setStyleSheet(
                        "background-color: #f1f5f9; color: #94a3b8; border: 1px solid #e2e8f0; "
                        "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                        if is_light
                        else "background-color: #0c1117; color: #526175; border: 1px solid #1e293b; "
                        "border-radius: 5px; font-size: 10px; font-weight: 600; padding: 0px;"
                    )
                c_btn.clicked.connect(lambda checked, tool_obj=t, c=code: self._toggle_client(tool_obj, c, checked))
                mat_l.addWidget(c_btn)
            self.table.setCellWidget(r_idx, 3, mat_w)

            # Col 4: Configure gear icon + modern ToggleSwitch
            act_w = QWidget()
            act_w.setObjectName("cellBox")
            act_l = QHBoxLayout(act_w)
            act_l.setContentsMargins(4, 0, 10, 0)
            act_l.setSpacing(8)
            act_l.addStretch()
            if t.has_gear:
                g_btn = QPushButton()
                g_btn.setObjectName("iconBtn")
                g_btn.setIcon(gear_ico)
                g_btn.setFixedSize(26, 26)
                g_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                g_btn.setToolTip(tr(self.lang, "row_gear_tip", name=t.name))
                g_btn.clicked.connect(lambda _=False, tool_obj=t: self.open_gear(tool_obj))
                act_l.addWidget(g_btn)

            sw = ToggleSwitch(checked=t.enabled, is_light=is_light)
            sw.setToolTip(tr(self.lang, "row_toggle_tip", name=t.name))
            sw.clicked.connect(lambda _checked=False, tool_obj=t: self._toggle_tool(tool_obj))
            act_l.addWidget(sw)
            self.table.setCellWidget(r_idx, 4, act_w)

        active_tok, saved_tok = self._calculate_token_economy()
        self.token_summary_lbl.setText(
            tr(self.lang, "token_summary", act=fmt_tokens(active_tok), sav=fmt_tokens(saved_tok))
        )
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(2)
        if self.table.columnWidth(1) < 150:
            self.table.setColumnWidth(1, 150)
        if self.table.columnWidth(2) < 155:
            self.table.setColumnWidth(2, 155)
        self._update_bulk_client_buttons()
        self.ai_header.sync_ai_bar_geometry()
        self.table._refresh_hover_from_cursor()

    def _on_table_double_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._displayed_tools):
            ToolInfoDialog(self, self._displayed_tools[row]).exec()

    def _on_table_context_menu(self, pos: Any) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._displayed_tools):
            return
        t = self._displayed_tools[row]
        menu = QMenu(self)

        act_details = QAction(tr(self.lang, "row_ctx_details"), self)
        act_details.triggered.connect(lambda: ToolInfoDialog(self, t).exec())
        menu.addAction(act_details)

        if t.has_gear:
            act_cfg = QAction(tr(self.lang, "row_ctx_configure"), self)
            act_cfg.triggered.connect(lambda: self.open_gear(t))
            menu.addAction(act_cfg)

        act_copy = QAction(tr(self.lang, "row_ctx_copy_path"), self)
        path_info = f"{self._format_scope_display(t)}\n{t.live_location_detail}".strip()
        act_copy.triggered.connect(
            lambda: (
                QApplication.clipboard().setText(path_info),
                self.set_status(tr(self.lang, "msg_path_copied", name=t.name)),
            )
        )
        menu.addAction(act_copy)

        menu.addSeparator()
        act_reset = QAction(tr(self.lang, "row_ctx_reset"), self)
        act_reset.triggered.connect(lambda: self.reset_tool_to_defaults(t))
        menu.addAction(act_reset)

        if t.has_update and t.latest_version:
            menu.addSeparator()
            lat_v = t.latest_version.strip().lstrip("vV")
            act_upd = QAction(tr(self.lang, "row_ctx_update", ver=lat_v), self)
            act_upd.triggered.connect(lambda: self._run_batch_update([t], install_if_missing=True))
            menu.addAction(act_upd)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def copy_tools_status_report(self, enabled_only: bool = False) -> None:
        """Build and copy a clean plaintext status report (invoked from Diagnostics)."""
        target_tools = [t for t in self.tools if (not enabled_only or t.enabled)]
        target_tools.sort(key=lambda x: (0 if x.enabled else 1, x.name.lower()))
        active_tok, saved_tok = self._calculate_token_economy()
        en_cnt = sum(1 for t in target_tools if t.enabled)
        now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        gpu_txt = self.vram_lbl.text() if hasattr(self, "vram_lbl") and self.vram_lbl.isVisible() else "N/A"

        lines = [
            f"=== AIconomy Status Report ({now_str}) ===",
            f"Tools: {len(target_tools)} ({en_cnt} enabled, {len(target_tools) - en_cnt} disabled)",
            f"Token Budget: Active {fmt_tokens(active_tok)} | Saved +{fmt_tokens(saved_tok)} | GPU: {gpu_txt}",
            "",
        ]
        for idx, t in enumerate(target_tools, start=1):
            st_tag = "ON" if t.enabled else "OFF"
            port_part = f" · :{t.port}" if t.port else ""
            ver_s = f"v{t.version.strip().lstrip('vV')}"
            lines.append(f"{idx}. [{st_tag}] {t.name} ({tool_kind_label(t.kind, self.lang)} · {ver_s}{port_part})")
            scope_str = self._format_scope_display(t)
            loc_str = f" | {t.live_location_detail}" if t.live_location_detail else ""
            lines.append(f"   - Scope: {scope_str}{loc_str}")

            if t.id == "blender_skills":
                mode_str = f"{len(self.active_skills)}/{len(BLENDER_SKILLS_94)} skills"
            elif len(t.modes) > 1 and 0 <= t.mode_index < len(t.modes):
                mode_str = localized_tool_modes(t, self.lang)[t.mode_index]
            else:
                mode_str = tr(self.lang, "standard")

            on_clients = [c for c, _ in AI_CLIENTS if t.clients.get(c, False)]
            clients_str = ", ".join(on_clients) if on_clients else tr(self.lang, "none")
            lines.append(f"   - Status: {t.last_ping} | Mode: {mode_str} | Clients: {clients_str}")

            if t.id == "blender_skills" and self.active_skills:
                lines.append(f"   - Active skills ({len(self.active_skills)}): {', '.join(sorted(self.active_skills))}")

            if t.vault_key_name:
                has_k = self.vault.has_secret(t.vault_key_name)
                lines.append(f"   - API key ({t.vault_key_name}): {'Configured' if has_k else 'Missing'}")

        QApplication.clipboard().setText("\n".join(lines))
        self.set_status(tr(self.lang, "msg_report_copied", n=len(target_tools)))

    def _on_tool_scope_changed(self, tool: ToolSpec, new_scope: str) -> None:
        if new_scope == "__ADD_NEW__":
            self._prompt_add_project_folder(assign_tool=tool)
            return
        tool.project_scope = new_scope
        if new_scope != "GLOBAL" and new_scope in self.projects_map:
            proj_dir = self.projects_map[new_scope]
            if tool.id in ("unity_pipeline", "renderdoc_mcp"):
                tool.param_value = proj_dir
        self._save_state()
        live_map = scan_live_process_locations(lang=self.lang)
        missing_keys = self._missing_required_vault_keys()
        _, h_state, ping_str, ms, _, loc_det = probe_tool_health(
            tool,
            len(self.active_skills),
            self.projects_map,
            live_map,
            lang=self.lang,
            missing_required_keys=missing_keys,
        )
        tool.health_state = h_state
        tool.last_ping = ping_str
        tool.last_latency_ms = ms
        tool.live_location_detail = loc_det
        scope_disp = self._format_scope_display(tool)
        self.logs.add("INFO", tool.name, tr(self.lang, "log_scope_changed", scope=scope_disp), loc_det)
        self._set_config_status(tr(self.lang, "msg_scope_changed", name=tool.name, scope=scope_disp))
        self._refresh_table()
        self._refresh_logs_tab()
        self._sync_live_environment_async(
            target_tools=[tool],
            restart_running=(tool.id == "serena" and tool.enabled),
        )
