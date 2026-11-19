"""Curated 100-Tool Plugins Library & Workspace Manager tab mixin (zero auto-downloads, EN & TR, K9 thread-safe)."""
from __future__ import annotations

import copy
import threading
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...catalog import (
    ALL_TAG_IDS,
    LIBRARY_CATEGORY_IDS,
    ToolSpec,
    category_label,
    localized_tool_text,
    tag_label,
    tool_kind_label,
)
from ...i18n import tr
from ...plugins import (
    PluginCheckResult,
    check_all_tools_updates_parallel,
    install_library_tool,
    update_single_tool,
)
from ...tokens import fmt_tokens
from ...updater import parse_semver
from ..dialogs.add_repo import AddRepoDialog
from ..dialogs.tool_info import ToolInfoDialog
from ..theme import active_tag_combo_qss, tag_button_qss
from ..workers import safe_emit


class PluginsTabMixin:
    """Mixin implementing Tab 1 (Curated 100-Tool Plugins Library + Workspace Updates)."""

    def _init_plugins_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # 1. LIBRARY FILTER BAR (Search + Category + Tag + Status)
        self._plug_search_debounce = QTimer(self)
        self._plug_search_debounce.setSingleShot(True)
        self._plug_search_debounce.setInterval(120)
        self._plug_search_debounce.timeout.connect(self._refresh_plugins_tab)

        flt = QHBoxLayout()
        flt.setSpacing(8)

        self.plug_search_inp = QLineEdit()
        self.plug_search_inp.setPlaceholderText(tr(self.lang, "plug_search_ph"))
        self.plug_search_inp.setMinimumWidth(240)
        self.plug_search_inp.textChanged.connect(lambda _txt: self._plug_search_debounce.start())
        flt.addWidget(self.plug_search_inp, stretch=1)

        self.plug_cat_cmb = QComboBox()
        self.plug_cat_cmb.setMinimumWidth(175)
        self.plug_cat_cmb.currentIndexChanged.connect(self._refresh_plugins_tab)
        flt.addWidget(self.plug_cat_cmb)

        self.plug_tag_cmb = QComboBox()
        self.plug_tag_cmb.setMinimumWidth(155)
        self.plug_tag_cmb.currentIndexChanged.connect(self._refresh_plugins_tab)
        flt.addWidget(self.plug_tag_cmb)

        self.plug_status_cmb = QComboBox()
        self.plug_status_cmb.setMinimumWidth(155)
        self.plug_status_cmb.currentIndexChanged.connect(self._refresh_plugins_tab)
        flt.addWidget(self.plug_status_cmb)

        lay.addLayout(flt)

        # 2. SUMMARY & WORKSPACE UPDATE BAR
        banner = QFrame()
        banner.setObjectName("card")
        b_lay = QHBoxLayout(banner)
        b_lay.setContentsMargins(12, 7, 12, 7)
        b_lay.setSpacing(8)

        self.plugins_banner_lbl = QLabel("")
        self.plugins_banner_lbl.setStyleSheet("font-weight: 600;")
        b_lay.addWidget(self.plugins_banner_lbl, stretch=1)

        self.btn_jump_err_logs = QPushButton(tr(self.lang, "plug_btn_view_errs"))
        self.btn_jump_err_logs.setObjectName("warnBtn")
        self.btn_jump_err_logs.hide()
        self.btn_jump_err_logs.clicked.connect(self._jump_to_error_logs)
        b_lay.addWidget(self.btn_jump_err_logs)

        self.btn_plugins_check = QPushButton(tr(self.lang, "plug_check"))
        self.btn_plugins_check.clicked.connect(lambda: self.run_plugin_update_check(manual=True))
        b_lay.addWidget(self.btn_plugins_check)

        self.btn_plugins_update_all = QPushButton(tr(self.lang, "plug_upd_avail", n=0))
        self.btn_plugins_update_all.setObjectName("successBtn")
        self.btn_plugins_update_all.setEnabled(False)
        self.btn_plugins_update_all.clicked.connect(self._handle_start_available_updates)
        b_lay.addWidget(self.btn_plugins_update_all)

        self.btn_add_github = QPushButton(tr(self.lang, "plug_add_github"))
        self.btn_add_github.clicked.connect(self._open_add_repo_dialog)
        b_lay.addWidget(self.btn_add_github)

        lay.addWidget(banner)

        self.update_prog = QProgressBar()
        self.update_prog.hide()
        lay.addWidget(self.update_prog)

        # 3. SCROLLABLE CURATED LIBRARY CARDS
        self.plugins_scroll = QScrollArea()
        self.plugins_scroll.setWidgetResizable(True)
        self.plugins_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.plugins_scroll.viewport().setObjectName("cellBox")
        self.plugins_host = QWidget()
        self.plugins_host.setObjectName("cellBox")
        self.plugins_lay = QVBoxLayout(self.plugins_host)
        self.plugins_lay.setContentsMargins(0, 0, 4, 0)
        self.plugins_lay.setSpacing(6)
        self.plugins_scroll.setWidget(self.plugins_host)
        lay.addWidget(self.plugins_scroll, stretch=1)

        self._rebuild_plugin_filter_combos()
        self.tabs.addTab(tab, tr(self.lang, "tab_plugins_cnt", n=len(self.tools)))

    def _rebuild_plugin_filter_combos(self) -> None:
        if not hasattr(self, "plug_cat_cmb"):
            return

        cur_cat = self.plug_cat_cmb.currentData() if self.plug_cat_cmb.count() else "ALL"
        cat_counts: dict[str, int] = {}
        for t in self.tools:
            c = getattr(t, "category", "coding_dev")
            cat_counts[c] = cat_counts.get(c, 0) + 1

        self.plug_cat_cmb.blockSignals(True)
        self.plug_cat_cmb.clear()
        self.plug_cat_cmb.addItem(f"{tr(self.lang, 'cat_all')} ({len(self.tools)})", "ALL")
        for cid in LIBRARY_CATEGORY_IDS:
            cnt = cat_counts.get(cid, 0)
            self.plug_cat_cmb.addItem(f"{category_label(cid, self.lang)} ({cnt})", cid)
        idx_c = self.plug_cat_cmb.findData(cur_cat)
        self.plug_cat_cmb.setCurrentIndex(max(0, idx_c))
        self.plug_cat_cmb.blockSignals(False)

        cur_tag = self.plug_tag_cmb.currentData() if self.plug_tag_cmb.count() else "ALL"
        present_lib_tags = {tg for t in self.tools for tg in t.tags}
        self.plug_tag_cmb.blockSignals(True)
        self.plug_tag_cmb.clear()
        self.plug_tag_cmb.addItem(tr(self.lang, "tag_all"), "ALL")
        for tid in ALL_TAG_IDS:
            if tid in present_lib_tags:
                self.plug_tag_cmb.addItem(tag_label(tid, self.lang), tid)
        idx_t = self.plug_tag_cmb.findData(cur_tag)
        self.plug_tag_cmb.setCurrentIndex(max(0, idx_t))
        self.plug_tag_cmb.blockSignals(False)

        cur_st = self.plug_status_cmb.currentData() if self.plug_status_cmb.count() else "ALL"
        ws_cnt = sum(1 for t in self.tools if getattr(t, "in_workspace", True))
        lib_cnt = len(self.tools) - ws_cnt
        self.plug_status_cmb.blockSignals(True)
        self.plug_status_cmb.clear()
        self.plug_status_cmb.addItem(tr(self.lang, "plug_flt_all"), "ALL")
        self.plug_status_cmb.addItem(f"{tr(self.lang, 'plug_flt_workspace')} ({ws_cnt})", "WORKSPACE")
        self.plug_status_cmb.addItem(f"{tr(self.lang, 'plug_flt_library')} ({lib_cnt})", "LIBRARY")
        self.plug_status_cmb.addItem(tr(self.lang, "plug_flt_free"), "FREE")
        self.plug_status_cmb.addItem(tr(self.lang, "plug_flt_updates"), "UPDATES")
        idx_s = self.plug_status_cmb.findData(cur_st)
        self.plug_status_cmb.setCurrentIndex(max(0, idx_s))
        self.plug_status_cmb.blockSignals(False)

    def _filter_plugins_by_tag(self, tag_code: str) -> None:
        cur = str(self.plug_tag_cmb.currentData() or "ALL")
        target = "ALL" if cur == tag_code else tag_code
        idx = self.plug_tag_cmb.findData(target)
        if idx >= 0:
            self.plug_tag_cmb.setCurrentIndex(idx)

    def _open_add_repo_dialog(self) -> None:
        dlg = AddRepoDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.added_tool is not None:
            new_tool = dlg.added_tool
            self.tools.append(new_tool)
            self._save_state()
            self._rebuild_tag_filter_combo()
            self._rebuild_plugin_filter_combos()
            self._update_tab_titles()
            self._refresh_table()
            self._refresh_plugins_tab()
            self.tabs.setCurrentIndex(0)
            self.set_status(tr(self.lang, "msg_repo_added", name=new_tool.name))

    def _filtered_plugin_tools(self) -> list[ToolSpec]:
        q = self.plug_search_inp.text().strip().lower()
        cat_f = str(self.plug_cat_cmb.currentData() or "ALL")
        tag_f = str(self.plug_tag_cmb.currentData() or "ALL")
        st_f = str(self.plug_status_cmb.currentData() or "ALL")

        out: list[ToolSpec] = []
        for t in self.tools:
            in_ws = bool(getattr(t, "in_workspace", True))
            t_cat = getattr(t, "category", "coding_dev")
            if cat_f != "ALL" and t_cat != cat_f:
                continue
            if tag_f != "ALL" and tag_f not in t.tags:
                continue
            if st_f == "WORKSPACE" and not in_ws:
                continue
            if st_f == "LIBRARY" and in_ws:
                continue
            if st_f == "FREE" and bool(t.vault_key_required):
                continue
            if st_f == "UPDATES" and not (in_ws and t.has_update):
                continue
            if q:
                summary = localized_tool_text(t, "summary", self.lang).lower()
                cat_lbl = category_label(t_cat, self.lang).lower()
                tags_joined = " ".join(tag_label(tg, self.lang).lower() for tg in t.tags)
                if (
                    q not in t.name.lower()
                    and q not in t.id.lower()
                    and q not in summary
                    and q not in cat_lbl
                    and q not in tags_joined
                    and q not in t.install_cmd.lower()
                    and q not in t.vault_key_name.lower()
                ):
                    continue
            out.append(t)

        out.sort(
            key=lambda x: (
                0 if (getattr(x, "in_workspace", True) and x.has_update) else 1,
                0 if getattr(x, "in_workspace", True) else 1,
                x.name.lower(),
            )
        )
        return out

    def _refresh_plugins_tab(self) -> None:
        if not hasattr(self, "plugins_lay"):
            return

        # Keep status combo counts fresh without re-triggering signal recursion
        ws_cnt = sum(1 for t in self.tools if getattr(t, "in_workspace", True))
        lib_cnt = len(self.tools) - ws_cnt
        if self.plug_status_cmb.count() >= 3:
            self.plug_status_cmb.setItemText(1, f"{tr(self.lang, 'plug_flt_workspace')} ({ws_cnt})")
            self.plug_status_cmb.setItemText(2, f"{tr(self.lang, 'plug_flt_library')} ({lib_cnt})")

        while self.plugins_lay.count():
            item = self.plugins_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        upd_count = sum(1 for t in self.tools if getattr(t, "in_workspace", True) and t.has_update)
        self.btn_plugins_update_all.setText(tr(self.lang, "plug_upd_avail", n=upd_count))
        self.btn_plugins_update_all.setEnabled(upd_count > 0 and not self.updating_busy)

        filtered = self._filtered_plugin_tools()
        is_light = self.meta.get("theme", "dark") == "light"
        muted_col = "#64748b" if is_light else "#94a3b8"
        tag_f = str(self.plug_tag_cmb.currentData() or "ALL")
        self.plug_tag_cmb.setStyleSheet(active_tag_combo_qss(tag_f, is_light=is_light))

        if not self.checking_plugins_busy:
            base_txt = tr(
                self.lang,
                "plug_banner_library",
                shown=len(filtered),
                tot=len(self.tools),
                ws=ws_cnt,
                lib=lib_cnt,
            )
            if upd_count > 0:
                upd_txt = tr(self.lang, "plug_banner_updates", n=upd_count)
                self.plugins_banner_lbl.setText(f"{base_txt}  |  {upd_txt}")
                self.plugins_banner_lbl.setStyleSheet("color: #f59e0b; font-weight: 600;")
            else:
                self.plugins_banner_lbl.setText(base_txt)
                self.plugins_banner_lbl.setStyleSheet(f"color: {muted_col}; font-weight: 600;")

        cat_pill_style = (
            "background-color: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
            if is_light
            else "background-color: #132036; color: #93c5fd; border: 1px solid #1e3a5f; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )
        kind_pill_style = (
            "background-color: #e2e8f0; color: #475569; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
            if is_light
            else "background-color: #1a2434; color: #94a3b8; border: 1px solid #263549; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )
        ws_badge_style = (
            "background-color: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 700;"
            if is_light
            else "background-color: #0d281e; color: #6ee7b7; border: 1px solid #14533c; border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 700;"
        )
        not_dl_badge_style = (
            "background-color: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 600;"
            if is_light
            else "background-color: #141c28; color: #94a3b8; border: 1px solid #263549; border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 600;"
        )

        if not filtered:
            empty_card = QFrame()
            empty_card.setObjectName("card")
            e_lay = QVBoxLayout(empty_card)
            e_lay.setContentsMargins(16, 22, 16, 22)
            e_lbl = QLabel(tr(self.lang, "plug_empty_match"))
            e_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e_lbl.setStyleSheet(f"color: {muted_col};")
            e_lay.addWidget(e_lbl)
            self.plugins_lay.addWidget(empty_card)
            self.plugins_lay.addStretch()
            return

        for t in filtered:
            in_ws = bool(getattr(t, "in_workspace", True))
            card = QFrame()
            card.setObjectName("card")
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 8, 12, 8)
            row.setSpacing(10)

            info_col = QVBoxLayout()
            info_col.setSpacing(3)

            title_row = QHBoxLayout()
            title_row.setSpacing(7)

            name_btn = QPushButton(t.name.replace("&", "&&"))
            name_btn.setObjectName("ghostBtn")
            name_btn.setStyleSheet("font-weight: 700; padding: 0px; text-align: left;")
            name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            name_btn.clicked.connect(lambda _=False, tool_obj=t: ToolInfoDialog(self, tool_obj).exec())
            title_row.addWidget(name_btn)

            cat_lbl = QLabel(category_label(getattr(t, "category", "coding_dev"), self.lang))
            cat_lbl.setStyleSheet(cat_pill_style)
            title_row.addWidget(cat_lbl)

            kind_lbl = QLabel(tool_kind_label(t.kind, self.lang))
            kind_lbl.setStyleSheet(kind_pill_style)
            title_row.addWidget(kind_lbl)

            tok_lbl = QLabel(f"~{fmt_tokens(t.schema_tokens)}")
            tok_lbl.setStyleSheet(f"color: {muted_col}; font-family: Consolas, monospace; font-size: 10.5px;")
            title_row.addWidget(tok_lbl)

            cur_v = t.version.strip().lstrip("vV")
            lat_v = (t.latest_version or t.version).strip().lstrip("vV")
            if in_ws and t.has_update and lat_v != cur_v:
                ver_html = (
                    f"<span style='color:#f59e0b; font-weight:700;'>"
                    f"{tr(self.lang, 'plug_ver_update', cur=cur_v, lat=lat_v)}</span>"
                )
            else:
                ver_html = f"<span style='color:{muted_col}; font-size:11px;'>v{cur_v}</span>"
            title_row.addWidget(QLabel(ver_html))

            if t.vault_key_name:
                has_secret = self.vault.has_secret(t.vault_key_name)
                if has_secret:
                    k_txt = tr(self.lang, "plug_key_ready")
                    k_col = "#10b981"
                elif t.vault_key_required:
                    k_txt = tr(self.lang, "plug_key_req", key=t.vault_key_name)
                    k_col = "#f59e0b"
                else:
                    k_txt = tr(self.lang, "plug_key_opt")
                    k_col = muted_col
                k_lbl = QLabel(k_txt)
                k_lbl.setStyleSheet(f"color: {k_col}; font-size: 10.5px; font-weight: 600;")
                title_row.addWidget(k_lbl)

            title_row.addStretch()
            info_col.addLayout(title_row)

            summary = localized_tool_text(t, "summary", self.lang)
            if summary:
                desc_lbl = QLabel(summary)
                desc_lbl.setStyleSheet(f"color: {muted_col}; font-size: 11px;")
                desc_lbl.setWordWrap(True)
                info_col.addWidget(desc_lbl)

            if t.tags:
                tg_row = QHBoxLayout()
                tg_row.setContentsMargins(0, 0, 0, 0)
                tg_row.setSpacing(5)
                for tg in t.tags[:3]:
                    tg_txt = tag_label(tg, self.lang)
                    is_hi = tag_f != "ALL" and tg == tag_f
                    tg_btn = QPushButton(tg_txt.replace("&", "&&"))
                    tg_btn.setStyleSheet(tag_button_qss(tg, is_highlighted=is_hi, is_light=is_light))
                    tg_btn.setFixedHeight(16)
                    tg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    tg_btn.setToolTip(tr(self.lang, "tag_filter_tip", tag=tg_txt))
                    tg_btn.clicked.connect(lambda _=False, code=tg: self._filter_plugins_by_tag(code))
                    tg_row.addWidget(tg_btn)
                tg_row.addStretch()
                info_col.addLayout(tg_row)

            row.addLayout(info_col, stretch=1)

            if in_ws and t.release_notes_url:
                notes_lbl = QLabel(
                    f"<a style='color:#60a5fa;' href='{t.release_notes_url}'>{tr(self.lang, 'plug_release_notes')}</a>"
                )
                notes_lbl.setOpenExternalLinks(True)
                notes_lbl.setToolTip(t.release_notes_url)
                row.addWidget(notes_lbl)

            copy_cmd = QPushButton(tr(self.lang, "plug_btn_copy_cmd"))
            copy_cmd.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_cmd.setToolTip(t.install_cmd or t.repo_url)
            copy_cmd.clicked.connect(
                lambda _=False, c=(t.install_cmd or t.repo_url), nm=t.name: (
                    QApplication.clipboard().setText(c),
                    self.set_status(tr(self.lang, "msg_cmd_copied", name=nm)),
                )
            )
            row.addWidget(copy_cmd)

            if not in_ws:
                is_inst = bool(getattr(t, "installed", False))
                installing_ids = getattr(self, "_installing_tool_ids", set())
                is_busy_this = t.id in installing_ids
                if not is_inst:
                    nd_lbl = QLabel(tr(self.lang, "plug_badge_not_dl"))
                    nd_lbl.setFixedHeight(26)
                    nd_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    nd_lbl.setStyleSheet(not_dl_badge_style)
                    row.addWidget(nd_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

                    dl_txt = tr(self.lang, "plug_btn_installing" if is_busy_this else "plug_btn_install_add")
                    dl_btn = QPushButton(dl_txt.replace("&", "&&"))
                    dl_btn.setObjectName("primaryBtn")
                    dl_btn.setEnabled(not self.updating_busy and not is_busy_this)
                    dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    dl_btn.setToolTip(tr(self.lang, "plug_btn_install_add_tip"))
                    dl_btn.clicked.connect(lambda _=False, tool_obj=t: self.install_and_add_tool(tool_obj))
                    row.addWidget(dl_btn)
                else:
                    add_btn = QPushButton(tr(self.lang, "plug_btn_add_ws").replace("&", "&&"))
                    add_btn.setObjectName("primaryBtn")
                    add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    add_btn.setToolTip(tr(self.lang, "plug_btn_add_ws_tip"))
                    add_btn.clicked.connect(lambda _=False, tool_obj=t: self.add_tool_to_workspace(tool_obj))
                    row.addWidget(add_btn)
            else:
                ws_lbl = QLabel(tr(self.lang, "plug_badge_in_ws"))
                ws_lbl.setFixedHeight(26)
                ws_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ws_lbl.setStyleSheet(ws_badge_style)
                row.addWidget(ws_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

                if t.has_update:
                    upd_one = QPushButton(tr(self.lang, "plug_btn_update"))
                    upd_one.setObjectName("warnBtn")
                    upd_one.setCursor(Qt.CursorShape.PointingHandCursor)
                    upd_one.clicked.connect(
                        lambda _=False, tool_obj=t: self._run_batch_update([tool_obj], install_if_missing=True)
                    )
                    row.addWidget(upd_one)

                rem_btn = QPushButton(tr(self.lang, "plug_btn_remove_ws"))
                rem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                rem_btn.setToolTip(tr(self.lang, "plug_btn_remove_ws_tip"))
                rem_btn.clicked.connect(lambda _=False, tool_obj=t: self.remove_tool_from_workspace(tool_obj))
                row.addWidget(rem_btn)

            self.plugins_lay.addWidget(card)
        self.plugins_lay.addStretch()

    def run_plugin_update_check(self, manual: bool = False) -> None:
        if self.checking_plugins_busy or self.updating_busy:
            return

        ws_tools = [t for t in self.tools if getattr(t, "in_workspace", True)]
        if not ws_tools:
            self._refresh_plugins_tab()
            return

        if not manual:
            last_ts = float(self.meta.get("last_plugin_check_ts", 0.0) or 0.0)
            cached = self.meta.get("plugin_update_cache")
            if isinstance(cached, dict) and cached and (time.time() - last_ts) < 1800:
                for t in ws_tools:
                    entry = cached.get(t.id)
                    if isinstance(entry, dict):
                        lat = str(entry.get("latest_version", "") or "").strip()
                        if lat:
                            t.latest_version = lat
                            t.has_update = parse_semver(lat) > parse_semver(t.version)
                        notes = str(entry.get("release_notes_url", "") or "").strip()
                        if notes:
                            t.release_notes_url = notes
                self._update_tab_titles()
                self._refresh_table()
                self._refresh_plugins_tab()
                return

        self.checking_plugins_busy = True
        self.btn_plugins_check.setEnabled(False)
        self.plugins_banner_lbl.setText(tr(self.lang, "plug_banner_checking"))
        self.plugins_banner_lbl.setStyleSheet("color: #94a3b8; font-weight: 600;")
        if manual:
            self.set_status(tr(self.lang, "msg_plug_checking"))

        snap = copy.deepcopy(ws_tools)
        tok = self.vault.get_secret("GITHUB_TOKEN")
        lang_snap = self.lang

        def worker() -> None:
            results, chk_errs = check_all_tools_updates_parallel(snap, tok)
            for t_name, err_det in chk_errs:
                self.logs.add(
                    "WARN",
                    t_name,
                    tr(lang_snap, "log_upd_chk_err", err=err_det.splitlines()[0]),
                    err_det,
                )
            safe_emit(self.bridge.plugin_check_done, results, manual)

        threading.Thread(target=worker, daemon=True).start()

    def _on_plugin_check_done(self, results: list[PluginCheckResult] | None, manual: bool) -> None:
        self.checking_plugins_busy = False
        self.btn_plugins_check.setEnabled(True)
        self.btn_jump_err_logs.hide()

        if results:
            by_id = {t.id: t for t in self.tools}
            for item in results:
                t = by_id.get(item.tool_id)
                if t is None:
                    continue
                if item.local_version:
                    t.version = item.local_version
                t.latest_version = item.latest_version
                t.has_update = item.has_update
                t.release_notes_url = item.release_notes_url
            self.meta["last_plugin_check_ts"] = time.time()
            self.meta["plugin_update_cache"] = {
                t.id: {
                    "latest_version": t.latest_version,
                    "release_notes_url": t.release_notes_url,
                }
                for t in self.tools
                if getattr(t, "in_workspace", True)
            }
            self._save_state()

        upd_count = sum(1 for t in self.tools if getattr(t, "in_workspace", True) and t.has_update)
        self._refresh_logs_tab()

        if upd_count == 0:
            if manual:
                self.set_status(tr(self.lang, "msg_plug_all_ok"))
        else:
            self.set_status(tr(self.lang, "msg_plug_updates_found", n=upd_count))
            if manual:
                self.tabs.setCurrentIndex(1)

        self._update_tab_titles()
        self._refresh_table()
        self._refresh_plugins_tab()

    def _handle_start_available_updates(self) -> None:
        targets = [t for t in self.tools if getattr(t, "in_workspace", True) and t.has_update]
        if not targets:
            self.set_status(tr(self.lang, "msg_plug_all_ok"))
            return
        self._run_batch_update(targets, install_if_missing=True)

    def _run_batch_update(self, target_tools: list[ToolSpec], install_if_missing: bool = False) -> None:
        if self.updating_busy or not target_tools:
            return
        self.updating_busy = True
        self.btn_plugins_check.setEnabled(False)
        self.btn_plugins_update_all.setEnabled(False)

        total = len(target_tools)
        self.update_prog.setMaximum(total)
        self.update_prog.setValue(0)
        self.update_prog.setFormat(tr(self.lang, "plug_prog_init", tot=total))
        self.update_prog.show()
        self.set_status(tr(self.lang, "msg_plug_updating", n=total))

        wanted_skills = set(self.active_skills)
        items = copy.deepcopy(target_tools)
        lang_snap = self.lang

        def worker() -> None:
            ok_cnt = 0
            fail_cnt = 0
            details: list[str] = []
            for idx, tool_snap in enumerate(items, start=1):
                safe_emit(self.bridge.update_progress, idx, total, tool_snap.name)
                prev_v = tool_snap.version.strip().lstrip("vV")
                ok, new_ver, msg, raw_log = update_single_tool(
                    tool_snap, wanted_skills, install_if_missing=install_if_missing, lang=lang_snap
                )
                target_v = (tool_snap.latest_version or new_ver or tool_snap.version).strip().lstrip("vV")
                safe_emit(self.bridge.update_item_done, tool_snap.id, ok, prev_v, target_v, msg, raw_log)
                if ok:
                    ok_cnt += 1
                    ver_note = f"v{prev_v} -> v{target_v}" if prev_v != target_v else f"v{target_v}"
                    details.append(f"OK {tool_snap.name} ({ver_note}): {msg}")
                else:
                    fail_cnt += 1
                    details.append(f"ERR {tool_snap.name}: {msg}")
            safe_emit(self.bridge.update_all_done, ok_cnt, fail_cnt, "\n".join(details))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_item_done(
        self, tool_id: str, ok: bool, prev_v: str, target_v: str, msg: str, raw_log: str
    ) -> None:
        tool_obj = next((t for t in self.tools if t.id == tool_id), None)
        t_name = tool_obj.name if tool_obj else tool_id
        if ok:
            if tool_obj is not None:
                tool_obj.version = f"v{target_v}"
                tool_obj.latest_version = f"v{target_v}"
                tool_obj.has_update = False
            ver_note = f"v{prev_v} -> v{target_v}" if prev_v != target_v else f"v{target_v}"
            self.logs.add("INFO", t_name, tr(self.lang, "log_plug_updated", ver=ver_note), raw_log)
        else:
            self.logs.add("ERR", t_name, tr(self.lang, "log_plug_upd_fail", msg=msg), raw_log)

    def _on_update_progress(self, idx: int, total: int, tool_name: str) -> None:
        self.update_prog.setValue(idx - 1)
        step = tr(self.lang, "plug_prog_step", idx=idx, tot=total, name=tool_name)
        self.update_prog.setFormat(step)
        self.set_status(step)

    def _on_update_all_done(self, ok_cnt: int, fail_cnt: int, _summary_text: str) -> None:
        self.updating_busy = False
        self.btn_plugins_check.setEnabled(True)
        self.update_prog.setValue(self.update_prog.maximum())
        self.update_prog.setFormat(tr(self.lang, "plug_prog_done", ok=ok_cnt, fail=fail_cnt))
        QTimer.singleShot(3500, self.update_prog.hide)

        self._on_plugin_check_done(None, manual=False)
        if fail_cnt > 0:
            self.plugins_banner_lbl.setText(tr(self.lang, "plug_banner_err", fail=fail_cnt, ok=ok_cnt))
            self.plugins_banner_lbl.setStyleSheet("color: #ef4444; font-weight: 600;")
            self.btn_jump_err_logs.show()
            self.set_status(tr(self.lang, "msg_plug_update_err", fail=fail_cnt))
        else:
            self.set_status(tr(self.lang, "msg_plug_update_ok", n=ok_cnt))
        self._save_state()
        self._refresh_logs_tab()

    def _run_library_install(self, target_tools: list[ToolSpec], enable_after: bool = False) -> None:
        """Download & install library tools on demand (never runs subprocesses when sync_live_environment=False)."""
        if not target_tools:
            return
        if not self.sync_live_environment:
            for t in target_tools:
                t.installed = True
                self.add_tool_to_workspace(t)
                if enable_after:
                    t.enabled = True
                    if not any(t.clients.values()):
                        t.clients["AGY"] = True
            self._save_state()
            self._refresh_table()
            self._refresh_plugins_tab()
            return

        if self.updating_busy:
            return
        self.updating_busy = True
        self.btn_plugins_check.setEnabled(False)
        self.btn_plugins_update_all.setEnabled(False)
        self.btn_jump_err_logs.hide()
        for t in target_tools:
            self._installing_tool_ids.add(t.id)

        total = len(target_tools)
        self.update_prog.setMaximum(total)
        self.update_prog.setValue(0)
        self.update_prog.setFormat(tr(self.lang, "plug_prog_dl_init", tot=total))
        self.update_prog.show()
        self.set_status(tr(self.lang, "msg_lib_installing", n=total))
        self._refresh_plugins_tab()

        wanted_skills = set(self.active_skills)
        items = copy.deepcopy(target_tools)
        lang_snap = self.lang

        def worker() -> None:
            ok_cnt = 0
            fail_cnt = 0
            for idx, tool_snap in enumerate(items, start=1):
                safe_emit(self.bridge.lib_install_progress, idx, total, tool_snap.name)
                ok, new_ver, msg, raw_log = install_library_tool(
                    tool_snap, wanted_skills, lang=lang_snap
                )
                safe_emit(
                    self.bridge.lib_install_item_done,
                    tool_snap.id,
                    ok,
                    new_ver,
                    msg,
                    raw_log,
                    enable_after,
                )
                if ok:
                    ok_cnt += 1
                else:
                    fail_cnt += 1
            safe_emit(self.bridge.lib_install_all_done, ok_cnt, fail_cnt)

        threading.Thread(target=worker, daemon=True).start()

    def _on_lib_install_progress(self, idx: int, total: int, tool_name: str) -> None:
        self.update_prog.setValue(idx - 1)
        step = tr(self.lang, "plug_prog_dl_step", idx=idx, tot=total, name=tool_name)
        self.update_prog.setFormat(step)
        self.set_status(step)

    def _on_lib_install_item_done(
        self,
        tool_id: str,
        ok: bool,
        new_ver: str,
        msg: str,
        raw_log: str,
        enable_after: bool,
    ) -> None:
        self._installing_tool_ids.discard(tool_id)
        tool_obj = next((t for t in self.tools if t.id == tool_id), None)
        t_name = tool_obj.name if tool_obj else tool_id
        if ok and tool_obj is not None:
            if new_ver:
                clean_v = new_ver.strip().lstrip("vV")
                if clean_v:
                    tool_obj.version = f"v{clean_v}"
            tool_obj.installed = True
            self.add_tool_to_workspace(tool_obj)
            if enable_after:
                missing_keys = self._missing_required_vault_keys()
                tool_obj.enabled = True
                if not any(tool_obj.clients.values()):
                    tool_obj.clients["AGY"] = True
                if tool_obj.vault_key_required and tool_obj.vault_key_name and tool_obj.vault_key_name in missing_keys:
                    tool_obj.health_state = "warn"
                    tool_obj.last_ping = tr(self.lang, "st_missing_key")
                else:
                    tool_obj.health_state = "ok"
                    tool_obj.last_ping = tr(self.lang, "st_ready")
                self._sync_live_environment_async(target_tools=[tool_obj])
            self.logs.add(
                "INFO",
                t_name,
                tr(self.lang, "log_plug_installed", ver=tool_obj.version, msg=msg),
                raw_log,
            )
        else:
            self.logs.add("ERR", t_name, tr(self.lang, "log_plug_inst_fail", msg=msg), raw_log)

    def _on_lib_install_all_done(self, ok_cnt: int, fail_cnt: int) -> None:
        self.updating_busy = False
        self._installing_tool_ids.clear()
        self.btn_plugins_check.setEnabled(True)
        self.update_prog.setValue(self.update_prog.maximum())
        self.update_prog.setFormat(tr(self.lang, "plug_prog_dl_done", ok=ok_cnt, fail=fail_cnt))
        QTimer.singleShot(3500, self.update_prog.hide)

        if fail_cnt > 0:
            self.plugins_banner_lbl.setText(tr(self.lang, "plug_banner_err", fail=fail_cnt, ok=ok_cnt))
            self.plugins_banner_lbl.setStyleSheet("color: #ef4444; font-weight: 600;")
            self.btn_jump_err_logs.show()
            self.set_status(tr(self.lang, "msg_lib_install_err", fail=fail_cnt))
        elif ok_cnt > 1:
            self.set_status(tr(self.lang, "msg_lib_install_ok", n=ok_cnt))

        self._save_state()
        self._rebuild_tag_filter_combo()
        self._rebuild_plugin_filter_combos()
        self._update_tab_titles()
        self._refresh_table()
        self._refresh_plugins_tab()
        self._refresh_logs_tab()
        self.run_health_scan()
