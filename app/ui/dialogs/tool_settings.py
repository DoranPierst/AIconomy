"""Per-tool technical settings dialog with direct API key shortcut and AI advisor."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...ai_advisor import build_tool_ai_prompt, parse_tool_ai_response
from ...catalog import ToolSpec, localized_option_text, localized_tool_text
from ...i18n import tr
from ..widgets import create_option_help_badge
from .ai_paste import AiPasteDialog

if TYPE_CHECKING:
    from ..main_window import MainWindow


class ToolGearDialog(QDialog):
    """Configure a tool's parameter, options, API key shortcut, and AI recommendations."""

    def __init__(
        self,
        parent: "MainWindow",
        tool: ToolSpec,
        scope_display: str,
    ) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.tool = tool
        self.vault = parent.vault
        self.logs = parent.logs
        self.lang = parent.lang
        self.scope_display = scope_display
        self.setWindowTitle(tr(self.lang, "gear_title", name=tool.name))
        self.setMinimumWidth(640)
        self.resize(680, 540)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        loc_card = QFrame()
        loc_card.setObjectName("card")
        loc_lay = QVBoxLayout(loc_card)
        loc_lay.setContentsMargins(12, 8, 12, 8)
        loc_lay.addWidget(QLabel(f"<b>{tr(self.lang, 'gear_scope_lbl')}</b> {scope_display}"))
        if tool.live_location_detail:
            det = QLabel(f"<span style='color:#94a3b8; font-size:11px;'>{tool.live_location_detail}</span>")
            det.setWordWrap(True)
            loc_lay.addWidget(det)
        lay.addWidget(loc_card)

        self.opt_help_card = QFrame()
        self.opt_help_card.setObjectName("bannerInfo")
        oh_lay = QVBoxLayout(self.opt_help_card)
        oh_lay.setContentsMargins(12, 8, 12, 8)
        oh_lay.setSpacing(4)
        self.opt_help_title = QLabel(f"<b>{tr(self.lang, 'gear_help_hdr')}</b>")
        self.opt_help_body = QLabel("")
        self.opt_help_body.setWordWrap(True)
        self.opt_help_body.setStyleSheet("font-size: 11px;")
        oh_lay.addWidget(self.opt_help_title)
        oh_lay.addWidget(self.opt_help_body)

        param_lbl = localized_tool_text(tool, "param_label", self.lang)
        param_help = localized_tool_text(tool, "param_help", self.lang)
        if param_lbl:
            p_card = QFrame()
            p_card.setObjectName("card")
            p_lay = QVBoxLayout(p_card)
            p_lay.setContentsMargins(12, 8, 12, 8)
            p_hdr = QHBoxLayout()
            p_hdr.setSpacing(6)
            p_hdr.addWidget(QLabel(f"<b>{param_lbl}</b>"))
            if param_help:
                p_hdr.addWidget(
                    create_option_help_badge(
                        param_help,
                        lambda lbl=param_lbl, h=param_help: self._show_option_help(lbl, h),
                    )
                )
            p_hdr.addStretch()
            p_lay.addLayout(p_hdr)
            self.param_inp = QLineEdit(tool.param_value)
            if param_help:
                self.param_inp.setToolTip(param_help)
            p_lay.addWidget(self.param_inp)
            lay.addWidget(p_card)
        else:
            self.param_inp = None

        self._key_status_lbl: QLabel | None = None
        if tool.vault_key_name:
            v_card = QFrame()
            v_card.setObjectName("card")
            v_lay = QHBoxLayout(v_card)
            v_lay.setContentsMargins(12, 8, 12, 8)
            self._key_status_lbl = QLabel()
            v_lay.addWidget(self._key_status_lbl, stretch=1)
            btn_set_key = QPushButton(tr(self.lang, "gear_set_key_btn"))
            btn_set_key.clicked.connect(self._open_api_keys)
            v_lay.addWidget(btn_set_key)
            lay.addWidget(v_card)
            self._refresh_key_status()

        self.opt_checks: dict[str, QCheckBox] = {}
        if tool.options:
            opt_card = QFrame()
            opt_card.setObjectName("card")
            opt_lay = QVBoxLayout(opt_card)
            opt_lay.setContentsMargins(12, 10, 12, 10)
            opt_lay.setSpacing(6)
            opt_lay.addWidget(
                QLabel(
                    f"<b>{tr(self.lang, 'gear_opts_hdr')}</b>  "
                    f"<span style='color:#94a3b8; font-size:11px;'>({tr(self.lang, 'gear_opts_hint')})</span>"
                )
            )
            for opt in tool.options:
                o_lbl, o_help = localized_option_text(tool.id, opt, self.lang)
                row_w = QWidget()
                row_w.setObjectName("cellBox")
                r_lay = QHBoxLayout(row_w)
                r_lay.setContentsMargins(2, 2, 2, 2)
                r_lay.setSpacing(8)

                cb = QCheckBox(o_lbl)
                cb.setChecked(opt.enabled)
                cb.setCursor(Qt.CursorShape.PointingHandCursor)
                if o_help:
                    cb.setToolTip(o_help)
                cb.installEventFilter(self)
                cb.setProperty("opt_title", o_lbl)
                cb.setProperty("opt_help", o_help)
                self.opt_checks[opt.key] = cb
                r_lay.addWidget(cb)

                if o_help:
                    info_btn = create_option_help_badge(
                        o_help,
                        lambda lbl=o_lbl, h=o_help: self._show_option_help(lbl, h),
                    )
                    r_lay.addWidget(info_btn)
                r_lay.addStretch()
                opt_lay.addWidget(row_w)
            lay.addWidget(opt_card)

        lay.addWidget(self.opt_help_card)

        if tool.options:
            first_lbl, first_help = localized_option_text(tool.id, tool.options[0], self.lang)
            self._show_option_help(first_lbl, first_help)
        elif param_lbl and param_help:
            self._show_option_help(param_lbl, param_help)
        else:
            self.opt_help_card.hide()

        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setFixedHeight(90)
        self.prompt_preview.hide()
        lay.addWidget(self.prompt_preview)

        lay.addStretch()

        bot = QHBoxLayout()
        btn_ask = QPushButton(tr(self.lang, "gear_ask_ai"))
        btn_paste = QPushButton(tr(self.lang, "gear_paste_ai"))
        btn_cancel = QPushButton(tr(self.lang, "btn_cancel"))
        btn_save = QPushButton(tr(self.lang, "btn_save"))
        btn_save.setObjectName("primaryBtn")

        btn_ask.clicked.connect(self._copy_prompt)
        btn_paste.clicked.connect(self._paste_response)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)

        bot.addWidget(btn_ask)
        bot.addWidget(btn_paste)
        bot.addStretch()
        bot.addWidget(btn_cancel)
        bot.addWidget(btn_save)
        lay.addLayout(bot)

    def _refresh_key_status(self) -> None:
        if self._key_status_lbl is None:
            return
        has_k = self.vault.has_secret(self.tool.vault_key_name)
        status_txt = tr(self.lang, "gear_key_set" if has_k else "gear_key_missing")
        col = "#22c55e" if has_k else "#f59e0b"
        self._key_status_lbl.setText(
            f"<b>{self.tool.vault_key_name}:</b> <span style='color:{col}; font-weight:600;'>{status_txt}</span>"
        )

    def _open_api_keys(self) -> None:
        self.main_win.open_settings(initial_tab=1)
        self._refresh_key_status()

    def _show_option_help(self, title: str, help_body: str) -> None:
        if not help_body:
            return
        self.opt_help_title.setText(f"<b>{title}</b>")
        self.opt_help_body.setText(help_body)
        self.opt_help_card.show()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Enter:
            t = watched.property("opt_title")
            h = watched.property("opt_help")
            if t and h:
                self._show_option_help(str(t), str(h))
        return super().eventFilter(watched, event)

    def _copy_prompt(self) -> None:
        cur_param = self.param_inp.text().strip() if self.param_inp else ""
        opt_states = {k: cb.isChecked() for k, cb in self.opt_checks.items()}
        has_key = self.vault.has_secret(self.tool.vault_key_name) if self.tool.vault_key_name else False
        issue = self.logs.latest_issue_for_tool(self.tool.name)
        prompt = build_tool_ai_prompt(
            self.tool, cur_param, opt_states, has_key, issue, self.scope_display, lang=self.lang
        )
        QApplication.clipboard().setText(prompt)
        self.prompt_preview.setPlainText(prompt)
        self.prompt_preview.show()

    def _paste_response(self) -> None:
        dlg = AiPasteDialog(self, f"{self.tool.name} — {tr(self.lang, 'gear_paste_ai')}", lang=self.lang)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            matched, msg = parse_tool_ai_response(self.tool, dlg.editor.toPlainText(), lang=self.lang)
            if matched or "none" in msg.lower() or "kapalı" in msg.lower():
                for k, cb in self.opt_checks.items():
                    cb.setChecked(k in matched)
                QMessageBox.information(
                    self,
                    tr(self.lang, "gear_ai_applied_title"),
                    tr(self.lang, "gear_ai_applied_msg", msg=msg),
                )
            else:
                QMessageBox.warning(
                    self,
                    tr(self.lang, "gear_ai_nomatch_title"),
                    tr(self.lang, "gear_ai_nomatch_msg"),
                )

    def _save(self) -> None:
        if self.param_inp is not None:
            self.tool.param_value = self.param_inp.text().strip()
        for opt in self.tool.options:
            opt.enabled = self.opt_checks[opt.key].isChecked()
        self.accept()
