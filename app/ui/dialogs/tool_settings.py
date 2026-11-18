"""Per-tool technical settings dialog with option help and AI advisor."""
from __future__ import annotations

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
from ...catalog import ToolSpec
from ...storage import LogDatabase, WindowsDpapiVault
from ..widgets import create_option_help_badge
from .ai_paste import AiPasteDialog


class ToolGearDialog(QDialog):
    """Configure a tool's parameter, options, and AI-assisted recommendations."""

    def __init__(
        self,
        parent: QWidget,
        tool: ToolSpec,
        vault: WindowsDpapiVault,
        logs: LogDatabase,
        scope_display: str,
    ) -> None:
        super().__init__(parent)
        self.tool = tool
        self.vault = vault
        self.logs = logs
        self.scope_display = scope_display
        self.setWindowTitle(f"⚙️ {tool.name} — Teknik Ayarlar")
        self.setMinimumWidth(680)
        self.resize(700, 560)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        loc_card = QFrame()
        loc_card.setObjectName("card")
        loc_lay = QVBoxLayout(loc_card)
        loc_lay.addWidget(QLabel(f"<b>📁 Proje / Kapsam:</b> {scope_display}"))
        if tool.live_location_detail:
            det = QLabel(f"<span style='color:#94a3b8;'>{tool.live_location_detail}</span>")
            det.setWordWrap(True)
            loc_lay.addWidget(det)
        lay.addWidget(loc_card)

        self.opt_help_card = QFrame()
        self.opt_help_card.setObjectName("card")
        self.opt_help_card.setStyleSheet("QFrame#card { border: 1px solid #2563eb; background-color: #132038; }")
        oh_lay = QVBoxLayout(self.opt_help_card)
        oh_lay.setContentsMargins(12, 8, 12, 8)
        oh_lay.setSpacing(4)
        self.opt_help_title = QLabel("<b>ℹ️ Özellik Rehberi (Açarsan / Kapatırsan Ne Olur?)</b>")
        self.opt_help_body = QLabel("")
        self.opt_help_body.setWordWrap(True)
        self.opt_help_body.setStyleSheet("color: #dbeafe; font-size: 12px;")
        oh_lay.addWidget(self.opt_help_title)
        oh_lay.addWidget(self.opt_help_body)

        if tool.param_label:
            p_card = QFrame()
            p_card.setObjectName("card")
            p_lay = QVBoxLayout(p_card)
            p_hdr = QHBoxLayout()
            p_hdr.setSpacing(6)
            p_hdr.addWidget(QLabel(f"<b>{tool.param_label}</b>"))
            p_help = tool.param_help or f"{tool.param_label} değerini projeye göre özelleştirmenizi sağlar."
            p_hdr.addWidget(
                create_option_help_badge(
                    f"❓ {tool.param_label}\n{p_help}",
                    lambda lbl=tool.param_label, h=p_help: self._show_option_help(lbl, h),
                )
            )
            p_hdr.addStretch()
            p_lay.addLayout(p_hdr)
            self.param_inp = QLineEdit(tool.param_value)
            self.param_inp.setToolTip(p_help)
            p_lay.addWidget(self.param_inp)
            lay.addWidget(p_card)
        else:
            self.param_inp = None

        if tool.vault_key_name:
            v_card = QFrame()
            v_card.setObjectName("card")
            v_lay = QHBoxLayout(v_card)
            has_k = vault.has_secret(tool.vault_key_name)
            status_txt = "Tanımlı (Windows DPAPI ile Şifreli)" if has_k else "Henüz Girilmedi (Şifreli Kasa sekmesinden ekleyin)"
            v_lay.addWidget(QLabel(f"🔐 <b>{tool.vault_key_name}:</b> {status_txt}"))
            lay.addWidget(v_card)

        self.opt_checks: dict[str, QCheckBox] = {}
        if tool.options:
            opt_card = QFrame()
            opt_card.setObjectName("card")
            opt_lay = QVBoxLayout(opt_card)
            opt_lay.setSpacing(6)
            opt_lay.addWidget(
                QLabel(
                    "<b>Özellikler & Çalışma İzinleri</b>  "
                    "<span style='color:#94a3b8; font-size:11px;'>(Yanındaki <b>?</b> butonuna tıklayarak veya üzerine gelerek ne işe yaradığını okuyun)</span>"
                )
            )
            for opt in tool.options:
                row_w = QWidget()
                row_w.setObjectName("cellBox")
                r_lay = QHBoxLayout(row_w)
                r_lay.setContentsMargins(2, 2, 2, 2)
                r_lay.setSpacing(8)

                h_txt = (
                    opt.help_text
                    or "✅ AÇARSAN: Bu alt özelliği etkinleştirir.\n⛔ KAPATIRSAN: Bu alt özellik devre dışı kalır."
                )
                cb = QCheckBox(opt.label)
                cb.setChecked(opt.enabled)
                cb.setCursor(Qt.CursorShape.PointingHandCursor)
                cb.setToolTip(f"❓ {opt.label}\n\n{h_txt}")
                cb.installEventFilter(self)
                cb.setProperty("opt_title", opt.label)
                cb.setProperty("opt_help", h_txt)
                self.opt_checks[opt.key] = cb
                r_lay.addWidget(cb)

                info_btn = create_option_help_badge(
                    f"❓ {opt.label}\n\n{h_txt}",
                    lambda lbl=opt.label, h=h_txt: self._show_option_help(lbl, h),
                )
                r_lay.addWidget(info_btn)
                r_lay.addStretch()
                opt_lay.addWidget(row_w)
            lay.addWidget(opt_card)

        lay.addWidget(self.opt_help_card)

        if tool.options:
            first = tool.options[0]
            self._show_option_help(
                first.label,
                first.help_text or "✅ AÇARSAN: Bu alt özelliği etkinleştirir.\n⛔ KAPATIRSAN: Devre dışı bırakır.",
            )
        elif tool.param_label:
            self._show_option_help(
                tool.param_label,
                tool.param_help or f"{tool.param_label} değerini yapılandırır.",
            )
        else:
            self.opt_help_card.hide()

        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setFixedHeight(95)
        self.prompt_preview.hide()
        lay.addWidget(self.prompt_preview)

        lay.addStretch()

        bot = QHBoxLayout()
        btn_ask = QPushButton("🤖 AI'a Danış (Prompt Kopyala)")
        btn_paste = QPushButton("📥 AI Yanıtını Yapıştır && Uygula")
        btn_cancel = QPushButton("Vazgeç")
        btn_save = QPushButton("💾 Kaydet")
        btn_save.setObjectName("successBtn")

        btn_ask.clicked.connect(self._copy_prompt)
        btn_paste.clicked.connect(self._paste_response)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)

        for b in (btn_ask, btn_paste):
            bot.addWidget(b)
        bot.addStretch()
        bot.addWidget(btn_cancel)
        bot.addWidget(btn_save)
        lay.addLayout(bot)

    def _show_option_help(self, title: str, help_body: str) -> None:
        self.opt_help_title.setText(f"<b>ℹ️ {title}</b>")
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
        prompt = build_tool_ai_prompt(self.tool, cur_param, opt_states, has_key, issue, self.scope_display)
        QApplication.clipboard().setText(prompt)
        self.prompt_preview.setPlainText(prompt)
        self.prompt_preview.show()

    def _paste_response(self) -> None:
        dlg = AiPasteDialog(self, f"📥 {self.tool.name} — AI Yanıtını Uygula")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            matched, msg = parse_tool_ai_response(self.tool, dlg.editor.toPlainText())
            if matched or "kapalı" in msg:
                for k, cb in self.opt_checks.items():
                    cb.setChecked(k in matched)
                QMessageBox.information(
                    self,
                    "AI Önerisi Uygulandı",
                    f"{msg}.\nKaydet butonuna basarak kalıcı hale getirebilirsiniz.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Eşleşme Yok",
                    "Metinde geçerli bir seçenek anahtarı veya <<<ACIK: ...>>> satırı bulunamadı.",
                )

    def _save(self) -> None:
        if self.param_inp is not None:
            self.tool.param_value = self.param_inp.text().strip()
        for opt in self.tool.options:
            opt.enabled = self.opt_checks[opt.key].isChecked()
        self.accept()
