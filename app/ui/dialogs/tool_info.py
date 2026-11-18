"""Tool information summary dialog."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ...catalog import ToolSpec

if TYPE_CHECKING:
    from ..main_window import MainWindow


class ToolInfoDialog(QDialog):
    """Explain what a tool does, when to enable/disable it, and its technical requirements."""

    def __init__(self, parent: "MainWindow", tool: ToolSpec) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.tool = tool
        self.setWindowTitle(f"❓ {tool.name} — Ne İşe Yarar?")
        self.setMinimumWidth(620)
        self.resize(640, 500)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        hdr_row = QHBoxLayout()
        title_lbl = QLabel(f"<span style='font-size:15px; font-weight:700;'>{tool.name}</span>")
        hdr_row.addWidget(title_lbl)
        badge_lbl = QLabel(f"  <span style='color:#60a5fa; font-weight:600;'>[{tool.kind} · {tool.version}]</span>")
        hdr_row.addWidget(badge_lbl)
        hdr_row.addStretch()
        lay.addLayout(hdr_row)

        what_card = QFrame()
        what_card.setObjectName("card")
        w_lay = QVBoxLayout(what_card)
        w_lay.setSpacing(6)
        w_lay.addWidget(QLabel("<b>🎯 Ne İşe Yarar?</b>"))
        sum_txt = tool.summary or "Bu eklenti yapay zeka istemcinize ek araç ve yetenekler kazandırır."
        det_txt = tool.details or ""
        full_what = f"{sum_txt}\n\n{det_txt}".strip() if det_txt else sum_txt
        what_lbl = QLabel(full_what)
        what_lbl.setWordWrap(True)
        w_lay.addWidget(what_lbl)
        lay.addWidget(what_card)

        when_card = QFrame()
        when_card.setObjectName("card")
        wh_lay = QVBoxLayout(when_card)
        wh_lay.addWidget(QLabel("<b>💡 Ne Zaman Açmalı / Ne Zaman Kapatmalı?</b>"))
        when_lbl = QLabel(
            tool.when_to_use
            or "İlgili projede aktif olarak ihtiyacınız olduğunda AÇIN; kullanmadığınız zamanlarda gereksiz şema tokenı harcamaması için KAPATIN."
        )
        when_lbl.setWordWrap(True)
        wh_lay.addWidget(when_lbl)
        lay.addWidget(when_card)

        tech_card = QFrame()
        tech_card.setObjectName("card")
        t_lay = QVBoxLayout(tech_card)
        t_lay.addWidget(QLabel("<b>📊 Teknik & Kaynak Özeti</b>"))

        if tool.id == "blender_skills":
            tok_info = "Seçilen her skill ~350 token (94 skill tamamı açılırsa ~33,000 token)"
        else:
            tok_info = f"~{tool.schema_tokens:,} şema tokenı (Kapalıyken 0 token)"

        key_info = (
            f"🔐 <b>{tool.vault_key_name}</b> gerekir (Şifreli Kasa sekmesinden girilir)"
            if tool.vault_key_name
            else "✓ Ücretsiz / API Anahtarı Gerekmez"
        )
        t_lay.addWidget(QLabel(f"• <b>Bağlam Yükü:</b> {tok_info}"))
        t_lay.addWidget(QLabel(f"• <b>Anahtar İhtiyacı:</b> {key_info}"))
        if tool.install_cmd:
            t_lay.addWidget(QLabel(f"• <b>Kurulum / Çalıştırma:</b> <code>{tool.install_cmd}</code>"))
        if tool.repo_url:
            link_lbl = QLabel(f"• <b>Resmi Kaynak:</b> <a style='color:#60a5fa;' href='{tool.repo_url}'>{tool.repo_url} ↗</a>")
            link_lbl.setOpenExternalLinks(True)
            t_lay.addWidget(link_lbl)
        lay.addWidget(tech_card)

        lay.addStretch()
        bot = QHBoxLayout()
        if tool.has_gear:
            btn_gear = QPushButton("⚙️ Bu Eklentinin Ayarlarını Aç")
            btn_gear.clicked.connect(lambda: (self.accept(), self.main_win.open_gear(tool)))
            bot.addWidget(btn_gear)
        bot.addStretch()
        btn_ok = QPushButton("Tamam")
        btn_ok.setObjectName("primaryBtn")
        btn_ok.clicked.connect(self.accept)
        bot.addWidget(btn_ok)
        lay.addLayout(bot)
        self.adjustSize()
