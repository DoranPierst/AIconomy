"""AI response paste & parse dialog."""
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


class AiPasteDialog(QDialog):
    """Accept an AI response from clipboard or manual input for <<<ACIK: ...>>> parsing."""

    def __init__(self, parent: QWidget, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 340)
        lay = QVBoxLayout(self)
        info = QLabel(
            "AI'dan aldığın cevabı aşağıya yapıştır (panoda varsa otomatik dolduruldu).\n"
            "Program cevabın sonundaki <<<ACIK: ...>>> satırını (veya metindeki isimleri) otomatik yakalar:"
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        self.editor = QPlainTextEdit()
        clip = QApplication.clipboard().text()
        if clip:
            self.editor.setPlainText(clip)
        lay.addWidget(self.editor)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("İptal")
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton("📥 Analiz Et && Seçime Uygula")
        apply_btn.setObjectName("primaryBtn")
        apply_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(apply_btn)
        lay.addLayout(btns)
