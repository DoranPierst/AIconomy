"""Tool details summary dialog (emoji-free, EN & TR)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ...catalog import ToolSpec, localized_tool_text, tag_label, tool_kind_label
from ...i18n import tr
from ..theme import tag_pill_qss

if TYPE_CHECKING:
    from ..main_window import MainWindow


class ToolInfoDialog(QDialog):
    """Explain what a tool does, when to enable/disable it, and its technical requirements."""

    def __init__(self, parent: "MainWindow", tool: ToolSpec) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.tool = tool
        lang = parent.lang
        self.setWindowTitle(tr(lang, "info_title", name=tool.name))
        self.setMinimumWidth(580)
        self.resize(610, 460)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        hdr_row = QHBoxLayout()
        title_lbl = QLabel(f"<span style='font-size:15px; font-weight:700;'>{tool.name}</span>")
        hdr_row.addWidget(title_lbl)
        ver_str = f"v{tool.version.strip().lstrip('vV')}"
        kind_lbl = tool_kind_label(tool.kind, lang)
        badge_lbl = QLabel(f"  <span style='color:#60a5fa; font-weight:600;'>{kind_lbl} · {ver_str}</span>")
        hdr_row.addWidget(badge_lbl)
        hdr_row.addStretch()
        lay.addLayout(hdr_row)

        if tool.tags:
            is_light = parent.meta.get("theme", "dark") == "light"
            cur_tab = parent.tabs.currentIndex() if hasattr(parent, "tabs") else 0
            if cur_tab == 1 and hasattr(parent, "plug_tag_cmb"):
                flt_tag = str(parent.plug_tag_cmb.currentData() or "ALL")
                hi_tags = {flt_tag} if flt_tag != "ALL" else set()
            else:
                flt_tag = str(parent.tag_cmb.currentData() or "ALL") if hasattr(parent, "tag_cmb") else "ALL"
                if flt_tag != "ALL":
                    hi_tags = {flt_tag}
                elif tool.enabled and hasattr(parent, "get_active_profile_tags"):
                    hi_tags = parent.get_active_profile_tags()
                else:
                    hi_tags = set()
            tags_row = QHBoxLayout()
            tags_row.setSpacing(6)
            for tg in tool.tags:
                pill = QLabel(tag_label(tg, lang))
                pill.setFixedHeight(18)
                pill.setStyleSheet(tag_pill_qss(tg, is_highlighted=(tg in hi_tags), is_light=is_light))
                tags_row.addWidget(pill)
            tags_row.addStretch()
            lay.addLayout(tags_row)

        what_card = QFrame()
        what_card.setObjectName("card")
        w_lay = QVBoxLayout(what_card)
        w_lay.setSpacing(6)
        w_lay.addWidget(QLabel(f"<b>{tr(lang, 'info_what')}</b>"))
        sum_txt = localized_tool_text(tool, "summary", lang)
        det_txt = localized_tool_text(tool, "details", lang)
        full_what = f"{sum_txt}\n\n{det_txt}".strip() if det_txt else sum_txt
        what_lbl = QLabel(full_what)
        what_lbl.setWordWrap(True)
        w_lay.addWidget(what_lbl)
        lay.addWidget(what_card)

        when_txt = localized_tool_text(tool, "when_to_use", lang)
        if when_txt:
            when_card = QFrame()
            when_card.setObjectName("card")
            wh_lay = QVBoxLayout(when_card)
            wh_lay.addWidget(QLabel(f"<b>{tr(lang, 'info_when')}</b>"))
            when_lbl = QLabel(when_txt)
            when_lbl.setWordWrap(True)
            wh_lay.addWidget(when_lbl)
            lay.addWidget(when_card)

        tech_card = QFrame()
        tech_card.setObjectName("card")
        t_lay = QVBoxLayout(tech_card)
        t_lay.setSpacing(5)
        t_lay.addWidget(QLabel(f"<b>{tr(lang, 'info_tech')}</b>"))

        if tool.id == "blender_skills":
            tok_info = tr(lang, "info_tok_skills")
        else:
            tok_info = tr(lang, "info_tok_std", tok=tool.schema_tokens)

        if tool.vault_key_name and tool.vault_key_required:
            key_info = tr(lang, "info_key_req", key=tool.vault_key_name)
        elif tool.vault_key_name:
            key_info = tr(lang, "info_key_opt", key=tool.vault_key_name)
        else:
            key_info = tr(lang, "info_key_none")
        t_lay.addWidget(QLabel(f"<b>{tr(lang, 'info_ctx_load')}</b> {tok_info}"))
        t_lay.addWidget(QLabel(f"<b>{tr(lang, 'info_key_lbl')}</b> {key_info}"))
        if tool.install_cmd:
            t_lay.addWidget(QLabel(f"<b>{tr(lang, 'info_cmd_lbl')}</b> <code>{tool.install_cmd}</code>"))
        if tool.repo_url:
            link_lbl = QLabel(
                f"<b>{tr(lang, 'info_src_lbl')}</b> <a style='color:#60a5fa;' href='{tool.repo_url}'>{tool.repo_url}</a>"
            )
            link_lbl.setOpenExternalLinks(True)
            t_lay.addWidget(link_lbl)
        lay.addWidget(tech_card)

        lay.addStretch()
        bot = QHBoxLayout()
        if tool.has_gear:
            btn_gear = QPushButton(tr(lang, "info_open_settings"))
            btn_gear.clicked.connect(lambda: (self.accept(), self.main_win.open_gear(tool)))
            bot.addWidget(btn_gear)
        bot.addStretch()
        btn_ok = QPushButton(tr(lang, "btn_ok"))
        btn_ok.setObjectName("primaryBtn")
        btn_ok.clicked.connect(self.accept)
        bot.addWidget(btn_ok)
        lay.addLayout(bot)
        self.adjustSize()
