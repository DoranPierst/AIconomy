"""Self-updater dialog (emoji-free, standard vX.Y.Z format, EN & TR)."""
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

from ...i18n import tr
from ..workers import safe_emit
from ...updater import (
    UpdateCheckResult,
    apply_self_update,
    check_for_app_updates,
    get_current_app_version,
    resolve_effective_app_repo,
    restart_running_python_app,
)

if TYPE_CHECKING:
    from ..main_window import MainWindow


class AppUpdateDialog(QDialog):
    """One-click application update center via GitHub Releases or git pull."""

    def __init__(self, parent: "MainWindow", initial_result: UpdateCheckResult | None = None) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.lang = parent.lang
        self.last_check: UpdateCheckResult | None = initial_result
        cur_ver = get_current_app_version()
        self.setWindowTitle(tr(self.lang, "upd_title", ver=cur_ver))
        self.resize(600, 380)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        cur_repo = resolve_effective_app_repo(str(parent.meta.get("app_update_repo", "")))

        top_bar = QHBoxLayout()
        self.status_badge = QLabel(
            tr(self.lang, "upd_checking") if cur_repo else tr(self.lang, "upd_no_channel")
        )
        self.status_badge.setStyleSheet("font-weight: 700; font-size: 13px;")
        top_bar.addWidget(self.status_badge, stretch=1)

        self.notes_link_lbl = QLabel("")
        self.notes_link_lbl.setOpenExternalLinks(True)
        top_bar.addWidget(self.notes_link_lbl)

        self.btn_toggle_channel = QPushButton(tr(self.lang, "upd_channel_btn"))
        self.btn_toggle_channel.clicked.connect(self._toggle_repo_card)
        top_bar.addWidget(self.btn_toggle_channel)
        lay.addLayout(top_bar)

        self.repo_card = QFrame()
        self.repo_card.setObjectName("card")
        r_lay = QVBoxLayout(self.repo_card)
        r_lay.addWidget(QLabel(f"<b>{tr(self.lang, 'upd_channel_hdr')}</b>"))
        row = QHBoxLayout()
        self.repo_inp = QLineEdit(cur_repo)
        self.repo_inp.setPlaceholderText("https://github.com/DoranPierst/AIconomy")
        row.addWidget(self.repo_inp, stretch=1)

        btn_save_repo = QPushButton(tr(self.lang, "upd_channel_save"))
        btn_save_repo.setObjectName("primaryBtn")
        btn_save_repo.clicked.connect(self.run_check)
        row.addWidget(btn_save_repo)
        r_lay.addLayout(row)
        if cur_repo:
            self.repo_card.hide()
        lay.addWidget(self.repo_card)

        self.info_box = QPlainTextEdit()
        self.info_box.setReadOnly(True)
        self.info_box.setPlaceholderText(tr(self.lang, "upd_info_ph"))
        lay.addWidget(self.info_box, stretch=1)

        self.dl_bar = QProgressBar()
        self.dl_bar.hide()
        lay.addWidget(self.dl_bar)

        bot = QHBoxLayout()
        self.btn_check = QPushButton(tr(self.lang, "upd_btn_recheck"))
        self.btn_check.clicked.connect(self.run_check)
        bot.addWidget(self.btn_check)

        bot.addStretch()
        btn_close = QPushButton(tr(self.lang, "btn_close"))
        btn_close.clicked.connect(self.reject)
        self.btn_apply = QPushButton(tr(self.lang, "upd_btn_up_to_date"))
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

    def _toggle_repo_card(self) -> None:
        self.repo_card.setVisible(not self.repo_card.isVisible())

    def run_check(self) -> None:
        repo = self.repo_inp.text().strip()
        if repo:
            self.main_win.meta["app_update_repo"] = repo
            self.main_win._save_state()
        else:
            repo = resolve_effective_app_repo(str(self.main_win.meta.get("app_update_repo", "")))
        self.btn_check.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.status_badge.setText(tr(self.lang, "upd_checking"))
        self.status_badge.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 13px;")
        self.info_box.setPlainText(tr(self.lang, "upd_checking"))
        tok = self.main_win.vault.get_secret("GITHUB_TOKEN")

        lang = self.lang

        def worker() -> None:
            res = check_for_app_updates(repo, tok, lang=lang)
            safe_emit(self.main_win.bridge.app_check_done, res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_checked(self, res: UpdateCheckResult) -> None:
        if not res.ok and res.repo_url:
            self.main_win.logs.add("WARN", "Updater", res.message, f"Repo: {res.repo_url}\n{res.message}")
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
            self.status_badge.setText(res.message)
            self.status_badge.setStyleSheet("color: #f59e0b; font-weight: 700; font-size: 13px;")
            self.notes_link_lbl.setText("")
            if not res.repo_url:
                self.repo_card.show()
        elif res.has_update:
            self.status_badge.setText(
                tr(self.lang, "upd_status_avail", local=res.local_version, remote=res.remote_version)
            )
            self.status_badge.setStyleSheet("color: #f59e0b; font-weight: 700; font-size: 13px;")
            if res.release_notes_url:
                self.notes_link_lbl.setText(
                    f"<a style='color:#60a5fa;' href='{res.release_notes_url}'>{tr(self.lang, 'upd_notes_link')}</a>"
                )
        else:
            self.status_badge.setText(tr(self.lang, "upd_status_ok", local=res.local_version))
            self.status_badge.setStyleSheet("color: #22c55e; font-weight: 700; font-size: 13px;")
            if res.release_notes_url:
                self.notes_link_lbl.setText(
                    f"<a style='color:#60a5fa;' href='{res.release_notes_url}'>{tr(self.lang, 'upd_history_link')}</a>"
                )

        lines = [
            tr(self.lang, "upd_cmp_avail", local=res.local_version, remote=res.remote_version)
            if res.has_update
            else tr(self.lang, "upd_cmp_ok", local=res.local_version)
        ]
        if res.repo_url:
            lines.append(tr(self.lang, "upd_lbl_channel", url=res.repo_url))
        if res.release_notes_url:
            lines.append(tr(self.lang, "upd_lbl_notes", url=res.release_notes_url))
        if res.exe_download_url:
            lines.append(tr(self.lang, "upd_method_exe"))
        elif res.can_git_pull:
            lines.append(tr(self.lang, "upd_method_git"))
        if res.changelog:
            lines.extend(["", tr(self.lang, "upd_changelog_hdr"), res.changelog])
        self.info_box.setPlainText("\n".join(lines))

        self.btn_apply.setEnabled(res.ok and res.has_update)
        if res.has_update:
            self.btn_apply.setText(
                tr(self.lang, "upd_btn_install", local=res.local_version, remote=res.remote_version)
            )
        else:
            self.btn_apply.setText(tr(self.lang, "upd_btn_up_to_date"))

    def run_apply(self) -> None:
        if not self.last_check:
            return
        self.btn_apply.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.dl_bar.setMaximum(100)
        self.dl_bar.setValue(0)
        self.dl_bar.setFormat(tr(self.lang, "upd_downloading"))
        self.dl_bar.show()
        tok = self.main_win.vault.get_secret("GITHUB_TOKEN")
        chk = self.last_check

        lang = self.lang

        def worker() -> None:
            ok, mode, msg = apply_self_update(
                chk,
                tok,
                progress_cb=lambda cur, tot: safe_emit(self.main_win.bridge.app_dl_progress, cur, tot),
                lang=lang,
            )
            safe_emit(self.main_win.bridge.app_apply_done, ok, mode, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_dl_prog(self, cur: int, tot: int) -> None:
        if not self.isVisible():
            return
        if tot > 0:
            pct = int((cur * 100) / tot)
            self.dl_bar.setValue(pct)
            self.dl_bar.setFormat(
                tr(self.lang, "upd_dl_prog", cur=cur / (1024 * 1024), tot=tot / (1024 * 1024), pct=pct)
            )

    def _on_applied(self, ok: bool, mode: str, msg: str) -> None:
        if not ok:
            first_line = msg.splitlines()[0] if msg else "Update error"
            self.main_win.logs.add("ERR", "Updater", first_line, msg)
            self.main_win._refresh_logs_tab()
        else:
            self.main_win.logs.add("INFO", "Updater", "Application update applied.", msg)
            self.main_win._refresh_logs_tab()
        if not self.isVisible():
            return
        self.btn_check.setEnabled(True)
        self.dl_bar.setValue(100 if ok else 0)
        if not ok:
            self.btn_apply.setEnabled(True)
            QMessageBox.warning(
                self,
                tr(self.lang, "upd_err_title"),
                tr(self.lang, "upd_err_msg", msg=msg.splitlines()[0]),
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
        QMessageBox.information(self, tr(self.lang, "upd_done_title"), msg)
