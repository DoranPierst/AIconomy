"""End-to-end MCP connection verification dialog."""
from __future__ import annotations

import copy
import threading

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...catalog import ToolSpec
from ...diagnostics import test_tool_connection_e2e
from ...storage import WindowsDpapiVault
from ..workers import WorkerBridge


class ConnectionTestDialog(QDialog):
    """Test real HTTP/socket/stdio MCP connections for all enabled tools."""

    def __init__(
        self,
        parent: QWidget,
        tools: list[ToolSpec],
        vault: WindowsDpapiVault,
        projects_map: dict[str, str],
        active_skills_count: int,
    ) -> None:
        super().__init__(parent)
        self.tools = [copy.deepcopy(t) for t in tools if t.enabled]
        self.vault = vault
        self.projects_map = dict(projects_map)
        self.active_skills_count = active_skills_count
        self._running = False
        self._bridge = WorkerBridge()
        self._bridge.conn_test_row.connect(self._on_row_result)
        self._bridge.conn_test_done.connect(self._on_all_done)

        self.setWindowTitle("🔌 Bağlantı Test Merkezi (Canlı MCP & İstemci Doğrulama)")
        self.resize(840, 520)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        info = QLabel(
            "<b>Antigravity veya başka bir AI editörü açık olmasa bile</b> tüm <b>AÇIK</b> araçların gerçekten çalışıp çalışmadığını "
            "doğrudan test eder (HTTP MCP <code>initialize</code>, Blender <code>get_scene_info</code>, stdio MCP el sıkışması ve config kontrolü)."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        self.tbl = QTableWidget(len(self.tools), 4, self)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setHorizontalHeaderLabels(["Araç", "Durum", "Gecikme", "Test Sonucu / Detay"])
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tbl.itemSelectionChanged.connect(self._on_row_selected)
        lay.addWidget(self.tbl, stretch=1)

        self.detail_box = QPlainTextEdit()
        self.detail_box.setReadOnly(True)
        self.detail_box.setFixedHeight(95)
        self.detail_box.setPlaceholderText("Detaylı ham teknik yanıtı görmek için yukarıdan bir satıra tıklayın...")
        lay.addWidget(self.detail_box)

        bot = QHBoxLayout()
        self.summary_lbl = QLabel("Hazır.")
        self.summary_lbl.setStyleSheet("font-weight: 600;")
        bot.addWidget(self.summary_lbl, stretch=1)

        self.btn_retest = QPushButton("🔄 Tümünü Tekrar Test Et")
        self.btn_retest.setObjectName("primaryBtn")
        self.btn_retest.clicked.connect(self.start_tests)
        bot.addWidget(self.btn_retest)

        btn_close = QPushButton("Kapat")
        btn_close.clicked.connect(self.accept)
        bot.addWidget(btn_close)
        lay.addLayout(bot)

        self._raw_details: list[str] = [""] * len(self.tools)
        self._ok_count = 0
        self._fail_count = 0
        self.start_tests()

    def start_tests(self) -> None:
        if self._running:
            return
        self._running = True
        self._ok_count = 0
        self._fail_count = 0
        self.btn_retest.setEnabled(False)
        self._raw_details = [""] * len(self.tools)

        if not self.tools:
            self.summary_lbl.setText("⚠️ Panelde AÇIK araç yok — önce Araç Paneli'nden test etmek istediğiniz araçları açın.")
            self._running = False
            self.btn_retest.setEnabled(True)
            return

        self.summary_lbl.setText(f"⏳ {len(self.tools)} aktif araç test ediliyor...")
        for r, t in enumerate(self.tools):
            self.tbl.setItem(r, 0, QTableWidgetItem(t.name))
            self.tbl.setItem(r, 1, QTableWidgetItem("⏳ Bekliyor"))
            self.tbl.setItem(r, 2, QTableWidgetItem("—"))
            self.tbl.setItem(r, 3, QTableWidgetItem("Bağlantı deneniyor..."))

        snap = list(self.tools)
        proj = dict(self.projects_map)
        sk = self.active_skills_count

        def worker() -> None:
            for idx, t in enumerate(snap):
                ok, ms, msg, raw = test_tool_connection_e2e(t, self.vault, proj, sk)
                self._bridge.conn_test_row.emit(idx, ok, ms, msg, raw)
            self._bridge.conn_test_done.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _on_row_result(self, row: int, ok: bool, ms: int, msg: str, raw: str) -> None:
        if row < 0 or row >= len(self.tools):
            return
        self._raw_details[row] = raw
        if ok:
            self._ok_count += 1
        else:
            self._fail_count += 1
        st_item = QTableWidgetItem("✅ Başarılı" if ok else "❌ Başarısız")
        st_item.setForeground(QColor("#22c55e" if ok else "#ef4444"))
        self.tbl.setItem(row, 1, st_item)
        self.tbl.setItem(row, 2, QTableWidgetItem(f"{ms}ms" if ms >= 0 else "—"))
        self.tbl.setItem(row, 3, QTableWidgetItem(msg))

    def _on_all_done(self) -> None:
        self._running = False
        self.btn_retest.setEnabled(True)
        self.summary_lbl.setText(
            f"Test Tamamlandı: {self._ok_count} Başarılı, {self._fail_count} Başarısız ({len(self.tools)} AÇIK araç)"
        )

    def _on_row_selected(self) -> None:
        idxs = self.tbl.selectionModel().selectedRows()
        if not idxs:
            return
        r = idxs[0].row()
        if 0 <= r < len(self._raw_details):
            self.detail_box.setPlainText(self._raw_details[r])
