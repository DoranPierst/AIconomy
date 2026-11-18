"""Persistent SQLite debug & log viewer tab mixin."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...ai_advisor import build_logs_ai_prompt
from ...updater import get_current_app_version
from ..widgets import HoverTableWidget


class LogsTabMixin:
    """Mixin implementing Tab 5 (Debug & Logs)."""

    def _init_logs_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        top = QHBoxLayout()
        self.log_lvl_cmb = QComboBox()
        self.log_lvl_cmb.addItems(["ALL", "ERR", "WARN", "INFO", "DBG"])
        self.log_lvl_cmb.currentTextChanged.connect(self._refresh_logs_tab)
        top.addWidget(QLabel("Seviye:"))
        top.addWidget(self.log_lvl_cmb)

        self.log_search_inp = QLineEdit()
        self.log_search_inp.setPlaceholderText("Log geçmişinde ara...")
        self.log_search_inp.textChanged.connect(self._refresh_logs_tab)
        top.addWidget(self.log_search_inp, stretch=1)

        top.addWidget(QLabel("🔌 Asılı Portu Kapat:"))
        for port_num, lbl in [(8080, "8080 Unity"), (9876, "9876 Blender"), (9121, "9121 Serena"), (8790, "8790 Trellis")]:
            zb = QPushButton(f"🔌 {lbl}")
            zb.setToolTip(
                f"Logları silmez! Yalnızca {port_num} portu arkada asılı kalırsa o porttaki arka plan sürecini kapatır.\n"
                "(Logları temizlemek için aşağıdaki '🧹 Logları Temizle' butonunu kullanın.)"
            )
            zb.clicked.connect(lambda _=False, p=port_num: self._handle_kill_zombie_port(p))
            top.addWidget(zb)
        lay.addLayout(top)

        self.log_table = HoverTableWidget(0, 5, self)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.log_table.setHorizontalHeaderLabels(
            ["", "Zaman", "Seviye", "Araç", "Özet Teşhis (Ham çıktı için satıra tıklayın)"]
        )
        lh = self.log_table.horizontalHeader()
        lh.setMinimumHeight(32)
        lh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        lh.resizeSection(0, 38)
        self.log_table.setColumnWidth(0, 38)
        lh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.log_master_cb = QCheckBox(lh.viewport())
        self.log_master_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_master_cb.setGeometry(10, 7, 20, 18)
        self.log_master_cb.setToolTip("Listelenen tüm log satırlarını seç / seçimi kaldır")
        self.log_master_cb.clicked.connect(lambda checked: self._set_log_checks("all" if checked else "none"))

        self.log_table.itemSelectionChanged.connect(self._on_log_row_selected)
        lay.addWidget(self.log_table, stretch=1)

        log_act_bar = QHBoxLayout()
        log_act_bar.setContentsMargins(2, 2, 2, 2)

        self.lbl_log_sel = QLabel("☑️ Seçili Log: 0")
        self.lbl_log_sel.setStyleSheet("color: #94a3b8; font-weight: 600;")
        log_act_bar.addWidget(self.lbl_log_sel)

        btn_l_all = QPushButton("Tümünü Seç")
        btn_l_all.clicked.connect(lambda: self._set_log_checks("all"))
        log_act_bar.addWidget(btn_l_all)

        btn_l_err = QPushButton("🔴 Sadece Hata && Uyarıları Seç (ERR/WARN)")
        btn_l_err.setToolTip("Listedeki tüm kırmızı (ERR) ve sarı (WARN) kayıtları tek tıkla işaretler")
        btn_l_err.clicked.connect(lambda: self._set_log_checks("issues_only"))
        log_act_bar.addWidget(btn_l_err)

        btn_l_clr = QPushButton("Seçimi Temizle")
        btn_l_clr.clicked.connect(lambda: self._set_log_checks("none"))
        log_act_bar.addWidget(btn_l_clr)

        btn_l_wipe = QPushButton("🧹 Logları Temizle")
        btn_l_wipe.setToolTip("Eski / çözülmüş tüm log kayıtlarını veritabanından temizler")
        btn_l_wipe.clicked.connect(self._clear_all_logs)
        log_act_bar.addWidget(btn_l_wipe)

        log_act_bar.addStretch()

        self.btn_copy_logs_ai = QPushButton("🤖 Seçili Loglar İçin Hazır AI Çözüm Promptu Kopyala (0)")
        self.btn_copy_logs_ai.setObjectName("primaryBtn")
        self.btn_copy_logs_ai.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_logs_ai.setToolTip(
            "Seçtiğiniz hata/debug kayıtlarını, tam ham çıktıları (stderr/komut) ve araçların kurulu sürümlerini\n"
            "birleştirerek doğrudan AI'a yapıştırabileceğiniz hazır çözüm promptu üretir."
        )
        self.btn_copy_logs_ai.clicked.connect(self._copy_selected_logs_ai_prompt)
        log_act_bar.addWidget(self.btn_copy_logs_ai)
        lay.addLayout(log_act_bar)

        self.log_raw_view = QPlainTextEdit()
        self.log_raw_view.setReadOnly(True)
        self.log_raw_view.setFixedHeight(125)
        self.log_raw_view.setPlaceholderText(
            "Bir log satırına tıkladığınızda ham teknik çıktı (stderr / port / detay) veya üretilen hazır AI çözüm promptu burada görüntülenir."
        )
        lay.addWidget(self.log_raw_view)

        self.tabs.addTab(tab, "🐛 Debug && Log")

    def _refresh_logs_tab(self) -> None:
        lvl = self.log_lvl_cmb.currentText()
        q = self.log_search_inp.text()
        self._current_logs = self.logs.query(level=lvl, search=q)
        self.log_row_checks.clear()
        self.log_table.setRowCount(0)
        self.log_table.setRowCount(len(self._current_logs))
        for i, row in enumerate(self._current_logs):
            self.log_table.setRowHeight(i, 32)
            log_id = int(row["id"])

            cb_w = QWidget()
            cb_w.setObjectName("cellBox")
            cb_l = QHBoxLayout(cb_w)
            cb_l.setContentsMargins(10, 0, 4, 0)
            l_cb = QCheckBox()
            l_cb.setCursor(Qt.CursorShape.PointingHandCursor)
            l_cb.setChecked(log_id in self.checked_log_ids)
            l_cb.toggled.connect(lambda checked, lid=log_id: self._on_single_log_check_toggled(lid, checked))
            self.log_row_checks[log_id] = l_cb
            cb_l.addWidget(l_cb)
            self.log_table.setCellWidget(i, 0, cb_w)

            for col_i, key in enumerate(("ts", "level", "tool", "summary"), start=1):
                item = QTableWidgetItem(str(row[key]))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if key == "level":
                    if row["level"] == "ERR":
                        item.setForeground(QColor("#ef4444"))
                    elif row["level"] == "WARN":
                        item.setForeground(QColor("#f59e0b"))
                self.log_table.setItem(i, col_i, item)
        counts = self.logs.counts_by_level()
        self.tabs.setTabText(4, f"🐛 Debug && Log (🔴{counts['ERR']} 🟡{counts['WARN']})")
        self._update_log_selection_ui()

    def _jump_to_error_logs(self) -> None:
        self.log_lvl_cmb.setCurrentText("ERR")
        self._refresh_logs_tab()
        self._set_log_checks("issues_only")
        self.tabs.setCurrentIndex(4)
        if self.log_table.rowCount() > 0:
            self.log_table.selectRow(0)

    def _on_single_log_check_toggled(self, log_id: int, checked: bool) -> None:
        if checked:
            self.checked_log_ids.add(log_id)
        else:
            self.checked_log_ids.discard(log_id)
        self._update_log_selection_ui()

    def _set_log_checks(self, mode: str) -> None:
        if mode == "all":
            for row in self._current_logs:
                self.checked_log_ids.add(int(row["id"]))
        elif mode == "issues_only":
            self.checked_log_ids = {int(row["id"]) for row in self._current_logs if row["level"] in ("ERR", "WARN")}
        else:
            self.checked_log_ids.clear()

        for lid, cb in self.log_row_checks.items():
            cb.blockSignals(True)
            cb.setChecked(lid in self.checked_log_ids)
            cb.blockSignals(False)
        self._update_log_selection_ui()

    def _update_log_selection_ui(self) -> None:
        sel_cnt = len(self.checked_log_ids)
        self.lbl_log_sel.setText(f"☑️ Seçili Log: {sel_cnt}")
        self.btn_copy_logs_ai.setText(f"🤖 Seçili Loglar İçin Hazır AI Çözüm Promptu Kopyala ({sel_cnt})")
        vis_ids = {int(r["id"]) for r in self._current_logs}
        all_vis_checked = bool(vis_ids) and vis_ids.issubset(self.checked_log_ids)
        self.log_master_cb.blockSignals(True)
        self.log_master_cb.setChecked(all_vis_checked)
        self.log_master_cb.blockSignals(False)

    def _copy_selected_logs_ai_prompt(self) -> None:
        if not self.checked_log_ids:
            idxs = self.log_table.selectionModel().selectedRows()
            if idxs:
                r = idxs[0].row()
                if 0 <= r < len(self._current_logs):
                    lid = int(self._current_logs[r]["id"])
                    self.checked_log_ids.add(lid)
                    if lid in self.log_row_checks:
                        self.log_row_checks[lid].setChecked(True)

        if not self.checked_log_ids:
            QMessageBox.information(
                self,
                "Log Seçilmedi",
                "AI çözüm promptu oluşturmak için lütfen en az bir log satırını solundaki kutucuktan işaretleyin\n"
                "(veya '🔴 Sadece Hata & Uyarıları Seç' butonuna tıklayın).",
            )
            return

        all_recent = self.logs.query(limit=500)
        selected_entries = [e for e in all_recent if int(e["id"]) in self.checked_log_ids]
        selected_entries.sort(key=lambda x: int(x["id"]))

        prompt = build_logs_ai_prompt(
            selected_entries,
            self.tools,
            get_current_app_version(),
            self.vram_bar.text(),
        )
        QApplication.clipboard().setText(prompt)
        self.log_raw_view.setPlainText(prompt)
        self.set_status(
            f"🤖 {len(selected_entries)} log kaydı ve araç sürümleri hazır AI çözüm promptu olarak panoya kopyalandı!"
        )

        self.btn_copy_logs_ai.setText(f"✓ AI Çözüm Promptu Kopyalandı! ({len(selected_entries)} Log)")
        self.btn_copy_logs_ai.setObjectName("successBtn")
        self.style().unpolish(self.btn_copy_logs_ai)
        self.style().polish(self.btn_copy_logs_ai)

        def _restore_log_btn() -> None:
            self.btn_copy_logs_ai.setObjectName("primaryBtn")
            self._update_log_selection_ui()
            self.style().unpolish(self.btn_copy_logs_ai)
            self.style().polish(self.btn_copy_logs_ai)

        QTimer.singleShot(1800, _restore_log_btn)

    def _clear_all_logs(self) -> None:
        self.logs.clear()
        self.checked_log_ids.clear()
        now_m = time.monotonic()
        for t in self.tools:
            self._last_warn_time[t.id] = now_m
        self._refresh_logs_tab()
        self.log_raw_view.clear()
        self.set_status("🧹 Tüm log kayıtları kalıcı olarak temizlendi.")

    def _on_log_row_selected(self) -> None:
        idxs = self.log_table.selectionModel().selectedRows()
        if not idxs:
            return
        r = idxs[0].row()
        if 0 <= r < len(self._current_logs):
            entry = self._current_logs[r]
            self.log_raw_view.setPlainText(f"[{entry['ts']}] [{entry['level']}] {entry['tool']}\n{entry['raw_detail']}")
