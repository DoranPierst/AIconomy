"""Task-based Profile Creation Wizard ('Yapacağınız İşi Seçin' / 'Pick Your Task', emoji-free, EN & TR)."""
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
    BENEFIT_TAG_IDS,
    BLENDER_SKILL_INDEX_TOKENS,
    DOMAIN_TAG_IDS,
    ToolSpec,
    is_benefit_tag,
    localized_tool_text,
    recommended_blender_skills_for_tags,
    tag_label,
)
from ...i18n import tr
from ...tokens import CONTEXT_WINDOW_TOKENS, compute_token_breakdown, fmt_tokens

if TYPE_CHECKING:
    from ..main_window import MainWindow


class ProfileWizardDialog(QDialog):
    """Build, name, save, and apply a custom profile by selecting task and advantage tags."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.main_win = parent
        self.lang = parent.lang
        self.workspace_tools: list[ToolSpec] = [
            t for t in parent.tools if getattr(t, "in_workspace", True)
        ]
        self.missing_keys: set[str] = parent._missing_required_vault_keys()

        self.selected_tags: list[str] = []
        self.checked_tool_ids: set[str] = set()
        self.manual_overrides: dict[str, bool] = {}
        self.name_touched: bool = False

        self.result_name: str = ""
        self.result_tool_ids: set[str] = set()
        self.result_skills: set[str] = set(parent.active_skills)
        self.result_tags: list[str] = []

        self.setWindowTitle(tr(self.lang, "wiz_title"))
        self.setMinimumSize(780, 580)
        self.resize(850, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        # 1. TAG SELECTION CARD
        tags_card = QFrame()
        tags_card.setObjectName("card")
        tc_lay = QVBoxLayout(tags_card)
        tc_lay.setContentsMargins(12, 10, 12, 10)
        tc_lay.setSpacing(8)

        adv_row = QHBoxLayout()
        adv_row.setSpacing(8)
        adv_row.addWidget(QLabel(f"<b>{tr(self.lang, 'wiz_adv_lbl')}</b>"))

        self.tag_buttons: dict[str, QPushButton] = {}
        tag_counts = {
            tid: sum(1 for t in self.workspace_tools if tid in t.tags)
            for tid in (BENEFIT_TAG_IDS + DOMAIN_TAG_IDS)
        }

        for tid in BENEFIT_TAG_IDS:
            cnt = tag_counts[tid]
            lbl = f"{tag_label(tid, self.lang)} ({cnt})" if cnt else tag_label(tid, self.lang)
            btn = QPushButton(lbl.replace("&", "&&"))
            btn.setObjectName("wizBenefitChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, tag_code=tid: self._on_tag_clicked(tag_code, checked))
            self.tag_buttons[tid] = btn
            adv_row.addWidget(btn)
        adv_row.addStretch()
        tc_lay.addLayout(adv_row)

        tc_lay.addWidget(QLabel(f"<b>{tr(self.lang, 'wiz_task_lbl')}</b>"))

        dom_grid = QGridLayout()
        dom_grid.setSpacing(6)
        cols = 4
        for idx, tid in enumerate(DOMAIN_TAG_IDS):
            cnt = tag_counts[tid]
            lbl = f"{tag_label(tid, self.lang)} ({cnt})" if cnt else tag_label(tid, self.lang)
            btn = QPushButton(lbl.replace("&", "&&"))
            btn.setObjectName("wizDomainChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if cnt == 0:
                btn.setToolTip(tr(self.lang, "wiz_tag_empty_tip"))
            btn.clicked.connect(lambda checked, tag_code=tid: self._on_tag_clicked(tag_code, checked))
            self.tag_buttons[tid] = btn
            dom_grid.addWidget(btn, idx // cols, idx % cols)
        tc_lay.addLayout(dom_grid)
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

        self._rebuild_tools_list()

    def _on_name_edited(self, _txt: str) -> None:
        self.name_touched = bool(self.name_inp.text().strip())

    def _effective_blender_skills(self) -> set[str]:
        sel_set = set(self.selected_tags)
        if sel_set & {"modeling_3d", "style_3d", "unity", "shader_gpu"}:
            return recommended_blender_skills_for_tags(sel_set)
        return set(self.main_win.active_skills)

    def _is_auto_selectable(self, t: ToolSpec) -> bool:
        if not any(t.clients.values()):
            return False
        if t.vault_key_required and t.vault_key_name and t.vault_key_name in self.missing_keys:
            return False
        return True

    def _sync_auto_checked_from_tags(self) -> None:
        sel_set = set(self.selected_tags)
        new_checked: set[str] = set()
        for t in self.workspace_tools:
            if t.id in self.manual_overrides:
                if self.manual_overrides[t.id]:
                    new_checked.add(t.id)
                continue
            if sel_set and (sel_set & set(t.tags)) and self._is_auto_selectable(t):
                new_checked.add(t.id)
        self.checked_tool_ids = new_checked

        if not self.name_touched:
            dom_chosen = [tid for tid in self.selected_tags if not is_benefit_tag(tid)]
            ben_chosen = [tid for tid in self.selected_tags if is_benefit_tag(tid)]
            basis = dom_chosen[:2] if dom_chosen else ben_chosen[:2]
            auto_nm = " + ".join(tag_label(tid, self.lang) for tid in basis)
            self.name_inp.setText(auto_nm)

    def _on_tag_clicked(self, tag_code: str, checked: bool) -> None:
        if checked:
            if tag_code not in self.selected_tags:
                self.selected_tags.append(tag_code)
        else:
            if tag_code in self.selected_tags:
                self.selected_tags.remove(tag_code)
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
        self._rebuild_tools_list()

    def _estimate_budget(self) -> tuple[int, float]:
        sim_tools = copy.deepcopy(self.workspace_tools)
        for t in sim_tools:
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
        )
        pct = bd.active_tokens / CONTEXT_WINDOW_TOKENS * 100.0
        return bd.active_tokens, pct

    def _update_header_and_budget(self) -> None:
        sel_set = set(self.selected_tags)
        match_cnt = (
            sum(1 for t in self.workspace_tools if sel_set & set(t.tags))
            if sel_set
            else len(self.workspace_tools)
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

        if sel_set and not self.show_all_cb.isChecked():
            shown_tools = [
                t for t in self.workspace_tools if (sel_set & set(t.tags)) or (t.id in self.checked_tool_ids)
            ]
        else:
            shown_tools = list(self.workspace_tools)

        shown_tools.sort(
            key=lambda t: (
                0 if t.id in self.checked_tool_ids else 1,
                -len(sel_set & set(t.tags)),
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

                for tg in t.tags:
                    t_pill = QLabel(tag_label(tg, self.lang))
                    t_pill.setObjectName("tagBenefitPill" if is_benefit_tag(tg) else "tagDomainPill")
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

                has_missing = bool(
                    t.vault_key_required and t.vault_key_name and t.vault_key_name in self.missing_keys
                )
                if has_missing:
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
