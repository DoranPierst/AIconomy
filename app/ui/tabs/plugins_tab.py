"""Plugins & updates tab mixin (K9 thread-safe update check and batch upgrade)."""
from __future__ import annotations

import copy
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...catalog import ToolSpec
from ...plugins import PluginCheckResult, check_all_tools_updates_parallel, update_single_tool


class PluginsTabMixin:
    """Mixin implementing Tab 2 (Plugins & Updates)."""

    def _init_plugins_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        top = QHBoxLayout()
        btn_sel_all = QPushButton("Tümünü Seç")
        btn_sel_all.clicked.connect(lambda: self._set_all_plugin_checks(True))
        top.addWidget(btn_sel_all)

        btn_clr_all = QPushButton("Seçimi Temizle")
        btn_clr_all.clicked.connect(lambda: self._set_all_plugin_checks(False))
        top.addWidget(btn_clr_all)

        self.btn_plugins_check = QPushButton("🔍 Güncellemeleri Kontrol Et")
        self.btn_plugins_check.setObjectName("primaryBtn")
        self.btn_plugins_check.clicked.connect(lambda: self.run_plugin_update_check(manual=True))
        top.addWidget(self.btn_plugins_check)

        self.btn_plugins_update_all = QPushButton("⬆️ Mevcut Güncellemeleri Başlat (0)")
        self.btn_plugins_update_all.setObjectName("successBtn")
        self.btn_plugins_update_all.setEnabled(False)
        self.btn_plugins_update_all.clicked.connect(self._handle_start_available_updates)
        top.addWidget(self.btn_plugins_update_all)

        self.btn_plugins_install_sel = QPushButton("📦 Seçilenleri Kur / Güncelle")
        self.btn_plugins_install_sel.clicked.connect(self._handle_update_selected_plugins)
        top.addWidget(self.btn_plugins_install_sel)

        top.addStretch()

        btn_export = QPushButton("📤 Export")
        btn_export.setToolTip("Tüm açık/kapalı durumlarını, 94 skill seçimini, proje kapsamlarını, çark ve kutucuk seçimlerini dışa aktarır")
        btn_export.clicked.connect(self._export_settings)
        top.addWidget(btn_export)

        btn_import = QPushButton("📥 Import")
        btn_import.setToolTip("Dışa aktarılan ayar dosyasını tüm seçimlerinizle birlikte geri yükler")
        btn_import.clicked.connect(self._import_settings)
        top.addWidget(btn_import)
        lay.addLayout(top)

        banner = QFrame()
        banner.setObjectName("card")
        b_lay = QHBoxLayout(banner)
        b_lay.setContentsMargins(10, 6, 10, 6)
        self.plugins_banner_lbl = QLabel("🔍 Açılış güncelleme kontrolü yapılıyor...")
        self.plugins_banner_lbl.setStyleSheet("font-weight: 600;")
        b_lay.addWidget(self.plugins_banner_lbl, stretch=1)

        self.btn_jump_err_logs = QPushButton("🐛 Hata Logunu Gör")
        self.btn_jump_err_logs.setObjectName("warnBtn")
        self.btn_jump_err_logs.hide()
        self.btn_jump_err_logs.clicked.connect(self._jump_to_error_logs)
        b_lay.addWidget(self.btn_jump_err_logs)
        lay.addWidget(banner)

        self.update_prog = QProgressBar()
        self.update_prog.hide()
        lay.addWidget(self.update_prog)

        self.plugins_scroll = QScrollArea()
        self.plugins_scroll.setWidgetResizable(True)
        self.plugins_host = QWidget()
        self.plugins_lay = QVBoxLayout(self.plugins_host)
        self.plugins_scroll.setWidget(self.plugins_host)
        lay.addWidget(self.plugins_scroll, stretch=1)

        self.tabs.addTab(tab, "🧩 Eklentiler")

    def _set_all_plugin_checks(self, state: bool) -> None:
        for cb in self.plugin_checks.values():
            cb.blockSignals(True)
            cb.setChecked(state)
            cb.blockSignals(False)
        self._sync_plugin_checks_to_meta()
        self._save_state()

    def _sync_plugin_checks_to_meta(self) -> None:
        self.meta["plugin_checked_ids"] = [tid for tid, cb in self.plugin_checks.items() if cb.isChecked()]

    def _on_single_plugin_check_changed(self) -> None:
        self._sync_plugin_checks_to_meta()
        self._save_state()

    def _refresh_plugins_tab(self) -> None:
        saved_checked_list = self.meta.get("plugin_checked_ids")
        if isinstance(saved_checked_list, list):
            checked_set = set(saved_checked_list)
        else:
            checked_set = {t.id for t in self.tools if t.enabled}

        self.plugin_checks.clear()
        while self.plugins_lay.count():
            item = self.plugins_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        upd_count = sum(1 for t in self.tools if t.has_update)
        self.btn_plugins_update_all.setText(f"⬆️ Mevcut Güncellemeleri Başlat ({upd_count})")
        self.btn_plugins_update_all.setEnabled(upd_count > 0 and not self.updating_busy)

        for t in self.tools:
            card = QFrame()
            card.setObjectName("card")
            row = QHBoxLayout(card)

            cb = QCheckBox()
            cb.setChecked(t.id in checked_set)
            cb.toggled.connect(lambda _checked: self._on_single_plugin_check_changed())
            self.plugin_checks[t.id] = cb
            row.addWidget(cb)

            cur_v = t.version.strip().lstrip("vV")
            lat_v = (t.latest_version or t.version).strip().lstrip("vV")

            if t.has_update:
                ver_html = (
                    f"<span style='color:#f59e0b; font-weight:700;'>🔔 Güncelleme Mevcut:  {cur_v}v &gt; {lat_v}v</span>"
                )
            else:
                ver_html = f"<span style='color:#22c55e; font-weight:600;'>✓ Güncel ({cur_v}v)</span>"

            info_col = QVBoxLayout()
            info_col.setSpacing(2)
            title_row = QHBoxLayout()
            title_row.setSpacing(6)
            title_row.addWidget(QLabel(f"<b>{t.name}</b>"))
            title_row.addWidget(self._make_info_btn(t))
            title_row.addWidget(QLabel(f"<span style='color:#94a3b8;'>({t.kind})</span>   {ver_html}"))
            title_row.addStretch()
            info_col.addLayout(title_row)
            if t.summary:
                desc_lbl = QLabel(t.summary)
                desc_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
                desc_lbl.setWordWrap(True)
                info_col.addWidget(desc_lbl)
            row.addLayout(info_col, stretch=1)

            if t.release_notes_url:
                notes_lbl = QLabel(f"<a style='color:#60a5fa;' href='{t.release_notes_url}'>📄 Sürüm Notları ↗</a>")
                notes_lbl.setOpenExternalLinks(True)
                notes_lbl.setToolTip(t.release_notes_url)
                row.addWidget(notes_lbl)

            if t.has_update:
                upd_one = QPushButton(f"⬆️ Güncelle ({cur_v}v > {lat_v}v)")
                upd_one.setObjectName("warnBtn")
            else:
                upd_one = QPushButton("🔄 Kur / Yenile")
            upd_one.clicked.connect(lambda _=False, tool_obj=t: self._run_batch_update([tool_obj], install_if_missing=True))
            row.addWidget(upd_one)

            copy_cmd = QPushButton("📋 Komut")
            copy_cmd.clicked.connect(
                lambda _=False, c=(t.install_cmd or t.repo_url), nm=t.name: (
                    QApplication.clipboard().setText(c),
                    self.set_status(f"{nm} kurulum komutu panoya kopyalandı: {c}"),
                )
            )
            row.addWidget(copy_cmd)
            self.plugins_lay.addWidget(card)
        self.plugins_lay.addStretch()

    def run_plugin_update_check(self, manual: bool = False) -> None:
        if self.checking_plugins_busy or self.updating_busy:
            return
        self.checking_plugins_busy = True
        self.btn_plugins_check.setEnabled(False)
        self.plugins_banner_lbl.setText("🔍 Eklenti sürümleri kontrol ediliyor...")
        self.plugins_banner_lbl.setStyleSheet("color: #94a3b8; font-weight: 600;")
        if manual:
            self.set_status("🔍 Tüm eklentiler için güncel sürüm kontrolü yapılıyor...")

        # K9: pass immutable deep copies to worker; UI thread applies results via signal
        snap = copy.deepcopy(self.tools)
        tok = self.vault.get_secret("GITHUB_TOKEN")

        def worker() -> None:
            results, chk_errs = check_all_tools_updates_parallel(snap, tok)
            for t_name, err_det in chk_errs:
                self.logs.add("WARN", t_name, f"Güncelleme kontrolü sırasında ağ/API hatası: {err_det.splitlines()[0]}", err_det)
            self.bridge.plugin_check_done.emit(results, manual)

        threading.Thread(target=worker, daemon=True).start()

    def _on_plugin_check_done(self, results: list[PluginCheckResult] | None, manual: bool) -> None:
        self.checking_plugins_busy = False
        self.btn_plugins_check.setEnabled(True)
        self.btn_jump_err_logs.hide()

        # K9: mutate shared ToolSpec objects exclusively on the UI thread
        if results:
            by_id = {t.id: t for t in self.tools}
            for item in results:
                t = by_id.get(item.tool_id)
                if t is None:
                    continue
                if item.local_version:
                    t.version = item.local_version
                t.latest_version = item.latest_version
                t.has_update = item.has_update
                t.release_notes_url = item.release_notes_url

        upd_count = sum(1 for t in self.tools if t.has_update)
        self._refresh_logs_tab()

        if upd_count == 0:
            self.plugins_banner_lbl.setText("✓ Tüm eklentiler güncel.")
            self.plugins_banner_lbl.setStyleSheet("color: #22c55e; font-weight: 700;")
            self.tabs.setTabText(1, "🧩 Eklentiler")
            if manual:
                self.set_status("✓ Tüm eklentiler güncel.")
        else:
            self.plugins_banner_lbl.setText(
                f"🔔 Güncelleme Mevcut ({upd_count} eklenti) — Güncellemeyi başlatmak için aşağıdaki butonları kullanabilirsiniz."
            )
            self.plugins_banner_lbl.setStyleSheet("color: #f59e0b; font-weight: 700;")
            self.tabs.setTabText(1, f"🧩 Eklentiler (🔔 {upd_count})")
            self.set_status(f"🔔 {upd_count} eklenti için güncelleme mevcut — Eklentiler sekmesinden başlatabilirsiniz.")
            if manual:
                self.tabs.setCurrentIndex(1)

        self._refresh_table()
        self._refresh_plugins_tab()

    def _handle_start_available_updates(self) -> None:
        targets = [t for t in self.tools if t.has_update]
        if not targets:
            self.set_status("✓ Tüm eklentiler zaten güncel.")
            return
        self._run_batch_update(targets, install_if_missing=True)

    def _handle_update_selected_plugins(self) -> None:
        selected = [t for t in self.tools if self.plugin_checks.get(t.id) and self.plugin_checks[t.id].isChecked()]
        if not selected:
            QMessageBox.information(self, "Araç Seçilmedi", "Lütfen listeden kurmak veya güncellemek istediğiniz araçları işaretleyin.")
            return
        self._run_batch_update(selected, install_if_missing=True)

    def _run_batch_update(self, target_tools: list[ToolSpec], install_if_missing: bool = False) -> None:
        if self.updating_busy or not target_tools:
            return
        self.updating_busy = True
        self.btn_plugins_check.setEnabled(False)
        self.btn_plugins_update_all.setEnabled(False)
        self.btn_plugins_install_sel.setEnabled(False)

        total = len(target_tools)
        self.update_prog.setMaximum(total)
        self.update_prog.setValue(0)
        self.update_prog.setFormat(f"Güncelleme uygulanıyor (0/{total})...")
        self.update_prog.show()
        self.set_status(f"⬆️ {total} araç güncelleniyor...")

        # K9: pass immutable snapshots; worker never touches live ToolSpec instances
        wanted_skills = set(self.active_skills)
        items = copy.deepcopy(target_tools)

        def worker() -> None:
            ok_cnt = 0
            fail_cnt = 0
            details: list[str] = []
            for idx, tool_snap in enumerate(items, start=1):
                self.bridge.update_progress.emit(idx, total, tool_snap.name)
                prev_v = tool_snap.version.strip().lstrip("vV")
                ok, new_ver, msg, raw_log = update_single_tool(
                    tool_snap, wanted_skills, install_if_missing=install_if_missing
                )
                target_v = (tool_snap.latest_version or new_ver or tool_snap.version).strip().lstrip("vV")
                self.bridge.update_item_done.emit(tool_snap.id, ok, prev_v, target_v, msg, raw_log)
                if ok:
                    ok_cnt += 1
                    ver_note = f"{prev_v}v > {target_v}v" if prev_v != target_v else f"{target_v}v"
                    details.append(f"✓ {tool_snap.name} ({ver_note}): {msg}")
                else:
                    fail_cnt += 1
                    details.append(f"🔴 {tool_snap.name}: {msg}")
            self.bridge.update_all_done.emit(ok_cnt, fail_cnt, "\n".join(details))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_item_done(
        self, tool_id: str, ok: bool, prev_v: str, target_v: str, msg: str, raw_log: str
    ) -> None:
        """K9: apply single-tool upgrade result onto UI-thread ToolSpec safely."""
        tool_obj = next((t for t in self.tools if t.id == tool_id), None)
        t_name = tool_obj.name if tool_obj else tool_id
        if ok:
            if tool_obj is not None:
                tool_obj.version = f"v{target_v}"
                tool_obj.latest_version = f"v{target_v}"
                tool_obj.has_update = False
            ver_note = f"{prev_v}v > {target_v}v" if prev_v != target_v else f"{target_v}v"
            self.logs.add("INFO", t_name, f"Güncellendi ({ver_note})", raw_log)
        else:
            self.logs.add("ERR", t_name, f"Güncelleme Hatası: {msg}", raw_log)

    def _on_update_progress(self, idx: int, total: int, tool_name: str) -> None:
        self.update_prog.setValue(idx - 1)
        self.update_prog.setFormat(f"Güncelleniyor ({idx}/{total}): {tool_name}...")
        self.set_status(f"⬆️ Güncelleniyor ({idx}/{total}): {tool_name}...")

    def _on_update_all_done(self, ok_cnt: int, fail_cnt: int, summary_text: str) -> None:
        self.updating_busy = False
        self.btn_plugins_check.setEnabled(True)
        self.btn_plugins_install_sel.setEnabled(True)
        self.update_prog.setValue(self.update_prog.maximum())
        self.update_prog.setFormat(f"Tamamlandı: {ok_cnt} güncellendi, {fail_cnt} hata")
        QTimer.singleShot(3500, self.update_prog.hide)

        self._on_plugin_check_done(None, manual=False)
        if fail_cnt > 0:
            self.plugins_banner_lbl.setText(
                f"🔴 {fail_cnt} araç güncellenirken hata alındı ({ok_cnt} başarılı) — Hata detayları Debug & Log sekmesine kaydedildi."
            )
            self.plugins_banner_lbl.setStyleSheet("color: #ef4444; font-weight: 700;")
            self.btn_jump_err_logs.show()
            self.set_status(f"🔴 Güncelleme sırasında {fail_cnt} hata oluştu — Debug & Log sekmesinden tam çıktıyı görebilirsiniz.")
        else:
            self.set_status(f"✓ Güncelleme tamamlandı ({ok_cnt} araç güncellendi).")
        self._save_state()
        self._refresh_logs_tab()
        self.run_health_scan()
