"""Self-updater dialog."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ...updater import (
    UpdateCheckResult,
    apply_self_update,
    check_for_app_updates,
    get_current_app_version,
    resolve_effective_app_repo,
    restart_running_python_app,
    stamp_repo_into_version_json,
)

if TYPE_CHECKING:
    from ..main_window import MainWindow


class AppUpdateDialog(QDialog):
    """One-click application update center via GitHub Releases or git pull."""

    def __init__(self, parent: "MainWindow", initial_result: UpdateCheckResult | None = None) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.last_check: UpdateCheckResult | None = initial_result
        cur_ver = get_current_app_version()
        self.setWindowTitle(f"🔄 Program Güncelleme Merkezi (Kullandığınız Sürüm: v{cur_ver})")
        self.resize(620, 380)

        lay = QVBoxLayout(self)

        cur_repo = resolve_effective_app_repo(str(parent.meta.get("app_update_repo", "")))

        top_bar = QHBoxLayout()
        self.status_badge = QLabel("🔍 Güncel sürüm kontrol ediliyor..." if cur_repo else "⚠️ Güncelleme kanalı henüz bağlanmadı")
        self.status_badge.setStyleSheet("font-weight: 700; font-size: 14px;")
        top_bar.addWidget(self.status_badge, stretch=1)

        self.notes_link_lbl = QLabel("")
        self.notes_link_lbl.setOpenExternalLinks(True)
        top_bar.addWidget(self.notes_link_lbl)

        self.btn_toggle_channel = QPushButton("⚙️ Kanal Ayarı")
        self.btn_toggle_channel.setToolTip("Güncellemelerin çekildiği GitHub depo adresini görüntüler veya değiştirir")
        self.btn_toggle_channel.clicked.connect(self._toggle_repo_card)
        top_bar.addWidget(self.btn_toggle_channel)
        lay.addLayout(top_bar)

        self.repo_card = QFrame()
        self.repo_card.setObjectName("card")
        r_lay = QVBoxLayout(self.repo_card)
        r_lay.addWidget(
            QLabel(
                "<b>GitHub Güncelleme Kanalı</b> "
                "<span style='color:#94a3b8;'>(Kaydettiğinizde ürettiğiniz .exe içine gömülür; paylaştığınız kişiler adres girmeden günceller)</span>"
            )
        )
        row = QHBoxLayout()
        self.repo_inp = QLineEdit(cur_repo)
        self.repo_inp.setPlaceholderText("https://github.com/DoranPierst/AIconomy")
        row.addWidget(self.repo_inp, stretch=1)

        btn_save_repo = QPushButton("💾 Kanalı Kaydet && Kontrol Et")
        btn_save_repo.setObjectName("primaryBtn")
        btn_save_repo.clicked.connect(self.run_check)
        row.addWidget(btn_save_repo)
        r_lay.addLayout(row)
        if cur_repo:
            self.repo_card.hide()
        lay.addWidget(self.repo_card)

        self.info_box = QPlainTextEdit()
        self.info_box.setReadOnly(True)
        self.info_box.setPlaceholderText("Sürüm karşılaştırması ve güncelleme notları burada görünür...")
        lay.addWidget(self.info_box, stretch=1)

        self.dl_bar = QProgressBar()
        self.dl_bar.hide()
        lay.addWidget(self.dl_bar)

        bot = QHBoxLayout()
        self.btn_check = QPushButton("🔍 Şimdi Tekrar Kontrol Et")
        self.btn_check.clicked.connect(self.run_check)
        bot.addWidget(self.btn_check)

        bot.addStretch()
        btn_close = QPushButton("Kapat")
        btn_close.clicked.connect(self.reject)
        self.btn_apply = QPushButton("✓ Sürüm Güncel")
        self.btn_apply.setObjectName("successBtn")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.run_apply)
        bot.addWidget(btn_close)
        bot.addWidget(self.btn_apply)
        lay.addLayout(bot)

        parent.bridge.app_check_done.connect(self._on_checked)
        parent.bridge.app_dl_progress.connect(self._on_dl_prog)
        parent.bridge.app_apply_done.connect(self._on_applied)

        if initial_result is not None and initial_result.ok:
            self._render_result(initial_result)
        elif cur_repo:
            QTimer.singleShot(120, self.run_check)
        else:
            self.info_box.setPlainText(
                "Bu programı arkadaşlarınıza veya topluluğa gönderdiğinizde tek tıkla güncelleme alabilmeleri için:\n\n"
                "1) GitHub'da oluşturduğunuz açık kaynak (Public) repo linkini yukarıdaki kutuya yapıştırıp kaydedin.\n"
                "2) Siz yeni bir sürüm yayınladığınızda, programı paylaştığınız herkes üst bardaki '🔄 Program Güncelle' butonuna basarak (veya programı açtığında gelen bildirimle) tekrar indirme yapmadan otomatik güncellenir."
            )

    def _toggle_repo_card(self) -> None:
        self.repo_card.setVisible(not self.repo_card.isVisible())

    def run_check(self) -> None:
        repo = self.repo_inp.text().strip()
        if repo:
            self.main_win.meta["app_update_repo"] = repo
            stamp_repo_into_version_json(repo)
            self.main_win._save_state()
        else:
            repo = resolve_effective_app_repo(str(self.main_win.meta.get("app_update_repo", "")))
        self.btn_check.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.status_badge.setText("🔍 GitHub üzerinden son sürüm kontrol ediliyor...")
        self.status_badge.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 14px;")
        self.info_box.setPlainText("GitHub üzerinden son sürüm ve değişiklik notları kontrol ediliyor...")
        tok = self.main_win.vault.get_secret("GITHUB_TOKEN")

        def worker() -> None:
            res = check_for_app_updates(repo, tok)
            self.main_win.bridge.app_check_done.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_checked(self, res: UpdateCheckResult) -> None:
        if not res.ok and res.repo_url:
            self.main_win.logs.add(
                "WARN",
                "Program Güncelleyici",
                f"Sürüm kontrol uyarısı: {res.message}",
                f"Repo: {res.repo_url}\nDetay: {res.message}",
            )
            self.main_win._refresh_logs_tab()
        if not self.isVisible():
            return
        self.btn_check.setEnabled(True)
        self._render_result(res)

    def _render_result(self, res: UpdateCheckResult) -> None:
        self.last_check = res
        if res.repo_url and not self.repo_inp.text().strip():
            self.repo_inp.setText(res.repo_url)

        if not res.ok:
            self.status_badge.setText(f"⚠️ {res.message}")
            self.status_badge.setStyleSheet("color: #f59e0b; font-weight: 700; font-size: 13px;")
            self.notes_link_lbl.setText("")
            if not res.repo_url:
                self.repo_card.show()
        elif res.has_update:
            self.status_badge.setText(f"🔔 Güncelleme Mevcut:  {res.local_version}v > {res.remote_version}v")
            self.status_badge.setStyleSheet("color: #f59e0b; font-weight: 700; font-size: 14px;")
            if res.release_notes_url:
                self.notes_link_lbl.setText(f"<a style='color:#60a5fa;' href='{res.release_notes_url}'>📄 Güncelleme Notları ↗</a>")
        else:
            self.status_badge.setText(f"✓ Programınız güncel ({res.local_version}v)")
            self.status_badge.setStyleSheet("color: #22c55e; font-weight: 700; font-size: 14px;")
            if res.release_notes_url:
                self.notes_link_lbl.setText(f"<a style='color:#60a5fa;' href='{res.release_notes_url}'>📄 Sürüm Geçmişi ↗</a>")

        lines = [
            f"Sürüm Karşılaştırması: {res.local_version}v > {res.remote_version}v"
            if res.has_update
            else f"Mevcut Sürüm: {res.local_version}v (En güncel sürümdesiniz)",
        ]
        if res.repo_url:
            lines.append(f"Güncelleme Kanalı: {res.repo_url}")
        if res.release_notes_url:
            lines.append(f"Güncelleme Notları: {res.release_notes_url}")
        if res.exe_download_url:
            lines.append("Güncelleme Yöntemi: Doğrudan AIconomy.exe otomatik yenileme (ayarlarınız korunur)")
        elif res.can_git_pull:
            lines.append("Güncelleme Yöntemi: Git Kaynak Deposu (git pull)")
        if res.changelog:
            lines.extend(["", "--- Bu Sürümdeki Yenilikler ---", res.changelog])
        self.info_box.setPlainText("\n".join(lines))

        self.btn_apply.setEnabled(res.ok and res.has_update)
        if res.has_update:
            self.btn_apply.setText(f"⚡ Şimdi Güncelle ve Yeniden Başlat ({res.local_version}v > {res.remote_version}v)")
        else:
            self.btn_apply.setText("✓ Sürüm Güncel")

    def run_apply(self) -> None:
        if not self.last_check:
            return
        self.btn_apply.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.dl_bar.setMaximum(100)
        self.dl_bar.setValue(0)
        self.dl_bar.setFormat("Yeni sürüm GitHub'dan indiriliyor...")
        self.dl_bar.show()
        tok = self.main_win.vault.get_secret("GITHUB_TOKEN")
        chk = self.last_check

        def worker() -> None:
            ok, mode, msg = apply_self_update(
                chk,
                tok,
                progress_cb=lambda cur, tot: self.main_win.bridge.app_dl_progress.emit(cur, tot),
            )
            self.main_win.bridge.app_apply_done.emit(ok, mode, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_dl_prog(self, cur: int, tot: int) -> None:
        if not self.isVisible():
            return
        if tot > 0:
            pct = int((cur * 100) / tot)
            self.dl_bar.setValue(pct)
            self.dl_bar.setFormat(f"İndiriliyor: {cur / (1024 * 1024):.1f} / {tot / (1024 * 1024):.1f} MB (%{pct})")

    def _on_applied(self, ok: bool, mode: str, msg: str) -> None:
        if not ok:
            first_line = msg.splitlines()[0] if msg else "Güncelleme hatası"
            self.main_win.logs.add("ERR", "Program Güncelleyici", first_line, msg)
            self.main_win._refresh_logs_tab()
        else:
            self.main_win.logs.add("INFO", "Program Güncelleyici", "Program güncellemesi başarıyla uygulandı.", msg)
            self.main_win._refresh_logs_tab()
        if not self.isVisible():
            return
        self.btn_check.setEnabled(True)
        self.dl_bar.setValue(100 if ok else 0)
        if not ok:
            self.btn_apply.setEnabled(True)
            QMessageBox.warning(
                self,
                "Güncelleme Hatası",
                f"{msg.splitlines()[0]}\n\n(Tam teknik çıktı Debug & Log sekmesine kaydedildi.)",
            )
            return
        if mode == "swap_exe":
            self.accept()
            self.main_win._quit_app()
            return
        if mode == "restart_py":
            self.accept()
            self.main_win._save_state()
            restart_running_python_app()
            return
        QMessageBox.information(self, "Güncelleme Tamamlandı", msg)
