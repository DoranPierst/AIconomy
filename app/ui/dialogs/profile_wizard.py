"""Task-based Profile Creation Wizard with General + Dynamic App-Specific Tags (emoji-free, EN & TR)."""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...catalog import (
    APP_SCOPE_IDS,
    BENEFIT_TAG_IDS,
    BLENDER_SKILL_INDEX_TOKENS,
    GENERAL_TAG_IDS,
    SCOPED_APP_TAG_IDS,
    ToolSpec,
    app_scope_label,
    is_benefit_tag,
    localized_tool_text,
    recommended_blender_skills_for_tags,
    split_scoped_tag,
    tag_label,
    tag_sub_label,
)
from ...i18n import tr
from ...oauth import supports_oauth
from ...tokens import CONTEXT_WINDOW_TOKENS, compute_token_breakdown, fmt_tokens
from ..theme import app_chip_qss, tag_pill_qss, wizard_chip_qss

if TYPE_CHECKING:
    from ..main_window import MainWindow


class ProfileWizardDialog(QDialog):
    """Build, name, save, and apply a custom profile by selecting general or app-specific tags."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.main_win = parent
        self.lang = parent.lang
        self.all_tools: list[ToolSpec] = list(parent.tools)
        self.workspace_tools: list[ToolSpec] = [
            t for t in parent.tools if getattr(t, "in_workspace", True)
        ]
        self.locked_keys: set[str] = set(parent._locked_vault_keys())
        self.missing_keys: set[str] = {
            t.vault_key_name
            for t in parent.tools
            if not (getattr(t, "auth_mode", "key") == "oauth" and supports_oauth(t.id))
            and t.vault_key_required
            and t.vault_key_name
            and t.vault_key_name not in self.locked_keys
            and not parent.vault.has_secret(t.vault_key_name)
        }

        self.selected_tags: list[str] = []
        self.checked_tool_ids: set[str] = set()
        self.manual_overrides: dict[str, bool] = {}
        self.name_touched: bool = False

        self.result_name: str = ""
        self.result_tool_ids: set[str] = set()
        self.result_skills: set[str] = set(parent.active_skills)
        self.result_tags: list[str] = []

        self.setWindowTitle(tr(self.lang, "wiz_title"))
        self.setMinimumSize(860, 620)
        self.resize(940, 710)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(9)

        # 1. THREE-TIER TAG SELECTION CARD (Advantage -> General -> App-Specific)
        tags_card = QFrame()
        tags_card.setObjectName("card")
        tc_lay = QVBoxLayout(tags_card)
        tc_lay.setContentsMargins(12, 9, 12, 9)
        tc_lay.setSpacing(7)

        is_light_init = parent.meta.get("theme", "dark") == "light"
        self.tag_buttons: dict[str, QPushButton] = {}
        self.app_header_buttons: dict[str, QPushButton] = {}
        self.app_subtags_map: dict[str, list[str]] = {}

        # Tier A: Advantage tags
        adv_row = QHBoxLayout()
        adv_row.setSpacing(8)
        adv_row.addWidget(QLabel(f"<b>{tr(self.lang, 'wiz_adv_lbl')}</b>"))

        for tid in BENEFIT_TAG_IDS:
            cnt = sum(1 for t in self.workspace_tools if tid in t.tags)
            lbl = f"{tag_label(tid, self.lang)} ({cnt})" if cnt else tag_label(tid, self.lang)
            btn = QPushButton(lbl.replace("&", "&&"))
            btn.setStyleSheet(wizard_chip_qss(tid, is_light=is_light_init, is_benefit=True))
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, tag_code=tid: self._on_tag_clicked(tag_code, checked))
            self.tag_buttons[tid] = btn
            adv_row.addWidget(btn)
        adv_row.addStretch()
        tc_lay.addLayout(adv_row)

        # Tier B: General cross-project tags (3 rows x 5 cols)
        tc_lay.addWidget(QLabel(f"<b>{tr(self.lang, 'wiz_task_lbl')}</b>"))
        gen_grid = QGridLayout()
        gen_grid.setSpacing(5)
        cols = 5
        for idx, tid in enumerate(GENERAL_TAG_IDS):
            cnt = sum(1 for t in self.workspace_tools if tid in t.tags)
            lbl = f"{tag_label(tid, self.lang)} ({cnt})" if cnt else tag_label(tid, self.lang)
            btn = QPushButton(lbl.replace("&", "&&"))
            btn.setStyleSheet(wizard_chip_qss(tid, is_light=is_light_init, is_benefit=False))
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if cnt == 0:
                btn.setToolTip(tr(self.lang, "wiz_tag_empty_tip"))
            btn.clicked.connect(lambda checked, tag_code=tid: self._on_tag_clicked(tag_code, checked))
            self.tag_buttons[tid] = btn
            gen_grid.addWidget(btn, idx // cols, idx % cols)
        tc_lay.addLayout(gen_grid)

        # Tier C: Dynamic App-Specific rows built from installed/active pool plugins
        self.app_sec_lbl = QLabel(f"<b>{tr(self.lang, 'wiz_app_lbl')}</b>")
        tc_lay.addWidget(self.app_sec_lbl)

        self.app_scroll = QScrollArea()
        self.app_scroll.setWidgetResizable(True)
        self.app_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.app_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.app_scroll.viewport().setObjectName("cellBox")
        self.app_host = QWidget()
        self.app_host.setObjectName("cellBox")
        self.app_rows_lay = QVBoxLayout(self.app_host)
        self.app_rows_lay.setContentsMargins(0, 0, 2, 0)
        self.app_rows_lay.setSpacing(4)
        self.app_scroll.setWidget(self.app_host)
        tc_lay.addWidget(self.app_scroll)

        root.addWidget(tags_card)

        # 2. MATCHED TOOLS HEADER + LIVE TOKEN ESTIMATE
        mid_hdr = QHBoxLayout()
        mid_hdr.setSpacing(10)
        self.tools_hdr_lbl = QLabel()
        mid_hdr.addWidget(self.tools_hdr_lbl)

        self.show_all_cb = QCheckBox(tr(self.lang, "wiz_show_all_cb"))
        self.show_all_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_all_cb.toggled.connect(lambda _v: self._rebuild_tools_list())
        mid_hdr.addWidget(self.show_all_cb)

        uninst_cnt = sum(1 for t in self.all_tools if not getattr(t, "in_workspace", True))
        self.include_lib_cb = QCheckBox(tr(self.lang, "wiz_include_lib_cb", n=uninst_cnt))
        self.include_lib_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.include_lib_cb.toggled.connect(self._on_include_lib_toggled)
        mid_hdr.addWidget(self.include_lib_cb)

        mid_hdr.addStretch()
        self.live_tok_lbl = QLabel()
        mid_hdr.addWidget(self.live_tok_lbl)
        root.addLayout(mid_hdr)

        # 3. SCROLLABLE TOOLS PREVIEW
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setObjectName("cellBox")
        self.list_host = QWidget()
        self.list_host.setObjectName("cellBox")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 4, 0)
        self.list_lay.setSpacing(5)
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, stretch=1)

        # 4. PROFILE NAME + SAVE & APPLY BAR
        name_card = QFrame()
        name_card.setObjectName("card")
        nm_lay = QHBoxLayout(name_card)
        nm_lay.setContentsMargins(12, 8, 12, 8)
        nm_lay.setSpacing(10)
        nm_lay.addWidget(QLabel(f"<b>{tr(self.lang, 'wiz_name_lbl')}</b>"))
        self.name_inp = QLineEdit()
        self.name_inp.setPlaceholderText(tr(self.lang, "wiz_name_ph"))
        self.name_inp.textEdited.connect(self._on_name_edited)
        nm_lay.addWidget(self.name_inp, stretch=1)
        root.addWidget(name_card)

        bot = QHBoxLayout()
        self.btn_clear = QPushButton(tr(self.lang, "wiz_btn_clear"))
        self.btn_clear.clicked.connect(self._clear_all)
        bot.addWidget(self.btn_clear)

        bot.addStretch()
        btn_cancel = QPushButton(tr(self.lang, "btn_cancel"))
        btn_cancel.clicked.connect(self.reject)
        bot.addWidget(btn_cancel)

        self.btn_save = QPushButton(tr(self.lang, "wiz_btn_save_apply").replace("&", "&&"))
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.clicked.connect(self._save_and_apply)
        bot.addWidget(self.btn_save)
        root.addLayout(bot)

        self._rebuild_app_specific_rows()
        self._rebuild_tools_list()

    def _active_pool(self) -> list[ToolSpec]:
        if hasattr(self, "include_lib_cb") and self.include_lib_cb.isChecked():
            return self.all_tools
        return self.workspace_tools

    def _rebuild_app_specific_rows(self) -> None:
        """Dynamically build app rows (Unity, Blender, Chrome, ...) from tools present in _active_pool."""
        for scoped_tid in list(SCOPED_APP_TAG_IDS):
            self.tag_buttons.pop(scoped_tid, None)
        self.app_header_buttons.clear()
        self.app_subtags_map.clear()

        while self.app_rows_lay.count():
            item = self.app_rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        pool = self._active_pool()
        is_light = self.main_win.meta.get("theme", "dark") == "light"

        # Discover present apps & their scoped subtags in canonical order
        app_to_subtags: dict[str, list[str]] = {}
        for stid in SCOPED_APP_TAG_IDS:
            app_id, _sub_id = split_scoped_tag(stid)
            if any(stid in t.tags for t in pool):
                app_to_subtags.setdefault(app_id, []).append(stid)

        ordered_apps = [aid for aid in APP_SCOPE_IDS if aid in app_to_subtags]
        for extra_aid in app_to_subtags:
            if extra_aid not in ordered_apps:
                ordered_apps.append(extra_aid)

        # Remove selected scoped tags that are no longer in the active pool
        valid_scoped = {st for sub_list in app_to_subtags.values() for st in sub_list}
        self.selected_tags = [
            tg for tg in self.selected_tags if (":" not in tg) or (tg in valid_scoped)
        ]

        if not ordered_apps:
            self.app_sec_lbl.hide()
            self.app_scroll.hide()
            return

        self.app_sec_lbl.show()
        self.app_scroll.show()

        for app_id in ordered_apps:
            subtags = app_to_subtags[app_id]
            self.app_subtags_map[app_id] = subtags
            app_tool_cnt = sum(
                1 for t in pool if any(tg.startswith(f"{app_id}:") for tg in t.tags)
            )
            app_name = app_scope_label(app_id, self.lang)

            row_w = QWidget()
            row_w.setObjectName("cellBox")
            r_lay = QHBoxLayout(row_w)
            r_lay.setContentsMargins(0, 0, 0, 0)
            r_lay.setSpacing(6)

            app_btn = QPushButton(f"{app_name} ({app_tool_cnt})".replace("&", "&&"))
            app_btn.setMinimumWidth(110)
            app_btn.setCheckable(True)
            app_btn.setChecked(all(st in self.selected_tags for st in subtags))
            app_btn.setStyleSheet(app_chip_qss(app_id, is_light=is_light))
            app_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            app_btn.setToolTip(tr(self.lang, "wiz_app_row_tip", app=app_name))
            app_btn.clicked.connect(
                lambda checked, a_code=app_id: self._on_app_header_clicked(a_code, checked)
            )
            self.app_header_buttons[app_id] = app_btn
            r_lay.addWidget(app_btn)

            sep_lbl = QLabel("->")
            sep_lbl.setStyleSheet("color: #64748b; font-weight: 600; font-size: 11px;")
            r_lay.addWidget(sep_lbl)

            for stid in subtags:
                sub_cnt = sum(1 for t in pool if stid in t.tags)
                sub_lbl = f"{tag_sub_label(stid, self.lang)} ({sub_cnt})"
                s_btn = QPushButton(sub_lbl.replace("&", "&&"))
                s_btn.setCheckable(True)
                s_btn.setChecked(stid in self.selected_tags)
                s_btn.setStyleSheet(wizard_chip_qss(stid, is_light=is_light, is_benefit=False))
                s_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                s_btn.setToolTip(tag_label(stid, self.lang))
                s_btn.clicked.connect(
                    lambda checked, tag_code=stid: self._on_tag_clicked(tag_code, checked)
                )
                self.tag_buttons[stid] = s_btn
                r_lay.addWidget(s_btn)

            r_lay.addStretch()
            self.app_rows_lay.addWidget(row_w)

        row_h = 34
        vis_rows = min(len(ordered_apps), 4)
        exact_h = vis_rows * row_h + max(0, vis_rows - 1) * 5 + 4
        self.app_scroll.setFixedHeight(exact_h)

    def _sync_app_header_check_states(self) -> None:
        for app_id, app_btn in self.app_header_buttons.items():
            subtags = self.app_subtags_map.get(app_id, [])
            all_on = bool(subtags) and all(st in self.selected_tags for st in subtags)
            app_btn.blockSignals(True)
            app_btn.setChecked(all_on)
            app_btn.blockSignals(False)

    def _on_app_header_clicked(self, app_id: str, checked: bool) -> None:
        subtags = self.app_subtags_map.get(app_id, [])
        for stid in subtags:
            if checked:
                if stid not in self.selected_tags:
                    self.selected_tags.append(stid)
            else:
                if stid in self.selected_tags:
                    self.selected_tags.remove(stid)
            s_btn = self.tag_buttons.get(stid)
            if s_btn is not None:
                s_btn.blockSignals(True)
                s_btn.setChecked(checked)
                s_btn.blockSignals(False)
        self._sync_app_header_check_states()
        self._sync_auto_checked_from_tags()
        self._rebuild_tools_list()

    def _refresh_general_chip_labels(self) -> None:
        pool = self._active_pool()
        for tid in BENEFIT_TAG_IDS + GENERAL_TAG_IDS:
            btn = self.tag_buttons.get(tid)
            if btn is None:
                continue
            cnt = sum(1 for t in pool if tid in t.tags)
            lbl = f"{tag_label(tid, self.lang)} ({cnt})" if cnt else tag_label(tid, self.lang)
            btn.setText(lbl.replace("&", "&&"))
            btn.setToolTip(tr(self.lang, "wiz_tag_empty_tip") if cnt == 0 else "")

    def _on_include_lib_toggled(self, _checked: bool) -> None:
        self._refresh_general_chip_labels()
        self._rebuild_app_specific_rows()
        self._sync_auto_checked_from_tags()
        self._rebuild_tools_list()

    def _on_name_edited(self, _txt: str) -> None:
        self.name_touched = bool(self.name_inp.text().strip())

    def _effective_blender_skills(self) -> set[str]:
        sel_set = set(self.selected_tags)
        if sel_set & {
            "modeling_3d",
            "blender:modeling_3d",
            "style_3d",
            "blender:style_3d",
            "shader_gpu",
            "unity:shader_gpu",
        } or any(tg.startswith("unity:") for tg in sel_set):
            return recommended_blender_skills_for_tags(sel_set)
        return set(self.main_win.active_skills)

    def _is_auto_selectable(self, t: ToolSpec) -> bool:
        if not any(t.clients.values()):
            return False
        if t.vault_key_required and t.vault_key_name and t.vault_key_name in self.missing_keys:
            return False
        return True

    def _build_smart_profile_name(self) -> str:
        non_ben = [tid for tid in self.selected_tags if not is_benefit_tag(tid)]
        ben_only = [tid for tid in self.selected_tags if is_benefit_tag(tid)]
        source = non_ben if non_ben else ben_only
        if not source:
            return ""

        # Condense multiple subtags of the same app (e.g. unity:*) into just "Unity"
        app_counts: dict[str, int] = {}
        for tid in source:
            aid, _ = split_scoped_tag(tid)
            if aid:
                app_counts[aid] = app_counts.get(aid, 0) + 1

        parts: list[str] = []
        seen_apps: set[str] = set()
        for tid in source:
            aid, _ = split_scoped_tag(tid)
            if aid and app_counts.get(aid, 0) >= 2:
                if aid not in seen_apps:
                    seen_apps.add(aid)
                    parts.append(app_scope_label(aid, self.lang))
            else:
                parts.append(tag_label(tid, self.lang))
            if len(parts) >= 2:
                break
        return " + ".join(parts)

    def _sync_auto_checked_from_tags(self) -> None:
        sel_set = set(self.selected_tags)
        new_checked: set[str] = set()
        for t in self._active_pool():
            if t.id in self.manual_overrides:
                if self.manual_overrides[t.id]:
                    new_checked.add(t.id)
                continue
            if sel_set and (sel_set & set(t.tags)) and self._is_auto_selectable(t):
                new_checked.add(t.id)
        self.checked_tool_ids = new_checked

        if not self.name_touched:
            self.name_inp.setText(self._build_smart_profile_name())

    def _on_tag_clicked(self, tag_code: str, checked: bool) -> None:
        if checked:
            if tag_code not in self.selected_tags:
                self.selected_tags.append(tag_code)
        else:
            if tag_code in self.selected_tags:
                self.selected_tags.remove(tag_code)
        self._sync_app_header_check_states()
        self._sync_auto_checked_from_tags()
        self._rebuild_tools_list()

    def _on_tool_check_toggled(self, tool_id: str, checked: bool) -> None:
        self.manual_overrides[tool_id] = checked
        if checked:
            self.checked_tool_ids.add(tool_id)
        else:
            self.checked_tool_ids.discard(tool_id)
        self._update_header_and_budget()

    def _clear_all(self) -> None:
        self.selected_tags.clear()
        self.checked_tool_ids.clear()
        self.manual_overrides.clear()
        self.name_touched = False
        self.name_inp.clear()
        for btn in self.tag_buttons.values():
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
        for abtn in self.app_header_buttons.values():
            abtn.blockSignals(True)
            abtn.setChecked(False)
            abtn.blockSignals(False)
        self._rebuild_tools_list()

    def _estimate_budget(self) -> tuple[int, float]:
        sim_tools = copy.deepcopy(self._active_pool())
        for t in sim_tools:
            t.in_workspace = True
            t.enabled = t.id in self.checked_tool_ids
            if t.enabled and not any(t.clients.values()):
                t.clients["AGY"] = True
        eff_skills = self._effective_blender_skills()
        bd = compute_token_breakdown(
            sim_tools,
            len(eff_skills),
            self.main_win.projects_map,
            missing_required_keys=self.missing_keys,
            installed_clients=self.main_win.installed_clients,
            locked_vault_keys=self.locked_keys,
        )
        pct = bd.active_tokens / CONTEXT_WINDOW_TOKENS * 100.0
        return bd.active_tokens, pct

    def _update_header_and_budget(self) -> None:
        pool = self._active_pool()
        sel_set = set(self.selected_tags)
        match_cnt = (
            sum(1 for t in pool if sel_set & set(t.tags))
            if sel_set
            else len(pool)
        )
        self.tools_hdr_lbl.setText(
            f"<b>{tr(self.lang, 'wiz_tools_hdr', sel=len(self.checked_tool_ids), match=match_cnt)}</b>"
        )
        act_tok, pct = self._estimate_budget()
        is_light = self.main_win.meta.get("theme", "dark") == "light"
        tok_col = "#047857" if is_light else "#34d399"
        self.live_tok_lbl.setStyleSheet(
            f"font-family: Consolas, 'Segoe UI', monospace; font-weight: 700; color: {tok_col};"
        )
        self.live_tok_lbl.setText(
            tr(self.lang, "wiz_live_budget", tok=fmt_tokens(act_tok), pct=f"{pct:.1f}")
        )

    def _rebuild_tools_list(self) -> None:
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        is_light = self.main_win.meta.get("theme", "dark") == "light"
        muted_col = "#64748b" if is_light else "#94a3b8"
        sel_set = set(self.selected_tags)

        if not sel_set and not self.checked_tool_ids:
            hint_card = QFrame()
            hint_card.setObjectName("bannerInfo")
            h_lay = QVBoxLayout(hint_card)
            h_lay.setContentsMargins(12, 8, 12, 8)
            h_lbl = QLabel(tr(self.lang, "wiz_pick_hint"))
            h_lbl.setWordWrap(True)
            h_lbl.setStyleSheet("font-size: 11px;")
            h_lay.addWidget(h_lbl)
            self.list_lay.addWidget(hint_card)

        pool = self._active_pool()
        if sel_set and not self.show_all_cb.isChecked():
            shown_tools = [
                t for t in pool if (sel_set & set(t.tags)) or (t.id in self.checked_tool_ids)
            ]
        else:
            shown_tools = list(pool)

        shown_tools.sort(
            key=lambda t: (
                0 if t.id in self.checked_tool_ids else 1,
                0 if (t.tags and t.tags[0] in sel_set) else 1,
                -len(sel_set & set(t.tags)),
                0 if getattr(t, "in_workspace", True) else 1,
                t.name.lower(),
            )
        )

        if not shown_tools:
            empty_card = QFrame()
            empty_card.setObjectName("card")
            e_lay = QVBoxLayout(empty_card)
            e_lay.setContentsMargins(14, 16, 14, 16)
            e_lbl = QLabel(tr(self.lang, "wiz_no_match"))
            e_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e_lbl.setStyleSheet(f"color: {muted_col};")
            e_lay.addWidget(e_lbl)
            self.list_lay.addWidget(empty_card)
        else:
            eff_skills = self._effective_blender_skills()
            for t in shown_tools:
                card = QFrame()
                card.setObjectName("card")
                r_lay = QHBoxLayout(card)
                r_lay.setContentsMargins(10, 6, 12, 6)
                r_lay.setSpacing(8)

                cb = QCheckBox()
                cb.setChecked(t.id in self.checked_tool_ids)
                cb.setCursor(Qt.CursorShape.PointingHandCursor)
                cb.toggled.connect(lambda checked, tid=t.id: self._on_tool_check_toggled(tid, checked))
                r_lay.addWidget(cb)

                info_col = QVBoxLayout()
                info_col.setSpacing(2)
                top_r = QHBoxLayout()
                top_r.setSpacing(6)
                nm_lbl = QLabel(f"<b>{t.name}</b>")
                nm_lbl.setToolTip(localized_tool_text(t, "summary", self.lang))
                top_r.addWidget(nm_lbl)

                is_inst = bool(getattr(t, "installed", getattr(t, "in_workspace", True)))
                if not is_inst:
                    lib_pill = QLabel(tr(self.lang, "wiz_lib_badge"))
                    lib_pill.setStyleSheet(
                        "background-color: #fffbeb; color: #b45309; border: 1px solid #fde68a; border-radius: 4px; padding: 1px 6px; font-size: 9.5px; font-weight: 700;"
                        if is_light
                        else "background-color: #291d09; color: #fbbf24; border: 1px solid #78350f; border-radius: 4px; padding: 1px 6px; font-size: 9.5px; font-weight: 700;"
                    )
                    top_r.addWidget(lib_pill)

                for tg in t.tags:
                    t_pill = QLabel(tag_label(tg, self.lang))
                    t_pill.setFixedHeight(16)
                    t_pill.setStyleSheet(tag_pill_qss(tg, is_highlighted=(tg in sel_set), is_light=is_light))
                    top_r.addWidget(t_pill)

                if t.id == "blender_skills":
                    sk_note = QLabel(tr(self.lang, "wiz_skills_auto", n=len(eff_skills)))
                    sk_note.setStyleSheet("color: #34d399; font-size: 10px; font-weight: 600;")
                    top_r.addWidget(sk_note)

                top_r.addStretch()
                info_col.addLayout(top_r)

                sum_lbl = QLabel(localized_tool_text(t, "summary", self.lang))
                sum_lbl.setStyleSheet(f"color: {muted_col}; font-size: 10.5px;")
                sum_lbl.setWordWrap(True)
                info_col.addWidget(sum_lbl)
                r_lay.addLayout(info_col, stretch=1)

                has_locked = bool(
                    not (getattr(t, "auth_mode", "key") == "oauth" and supports_oauth(t.id))
                    and t.vault_key_name
                    and t.vault_key_name in self.locked_keys
                )
                has_missing = bool(
                    not has_locked
                    and not (getattr(t, "auth_mode", "key") == "oauth" and supports_oauth(t.id))
                    and t.vault_key_required
                    and t.vault_key_name
                    and t.vault_key_name in self.missing_keys
                )
                if has_locked:
                    k_lbl = QLabel(tr(self.lang, "st_vault_locked"))
                    k_lbl.setStyleSheet("color: #f59e0b; font-size: 10px; font-weight: 700;")
                    r_lay.addWidget(k_lbl)
                elif has_missing:
                    k_lbl = QLabel(tr(self.lang, "st_missing_key"))
                    k_lbl.setStyleSheet("color: #f59e0b; font-size: 10px; font-weight: 700;")
                    r_lay.addWidget(k_lbl)

                cost = (
                    len(eff_skills) * BLENDER_SKILL_INDEX_TOKENS
                    if t.id == "blender_skills"
                    else int(t.schema_tokens)
                )
                cost_lbl = QLabel(f"~{fmt_tokens(cost)}")
                cost_lbl.setStyleSheet(
                    f"font-family: Consolas, 'Segoe UI', monospace; font-size: 11px; color: {muted_col};"
                )
                r_lay.addWidget(cost_lbl)
                self.list_lay.addWidget(card)

        self.list_lay.addStretch(1)
        self._update_header_and_budget()

    def _save_and_apply(self) -> None:
        name = self.name_inp.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                tr(self.lang, "prof_invalid_name_title"),
                tr(self.lang, "prof_invalid_name_msg"),
            )
            return
        presets = self.main_win._get_custom_presets()
        if name in presets:
            ans = QMessageBox.question(
                self,
                tr(self.lang, "prof_overwrite_title"),
                tr(self.lang, "prof_overwrite_msg", name=name),
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        self.result_name = name
        self.result_tool_ids = set(self.checked_tool_ids)
        self.result_skills = self._effective_blender_skills()
        self.result_tags = list(self.selected_tags)
        self.accept()
