"""AI response paste and parse dialog (emoji-free, EN & TR)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr


class AiPasteDialog(QDialog):
    """Accept an AI response from clipboard or manual input."""

    def __init__(self, parent: QWidget, title: str, lang: str = "en") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(600, 320)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        info = QLabel(tr(lang, "paste_info"))
        info.setWordWrap(True)
        lay.addWidget(info)

        self.editor = QPlainTextEdit()
        clip = QApplication.clipboard().text()
        if clip:
            self.editor.setPlainText(clip)
        lay.addWidget(self.editor)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton(tr(lang, "btn_cancel"))
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton(tr(lang, "paste_apply"))
        apply_btn.setObjectName("primaryBtn")
        apply_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(apply_btn)
        lay.addLayout(btns)
