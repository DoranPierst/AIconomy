"""94-skill Blender selector dialog (emoji-free, EN & TR)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...ai_advisor import build_skills_ai_prompt, parse_skills_ai_response
from ...catalog import BLENDER_SKILLS_94, describe_blender_skill
from ...i18n import tr
from ..widgets import create_option_help_badge
from .ai_paste import AiPasteDialog


class BlenderSkillsDialog(QDialog):
    """Multi-select manager for the 94 Blender specialist skills."""

    def __init__(
        self,
        parent: QWidget,
        active_skills: set[str],
        checked_skills: set[str] | None = None,
        lang: str = "en",
    ) -> None:
        super().__init__(parent)
        self.lang = lang
        self.setWindowTitle(tr(lang, "skills_title"))
        self.resize(920, 650)
        self.draft_active: set[str] = set(active_skills)
        self.checked_items: set[str] = set(checked_skills or set())
        self.saved_result: set[str] | None = None
        self.saved_checked: set[str] = set()

        root = QVBoxLayout(self)
        root.setSpacing(8)

        top_bar = QHBoxLayout()
        self.btn_all_on = QPushButton(tr(lang, "skills_all_on"))
        self.btn_all_off = QPushButton(tr(lang, "skills_all_off"))
        self.btn_sel_on = QPushButton(tr(lang, "skills_sel_on", n=0))
        self.btn_sel_on.setObjectName("primaryBtn")
        self.btn_sel_off = QPushButton(tr(lang, "skills_sel_off", n=0))
        self.btn_clear_sel = QPushButton(tr(lang, "skills_clear_sel"))

        self.btn_all_on.clicked.connect(self._enable_all)
        self.btn_all_off.clicked.connect(self._disable_all)
        self.btn_sel_on.clicked.connect(self._enable_selected)
        self.btn_sel_off.clicked.connect(self._disable_selected)
        self.btn_clear_sel.clicked.connect(self._clear_selection)

        for b in (self.btn_all_on, self.btn_all_off, self.btn_sel_on, self.btn_sel_off, self.btn_clear_sel):
            top_bar.addWidget(b)

        top_bar.addStretch()
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText(tr(lang, "skills_search_ph"))
        self.search_inp.setFixedWidth(220)
        self.search_inp.textChanged.connect(self._rebuild_grid)

        self.filter_cmb = QComboBox()
        self.filter_cmb.addItems(
            [
                tr(lang, "skills_flt_all"),
                tr(lang, "skills_flt_on"),
                tr(lang, "skills_flt_off"),
                tr(lang, "skills_flt_sel"),
            ]
        )
        self.filter_cmb.currentIndexChanged.connect(self._rebuild_grid)

        top_bar.addWidget(self.search_inp)
        top_bar.addWidget(self.filter_cmb)
        root.addLayout(top_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid_layout = QGridLayout(self.grid_host)
        self.grid_layout.setSpacing(6)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, stretch=1)

        self.skill_help_card = QFrame()
        self.skill_help_card.setObjectName("bannerInfo")
        sh_lay = QVBoxLayout(self.skill_help_card)
        sh_lay.setContentsMargins(10, 6, 10, 6)
        sh_lay.setSpacing(3)
        self.skill_help_title = QLabel(
            f"<b>{tr(lang, 'skills_guide_hdr')}:</b> <span style='color:#93c5fd;'>{tr(lang, 'skills_guide_hint')}</span>"
        )
        self.skill_help_body = QLabel(describe_blender_skill("blender-director", lang))
        self.skill_help_body.setWordWrap(True)
        self.skill_help_body.setStyleSheet("font-size: 11px;")
        sh_lay.addWidget(self.skill_help_title)
        sh_lay.addWidget(self.skill_help_body)
        root.addWidget(self.skill_help_card)

        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setFixedHeight(95)
        self.prompt_preview.hide()
        root.addWidget(self.prompt_preview)

        bot = QHBoxLayout()
        self.summary_lbl = QLabel()
        bot.addWidget(self.summary_lbl)
        bot.addStretch()

        self.btn_ask_ai = QPushButton(tr(lang, "gear_ask_ai"))
        self.btn_paste_ai = QPushButton(tr(lang, "gear_paste_ai"))
        self.btn_cancel = QPushButton(tr(lang, "btn_cancel"))
        self.btn_save = QPushButton(tr(lang, "btn_save"))
        self.btn_save.setObjectName("primaryBtn")

        self.btn_ask_ai.clicked.connect(self._copy_ai_prompt)
        self.btn_paste_ai.clicked.connect(self._paste_ai_response)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._save_and_close)

        for b in (self.btn_ask_ai, self.btn_paste_ai, self.btn_cancel, self.btn_save):
            bot.addWidget(b)
        root.addLayout(bot)

        self._rebuild_grid()

    def _show_skill_help(self, skill_name: str) -> None:
        self.skill_help_title.setText(f"<b>{skill_name}</b>")
        self.skill_help_body.setText(describe_blender_skill(skill_name, self.lang))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Enter:
            sk_nm = watched.property("skill_name")
            if sk_nm:
                self._show_skill_help(str(sk_nm))
        return super().eventFilter(watched, event)

    def _rebuild_grid(self) -> None:
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        q = self.search_inp.text().strip().lower()
        f_idx = self.filter_cmb.currentIndex()

        filtered: list[str] = []
        for sk in BLENDER_SKILLS_94:
            if q and q not in sk:
                continue
            if f_idx == 1 and sk not in self.draft_active:
                continue
            if f_idx == 2 and sk in self.draft_active:
                continue
            if f_idx == 3 and sk not in self.checked_items:
                continue
            filtered.append(sk)

        cols = 3
        on_txt = tr(self.lang, "skills_badge_on")
        off_txt = tr(self.lang, "skills_badge_off")
        for idx, sk in enumerate(filtered):
            card = QFrame()
            card.setObjectName("card")
            row_lay = QHBoxLayout(card)
            row_lay.setContentsMargins(8, 4, 8, 4)
            row_lay.setSpacing(5)

            desc_txt = describe_blender_skill(sk, self.lang)
            cb = QCheckBox(sk)
            cb.setChecked(sk in self.checked_items)
            cb.setToolTip(f"{sk}\n{desc_txt}")
            cb.setProperty("skill_name", sk)
            cb.installEventFilter(self)
            cb.toggled.connect(lambda checked, name=sk: self._on_check_toggled(name, checked))
            row_lay.addWidget(cb, stretch=1)

            q_btn = create_option_help_badge(
                f"{sk}\n{desc_txt}",
                lambda name=sk: self._show_skill_help(name),
                size=18,
            )
            row_lay.addWidget(q_btn)

            is_on = sk in self.draft_active
            badge = QLabel(on_txt if is_on else off_txt)
            badge.setStyleSheet(
                "color: #22c55e; font-weight: 700; font-size: 10px;"
                if is_on
                else "color: #64748b; font-size: 10px;"
            )
            row_lay.addWidget(badge)
            self.grid_layout.addWidget(card, idx // cols, idx % cols)

        self.grid_layout.setRowStretch((len(filtered) // cols) + 1, 1)
        self._update_counters()

    def _on_check_toggled(self, name: str, checked: bool) -> None:
        if checked:
            self.checked_items.add(name)
        else:
            self.checked_items.discard(name)
        self._update_counters()

    def _update_counters(self) -> None:
        sel_n = len(self.checked_items)
        on_n = len(self.draft_active)
        off_n = len(BLENDER_SKILLS_94) - on_n
        saved_tok = round(off_n * 0.35, 1)
        self.btn_sel_on.setText(tr(self.lang, "skills_sel_on", n=sel_n))
        self.btn_sel_off.setText(tr(self.lang, "skills_sel_off", n=sel_n))
        self.btn_sel_on.setEnabled(sel_n > 0)
        self.btn_sel_off.setEnabled(sel_n > 0)
        self.summary_lbl.setText(
            tr(self.lang, "skills_summary", on=on_n, off=off_n, sel=sel_n, sav=saved_tok)
        )

    def _enable_all(self) -> None:
        self.draft_active = set(BLENDER_SKILLS_94)
        self._rebuild_grid()

    def _disable_all(self) -> None:
        self.draft_active.clear()
        self._rebuild_grid()

    def _enable_selected(self) -> None:
        self.draft_active.update(self.checked_items)
        self._rebuild_grid()

    def _disable_selected(self) -> None:
        self.draft_active.difference_update(self.checked_items)
        self._rebuild_grid()

    def _clear_selection(self) -> None:
        self.checked_items.clear()
        self._rebuild_grid()

    def _copy_ai_prompt(self) -> None:
        prompt = build_skills_ai_prompt(self.draft_active, self.checked_items, lang=self.lang)
        QApplication.clipboard().setText(prompt)
        self.prompt_preview.setPlainText(prompt)
        self.prompt_preview.show()

    def _paste_ai_response(self) -> None:
        dlg = AiPasteDialog(self, tr(self.lang, "skills_paste_title"), lang=self.lang)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            matched, msg = parse_skills_ai_response(dlg.editor.toPlainText(), lang=self.lang)
            if matched or "none" in msg.lower() or "kapalı" in msg.lower():
                self.draft_active = set(matched)
                self.checked_items = set(matched)
                self._rebuild_grid()
                QMessageBox.information(
                    self,
                    tr(self.lang, "gear_ai_applied_title"),
                    tr(self.lang, "skills_ai_applied_msg", msg=msg, n=len(self.draft_active)),
                )
            else:
                QMessageBox.warning(
                    self,
                    tr(self.lang, "gear_ai_nomatch_title"),
                    tr(self.lang, "skills_ai_nomatch_msg"),
                )

    def _save_and_close(self) -> None:
        self.saved_result = set(self.draft_active)
        self.saved_checked = set(self.checked_items)
        self.accept()
