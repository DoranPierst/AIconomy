"""Tools panel tab mixin (search/filter bar, host-app banner, tools matrix table)."""
from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...catalog import AI_CLIENTS, BLENDER_SKILLS_94, ToolSpec
from ...i18n import tr
from ...processes import probe_tool_health, scan_live_process_locations
from ..dialogs.tool_info import ToolInfoDialog
from ..widgets import AiMatrixHeaderView, HoverTableWidget


class ToolsTabMixin:
    """Mixin implementing Tab 1 (Tools panel)."""

    def _make_info_btn(self, tool: ToolSpec) -> QPushButton:
        btn = QPushButton("?")
        btn.setFixedSize(20, 20)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        is_light = self.meta.get("theme", "dark") == "light"
        btn.setStyleSheet(
            "QPushButton { background-color: #dbeafe; color: #1d4ed8; border: 1px solid #60a5fa; "
            "border-radius: 10px; font-size: 11px; font-weight: 800; padding: 0px; }"
            "QPushButton:hover { background-color: #2563eb; color: #ffffff; }"
            if is_light
            else "QPushButton { background-color: #172554; color: #93c5fd; border: 1px solid #3b82f6; "
            "border-radius: 10px; font-size: 11px; font-weight: 800; padding: 0px; }"
            "QPushButton:hover { background-color: #2563eb; color: #ffffff; }"
        )
        tip_parts = [f"❓ {tool.name} — Ne İşe Yarar?"]
        if tool.summary:
            tip_parts.append(tool.summary)
        if tool.when_to_use:
            tip_parts.append(f"\n💡 Ne zaman kullanılır:\n{tool.when_to_use}")
        tip_parts.append("\n(Detaylı açıklama kartını açmak için tıklayın)")
        btn.setToolTip("\n".join(tip_parts))
        btn.clicked.connect(lambda _=False, t_obj=tool: ToolInfoDialog(self, t_obj).exec())
        return btn

    def _init_panel_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        flt = QHBoxLayout()
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("Araç, görev veya konum ara (örn: Serena, shader, ses, doküman)...")
        self.search_inp.setFixedWidth(250)
        self.search_inp.textChanged.connect(self._refresh_table)
        flt.addWidget(self.search_inp)

        self.kind_cmb = QComboBox()
        for k_data, k_lbl in [
            ("ALL", tr(self.lang, "all_types")),
            ("Skill Paketi", "Skill Paketi"),
            ("Skill / Kural", "Skill / Kural"),
            ("stdio MCP", "stdio MCP"),
            ("HTTP Servis", "HTTP Servis"),
            ("CLI / GPU", "CLI / GPU"),
        ]:
            self.kind_cmb.addItem(k_lbl, k_data)
        self.kind_cmb.currentIndexChanged.connect(self._refresh_table)
        flt.addWidget(self.kind_cmb)

        self.lbl_proj_flt = QLabel(tr(self.lang, "project_lbl"))
        flt.addWidget(self.lbl_proj_flt)
        self.proj_filter_cmb = QComboBox()
        self.proj_filter_cmb.currentIndexChanged.connect(self._refresh_table)
        flt.addWidget(self.proj_filter_cmb)

        self.btn_add_proj = QPushButton(tr(self.lang, "add_project"))
        self.btn_add_proj.setToolTip("Yeni bir oyun veya web sitesi klasörünü proje listesine ekler")
        self.btn_add_proj.clicked.connect(lambda: self._prompt_add_project_folder(assign_tool=None))
        flt.addWidget(self.btn_add_proj)

        flt.addStretch()

        preset_box = QFrame()
        preset_box.setObjectName("card")
        pb_lay = QHBoxLayout(preset_box)
        pb_lay.setContentsMargins(8, 3, 8, 3)
        pb_lay.setSpacing(6)

        self.lbl_saved_presets = QLabel(tr(self.lang, "saved_presets_lbl"))
        pb_lay.addWidget(self.lbl_saved_presets)

        self.saved_presets_cmb = QComboBox()
        self.saved_presets_cmb.setMinimumWidth(220)
        self.saved_presets_cmb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.saved_presets_cmb.setToolTip(
            "Daha önce isim vererek kaydettiğiniz özel araç/proje düzenlerini listeler.\n"
            "• Bir kayıt seçtiğinizde tüm araçlar (AÇIK/KAPALI, AI istemcileri, proje kapsamı, modlar) o kayda döner."
        )
        self.saved_presets_cmb.currentIndexChanged.connect(self._on_custom_preset_selected)
        pb_lay.addWidget(self.saved_presets_cmb)

        self.btn_save_preset = QPushButton(tr(self.lang, "save_btn"))
        self.btn_save_preset.setObjectName("primaryBtn")
        self.btn_save_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_preset.setToolTip("Şu anki araç, AI ve proje ayarlarınızı istediğiniz bir isimle kaydeder")
        self.btn_save_preset.clicked.connect(self._save_custom_preset)
        pb_lay.addWidget(self.btn_save_preset)

        self.btn_del_preset = QPushButton("🗑️")
        self.btn_del_preset.setFixedSize(28, 26)
        self.btn_del_preset.setStyleSheet("padding: 0px; font-size: 13px;")
        self.btn_del_preset.setEnabled(False)
        self.btn_del_preset.setToolTip("Seçili kayıtlı ayarı sil")
        self.btn_del_preset.clicked.connect(self._delete_custom_preset)
        pb_lay.addWidget(self.btn_del_preset)

        flt.addWidget(preset_box)
        lay.addLayout(flt)

        self.host_dep_banner = QFrame()
        self.host_dep_banner.setObjectName("card")
        self.host_dep_banner.setStyleSheet("QFrame#card { border: 1px solid #f59e0b; background-color: #271a0c; }")
        hdb_lay = QHBoxLayout(self.host_dep_banner)
        hdb_lay.setContentsMargins(10, 5, 10, 5)
        hdb_lay.setSpacing(8)
        self.host_dep_lbl = QLabel("")
        self.host_dep_lbl.setStyleSheet("color: #fde68a; font-weight: 600;")
        self.host_dep_lbl.setWordWrap(True)
        hdb_lay.addWidget(self.host_dep_lbl, stretch=1)
        self.host_dep_btns_lay = QHBoxLayout()
        self.host_dep_btns_lay.setSpacing(6)
        hdb_lay.addLayout(self.host_dep_btns_lay)
        self.host_dep_banner.hide()
        lay.addWidget(self.host_dep_banner)

        self.table = HoverTableWidget(0, 8, self)
        self.ai_header = AiMatrixHeaderView(self.table, self)
        self.bulk_client_btns: dict[str, QPushButton] = self.ai_header.buttons
        self.table.setHorizontalHeader(self.ai_header)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setHorizontalHeaderLabels(
            [
                "Araç",
                "Tür",
                "Proje / Konum",
                "Son Yanıt",
                "Kullanım",
                "",
                "Çalışma Modu",
                "Detay / Durum",
            ]
        )
        hdr = self.ai_header
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(5, AiMatrixHeaderView.AI_COL_WIDTH)
        self.table.setColumnWidth(5, AiMatrixHeaderView.AI_COL_WIDTH)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr.sectionClicked.connect(self._on_header_clicked)
        self.table.horizontalScrollBar().valueChanged.connect(lambda *_: hdr.sync_ai_bar_geometry())
        lay.addWidget(self.table, stretch=1)

        panel_bot = QHBoxLayout()
        panel_bot.setContentsMargins(2, 4, 2, 0)

        self.lbl_panel_sel = QLabel("☑️ Seçili: 14 / 14 araç")
        self.lbl_panel_sel.setStyleSheet("color: #94a3b8; font-weight: 600;")
        panel_bot.addWidget(self.lbl_panel_sel)

        btn_p_all = QPushButton("Tümünü Seç")
        btn_p_all.clicked.connect(lambda: self._set_panel_checks("all"))
        panel_bot.addWidget(btn_p_all)

        btn_p_act = QPushButton("Sadece Açıkları Seç")
        btn_p_act.setToolTip("Yalnızca şu an durumu AÇIK olan araçları seçer")
        btn_p_act.clicked.connect(lambda: self._set_panel_checks("enabled_only"))
        panel_bot.addWidget(btn_p_act)

        btn_p_none = QPushButton("Seçimi Temizle")
        btn_p_none.clicked.connect(lambda: self._set_panel_checks("none"))
        panel_bot.addWidget(btn_p_none)

        panel_bot.addStretch()

        self.btn_copy_tools_status = QPushButton("📋 Seçili Araçların Genel Durumunu Kopyala (14)")
        self.btn_copy_tools_status.setObjectName("primaryBtn")
        self.btn_copy_tools_status.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_tools_status.setToolTip(
            "Yalnızca tabloda işaretlediğiniz araçların genel durumunu (Açık/Kapalı, AI istemcileri,\n"
            "çalışma modu, son yanıt, aktif seçenekler ve proje konumları) düzenli rapor olarak kopyalar."
        )
        self.btn_copy_tools_status.clicked.connect(self._copy_selected_tools_status)
        panel_bot.addWidget(self.btn_copy_tools_status)
        lay.addLayout(panel_bot)

        self.tabs.addTab(tab, "📊 Araç Paneli (14)")

    def _rebuild_project_filter_combo(self) -> None:
        cur_data = self.proj_filter_cmb.currentData() if self.proj_filter_cmb.count() else "ALL"
        self.proj_filter_cmb.blockSignals(True)
        self.proj_filter_cmb.clear()
        self.proj_filter_cmb.addItem(tr(self.lang, "all_scopes"), "ALL")
        self.proj_filter_cmb.addItem(tr(self.lang, "global_only"), "GLOBAL")
        for p_name in sorted(self.projects_map.keys()):
            self.proj_filter_cmb.addItem(f"📁 {p_name}", p_name)
        idx = self.proj_filter_cmb.findData(cur_data)
        self.proj_filter_cmb.setCurrentIndex(max(0, idx))
        self.proj_filter_cmb.blockSignals(False)

    def _prompt_add_project_folder(self, assign_tool: ToolSpec | None) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Proje Klasörünü Seçin (Unity, Web Sitesi vb.)")
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
        self.set_status(f"📁 Yeni proje tanımlandı: {proj_key} ({p_path})")

    def _on_header_clicked(self, col: int) -> None:
        key_map = {0: "name", 1: "kind", 2: "project", 3: "ping", 4: "usage", 6: "mode", 7: "enabled"}
        if col not in key_map:
            return
        k = key_map[col]
        if self.sort_key == k:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = k
            self.sort_desc = col in (3, 4, 7)
        self._save_state()
        self._refresh_table()

    def _update_panel_header_indicators(self) -> None:
        base_labels = [
            tr(self.lang, "col_tool"),
            tr(self.lang, "col_kind"),
            tr(self.lang, "col_project"),
            tr(self.lang, "col_ping"),
            tr(self.lang, "col_usage"),
            "",
            tr(self.lang, "col_mode"),
            tr(self.lang, "col_status"),
        ]
        key_to_col = {
            "name": 0,
            "kind": 1,
            "project": 2,
            "ping": 3,
            "usage": 4,
            "mode": 6,
            "enabled": 7,
        }
        active_col = key_to_col.get(self.sort_key, -1)
        arrow = " ▼" if self.sort_desc else " ▲"
        labels = [
            f"{lbl}{arrow}" if (idx == active_col and lbl) else lbl
            for idx, lbl in enumerate(base_labels)
        ]
        self.table.setHorizontalHeaderLabels(labels)

    def _tool_sort_value(self, item: ToolSpec) -> Any:
        if self.sort_key == "name":
            return item.name.lower()
        if self.sort_key == "kind":
            return (item.kind.lower(), item.name.lower())
        if self.sort_key == "project":
            if item.scope_selectable:
                vis = "tüm projeler" if item.project_scope == "GLOBAL" else item.project_scope.lower()
            else:
                raw = (item.fixed_location_label or "sistem geneli").strip()
                vis = raw.lstrip("🖥️🌐📁📍🟢⚠️☁️ ").lower()
            return (vis, item.name.lower())
        if self.sort_key == "ping":
            if item.last_latency_ms >= 0:
                return (1, -item.last_latency_ms, item.name.lower())
            return (0, 0, item.last_ping.lower(), item.name.lower())
        if self.sort_key == "mode":
            if item.id == "blender_skills":
                m_txt = f"{len(self.active_skills):02d}/94"
            elif len(item.modes) > 1:
                m_txt = item.modes[item.mode_index].lower()
            else:
                m_txt = "~"
            return (m_txt, item.name.lower())
        if self.sort_key == "enabled":
            return (1 if item.enabled else 0, item.usage_count, item.name.lower())
        return (item.usage_count, item.name.lower())

    def _calculate_token_economy(self) -> tuple[int, int]:
        active_tok = 0
        saved_tok = 0
        for t in self.tools:
            if t.id == "blender_skills":
                per_skill = 350
                on_cnt = len(self.active_skills) if t.enabled else 0
                active_tok += on_cnt * per_skill
                saved_tok += (len(BLENDER_SKILLS_94) - on_cnt) * per_skill
            else:
                if t.enabled:
                    active_tok += t.schema_tokens
                else:
                    saved_tok += t.schema_tokens
        return round(active_tok / 1000), round(saved_tok / 1000)

    def _refresh_table(self) -> None:
        q = self.search_inp.text().strip().lower()
        kf = str(self.kind_cmb.currentData() or "ALL")
        pf = self.proj_filter_cmb.currentData() or "ALL"

        rows: list[ToolSpec] = []
        for t in self.tools:
            if q and (
                q not in t.name.lower()
                and q not in t.kind.lower()
                and q not in t.summary.lower()
                and q not in t.project_scope.lower()
                and q not in t.live_location_detail.lower()
            ):
                continue
            if kf != "ALL" and t.kind != kf:
                continue
            if pf == "GLOBAL" and (not t.scope_selectable or t.project_scope != "GLOBAL"):
                continue
            if pf not in ("ALL", "GLOBAL"):
                if t.scope_selectable and t.project_scope not in (pf, "GLOBAL"):
                    continue
            rows.append(t)

        self._update_panel_header_indicators()
        rows.sort(key=self._tool_sort_value, reverse=self.sort_desc)
        panel_checked_set = self._get_panel_checked_set()
        self.panel_row_checks.clear()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))

        for r_idx, t in enumerate(rows):
            self.table.setRowHeight(r_idx, 38)

            nm_w = QWidget()
            nm_w.setObjectName("cellBox")
            nm_l = QHBoxLayout(nm_w)
            nm_l.setContentsMargins(10, 2, 6, 2)
            nm_l.setSpacing(6)

            row_cb = QCheckBox()
            row_cb.setCursor(Qt.CursorShape.PointingHandCursor)
            row_cb.setChecked(t.id in panel_checked_set)
            row_cb.setToolTip(f"{t.name} aracını durum kopyalama listesine dahil et / çıkar")
            row_cb.toggled.connect(lambda checked, tid=t.id: self._on_panel_row_check_toggled(tid, checked))
            self.panel_row_checks[t.id] = row_cb
            nm_l.addWidget(row_cb)

            nm_lbl = QLabel(f"<b>{t.name}</b>")
            if t.summary or t.live_location_detail:
                nm_lbl.setToolTip(f"{t.summary}\n\n{t.live_location_detail}".strip())
            nm_l.addWidget(nm_lbl)

            cur_v = t.version.strip().lstrip("vV")
            lat_v = (t.latest_version or t.version).strip().lstrip("vV")
            if t.has_update and lat_v != cur_v:
                ver_lbl = QLabel(f"{cur_v}v > {lat_v}v")
                ver_lbl.setStyleSheet(
                    "color: #f59e0b; background-color: #271a0c; border: 1px solid #f59e0b; "
                    "border-radius: 4px; padding: 1px 5px; font-size: 10px; font-weight: 700;"
                )
                ver_lbl.setToolTip(f"Eklenti güncellemesi mevcut: {cur_v}v -> {lat_v}v")
            else:
                ver_lbl = QLabel(f"{cur_v}v")
                ver_lbl.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600;")
                ver_lbl.setToolTip(f"{t.name} kurulu sürümü: {cur_v}v")
            nm_l.addWidget(ver_lbl)

            nm_l.addWidget(self._make_info_btn(t))
            nm_l.addStretch()
            self.table.setCellWidget(r_idx, 0, nm_w)

            kd_item = QTableWidgetItem(t.kind)
            kd_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r_idx, 1, kd_item)

            proj_w = QWidget()
            proj_w.setObjectName("cellBox")
            proj_l = QHBoxLayout(proj_w)
            proj_l.setContentsMargins(4, 2, 4, 2)
            proj_l.setSpacing(4)

            is_live = (
                t.enabled
                and t.live_location_detail.startswith("🟢")
                and (t.id != "blender_mcp" or t.last_latency_ms >= 0)
            )
            is_warn = t.live_location_detail.startswith("⚠️")
            tooltip_full = f"{self._format_scope_display(t)}\n{t.live_location_detail}".strip()

            if t.scope_selectable:
                p_cmb = QComboBox()
                p_cmb.addItem("🌐 Tüm Projeler", "GLOBAL")
                for p_name in sorted(self.projects_map.keys()):
                    p_cmb.addItem(f"📁 {p_name}", p_name)
                p_cmb.addItem("➕ Klasör Seç...", "__ADD_NEW__")

                cur_idx = p_cmb.findData(t.project_scope)
                p_cmb.setCurrentIndex(cur_idx if cur_idx >= 0 else 0)
                p_cmb.setToolTip(tooltip_full)
                p_cmb.currentIndexChanged.connect(
                    lambda _idx, cmb=p_cmb, tool_obj=t: self._on_tool_scope_changed(tool_obj, str(cmb.currentData()))
                )
                proj_l.addWidget(p_cmb, stretch=1)
            else:
                fixed_lbl = QLabel(t.fixed_location_label or "🖥️ Sistem Geneli")
                fixed_lbl.setStyleSheet("color: #94a3b8; padding-left: 4px;")
                fixed_lbl.setToolTip(tooltip_full)
                proj_l.addWidget(fixed_lbl, stretch=1)

            loc_btn = QPushButton("🟢" if is_live else ("⚠️" if is_warn else "📍"))
            loc_btn.setFixedSize(32, 26)
            loc_btn.setStyleSheet("padding: 0px; font-size: 13px;")
            loc_btn.setToolTip(f"{tooltip_full}\n(Konum bilgisini panoya kopyalamak için tıklayın)")
            loc_btn.clicked.connect(
                lambda _=False, info=tooltip_full, nm=t.name: (
                    QApplication.clipboard().setText(info),
                    self.set_status(f"📍 {nm} konum bilgisi kopyalandı: {info.splitlines()[-1]}"),
                )
            )
            proj_l.addWidget(loc_btn)
            self.table.setCellWidget(r_idx, 2, proj_w)

            pg_item = QTableWidgetItem(t.last_ping)
            pg_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r_idx, 3, pg_item)

            us_item = QTableWidgetItem(str(t.usage_count))
            us_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            us_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r_idx, 4, us_item)

            mat_w = QWidget()
            mat_w.setObjectName("cellBox")
            mat_l = QHBoxLayout(mat_w)
            mat_l.setContentsMargins(4, 2, 4, 2)
            mat_l.setSpacing(3)
            for code, full_lbl in AI_CLIENTS:
                c_btn = QPushButton(code)
                c_btn.setCheckable(True)
                is_c_on = t.clients.get(code, False)
                c_btn.setChecked(is_c_on)
                c_btn.setToolTip(f"{full_lbl}: {'Açık' if is_c_on else 'Kapalı'}")
                c_btn.setFixedWidth(36)
                c_btn.setStyleSheet(
                    "background-color: #1d4ed8; color: #fff; font-size: 10px; font-weight: 700; padding: 2px;"
                    if is_c_on
                    else "color: #64748b; font-size: 10px; padding: 2px;"
                )
                c_btn.clicked.connect(lambda checked, tool_obj=t, c=code: self._toggle_client(tool_obj, c, checked))
                mat_l.addWidget(c_btn)
            self.table.setCellWidget(r_idx, 5, mat_w)

            mod_w = QWidget()
            mod_w.setObjectName("cellBox")
            mod_l = QHBoxLayout(mod_w)
            mod_l.setContentsMargins(4, 2, 4, 2)
            if t.id == "blender_skills":
                sk_btn = QPushButton(f"{len(self.active_skills)} / 94 Açık")
                sk_btn.clicked.connect(lambda _=False, tool_obj=t: self.open_gear(tool_obj))
                mod_l.addWidget(sk_btn)
            elif len(t.modes) > 1:
                cmb = QComboBox()
                cmb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
                cmb.addItems(t.modes)
                cmb.setCurrentIndex(t.mode_index)
                cmb.currentIndexChanged.connect(lambda idx, tool_obj=t: self._change_mode(tool_obj, idx))
                mod_l.addWidget(cmb)
            else:
                dash = QLabel("—")
                dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
                dash.setStyleSheet("color: #64748b;")
                mod_l.addWidget(dash)
            self.table.setCellWidget(r_idx, 6, mod_w)

            act_w = QWidget()
            act_w.setObjectName("cellBox")
            act_l = QHBoxLayout(act_w)
            act_l.setContentsMargins(4, 2, 4, 2)
            act_l.setSpacing(5)
            act_l.addStretch()
            if t.has_gear:
                g_btn = QPushButton("⚙️")
                g_btn.setFixedSize(34, 26)
                g_btn.setStyleSheet("padding: 0px; font-size: 13px;")
                g_btn.setToolTip(f"{t.name} Detaylı Ayarlar, Konum & AI'a Danış")
                g_btn.clicked.connect(lambda _=False, tool_obj=t: self.open_gear(tool_obj))
                act_l.addWidget(g_btn)

            t_btn = QPushButton(tr(self.lang, "state_on") if t.enabled else tr(self.lang, "state_off"))
            t_btn.setFixedWidth(66)
            if t.enabled:
                t_btn.setObjectName("primaryBtn")
            t_btn.clicked.connect(lambda _=False, tool_obj=t: self._toggle_tool(tool_obj))
            act_l.addWidget(t_btn)
            self.table.setCellWidget(r_idx, 7, act_w)

        active_k, saved_k = self._calculate_token_economy()
        self.token_summary_lbl.setText(tr(self.lang, "token_summary", act=active_k, sav=saved_k))
        self.table.resizeColumnToContents(6)
        self._update_bulk_client_buttons()
        self._update_panel_selection_ui()
        self.ai_header.sync_ai_bar_geometry()
        self.table._refresh_hover_from_cursor()

    def _get_panel_checked_set(self) -> set[str]:
        saved = self.meta.get("panel_checked_ids")
        if isinstance(saved, list):
            return {str(x) for x in saved}
        all_ids = [t.id for t in self.tools]
        self.meta["panel_checked_ids"] = all_ids
        return set(all_ids)

    def _on_panel_row_check_toggled(self, tool_id: str, checked: bool) -> None:
        cur = self._get_panel_checked_set()
        if checked:
            cur.add(tool_id)
        else:
            cur.discard(tool_id)
        self.meta["panel_checked_ids"] = [t.id for t in self.tools if t.id in cur]
        self._update_panel_selection_ui()
        self._save_state()

    def _set_panel_checks(self, mode: str) -> None:
        if mode == "all":
            target = {t.id for t in self.tools}
        elif mode == "enabled_only":
            target = {t.id for t in self.tools if t.enabled}
        else:
            target = set()
        self.meta["panel_checked_ids"] = [t.id for t in self.tools if t.id in target]
        for tid, cb in self.panel_row_checks.items():
            cb.blockSignals(True)
            cb.setChecked(tid in target)
            cb.blockSignals(False)
        self._update_panel_selection_ui()
        self._save_state()

    def _update_panel_selection_ui(self) -> None:
        cur = self._get_panel_checked_set()
        sel_cnt = sum(1 for t in self.tools if t.id in cur)
        tot_cnt = len(self.tools)
        self.lbl_panel_sel.setText(f"☑️ Seçili: {sel_cnt} / {tot_cnt} araç")
        self.btn_copy_tools_status.setText(f"📋 Seçili Araçların Genel Durumunu Kopyala ({sel_cnt})")
        self.ai_header.master_cb.blockSignals(True)
        self.ai_header.master_cb.setChecked(tot_cnt > 0 and sel_cnt == tot_cnt)
        self.ai_header.master_cb.blockSignals(False)

    def _copy_selected_tools_status(self) -> None:
        checked_set = self._get_panel_checked_set()
        selected_tools = [t for t in self.tools if t.id in checked_set]
        if not selected_tools:
            QMessageBox.information(
                self,
                "Araç Seçilmedi",
                "Genel durumu kopyalamak için lütfen Araç Paneli tablosundan en az bir aracı işaretleyin.",
            )
            return

        selected_tools.sort(key=self._tool_sort_value, reverse=self.sort_desc)
        active_k, saved_k = self._calculate_token_economy()
        en_cnt = sum(1 for t in selected_tools if t.enabled)
        now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        gpu_txt = self.vram_bar.text()

        lines = [
            f"=== AI Araç & Token Ekonomisi Genel Durum Raporu ({now_str}) ===",
            f"Seçili Araç: {len(selected_tools)} / {len(self.tools)} ({en_cnt} Açık, {len(selected_tools) - en_cnt} Kapalı)",
            f"Token Ekonomisi: Aktif Şema ~{active_k}K tok | Korunan Tasarruf +{saved_k}K tok | GPU: {gpu_txt}",
            "",
        ]

        for idx, t in enumerate(selected_tools, start=1):
            st_tag = "AÇIK" if t.enabled else "KAPALI"
            port_part = f" · Port :{t.port}" if t.port else ""
            lines.append(f"{idx}. [{st_tag}] {t.name} ({t.kind} · {t.version}{port_part})")

            scope_str = self._format_scope_display(t)
            loc_str = f" | {t.live_location_detail}" if t.live_location_detail else ""
            lines.append(f"   • Kapsam & Konum: {scope_str}{loc_str}")

            if t.id == "blender_skills":
                mode_str = f"{len(self.active_skills)} / {len(BLENDER_SKILLS_94)} Skill Açık"
            elif len(t.modes) > 1 and 0 <= t.mode_index < len(t.modes):
                mode_str = t.modes[t.mode_index]
            else:
                mode_str = "Standart"

            on_clients = [c for c, _ in AI_CLIENTS if t.clients.get(c, False)]
            clients_str = ", ".join(on_clients) if on_clients else "Hiçbiri (Tümü Kapalı)"
            lines.append(f"   • Son Yanıt: {t.last_ping} | Çalışma Modu: {mode_str} | Açık AI İstemcileri: {clients_str}")

            if t.id == "blender_skills" and self.active_skills:
                lines.append(f"   • Aktif Blender Skill'ler ({len(self.active_skills)}): {', '.join(sorted(self.active_skills))}")

            if t.options:
                on_opts = [o.label for o in t.options if o.enabled]
                if on_opts:
                    lines.append(f"   • Aktif Seçenekler: {', '.join(on_opts)}")

            if t.vault_key_name:
                has_k = bool(self.vault.get_secret(t.vault_key_name))
                lines.append(f"   • API Anahtarı ({t.vault_key_name}): {'Şifreli Kasada Kayıtlı ✓' if has_k else 'Girilmemiş'}")

        report_txt = "\n".join(lines)
        QApplication.clipboard().setText(report_txt)
        self.set_status(f"📋 Seçili {len(selected_tools)} aracın genel durum raporu panoya kopyalandı!")

        self.btn_copy_tools_status.setText(f"✓ Panoya Kopyalandı! ({len(selected_tools)} Araç)")
        self.btn_copy_tools_status.setObjectName("successBtn")
        self.style().unpolish(self.btn_copy_tools_status)
        self.style().polish(self.btn_copy_tools_status)

        def _restore_copy_btn() -> None:
            self.btn_copy_tools_status.setObjectName("primaryBtn")
            self._update_panel_selection_ui()
            self.style().unpolish(self.btn_copy_tools_status)
            self.style().polish(self.btn_copy_tools_status)

        QTimer.singleShot(1800, _restore_copy_btn)

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
        live_map = scan_live_process_locations()
        _, _, _, _, loc_det = probe_tool_health(tool, len(self.active_skills), self.projects_map, live_map)
        tool.live_location_detail = loc_det
        self.logs.add("INFO", tool.name, f"Proje kapsamı değiştirildi -> {self._format_scope_display(tool)}", loc_det)
        self.set_status(f"📁 {tool.name} kapsamı güncellendi: {self._format_scope_display(tool)}")
        self._refresh_table()
        self._refresh_logs_tab()
