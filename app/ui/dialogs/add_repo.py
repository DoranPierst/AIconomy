"""Add Tool from GitHub dialog (replaces legacy + Repo Ekle tab with clean production UX)."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ...catalog import ToolSpec, normalize_tool_kind, tool_kind_label
from ...i18n import tr
from ...plugins import inspect_github_repo
from ..workers import WorkerBridge, safe_emit

if TYPE_CHECKING:
    from ..main_window import MainWindow


class AddRepoDialog(QDialog):
    """Inspect a GitHub repository and add it as a custom tool."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.main_win = parent
        self.lang = parent.lang
        self.detected_candidate: dict[str, Any] | None = None
        self.added_tool: ToolSpec | None = None

        self._bridge = WorkerBridge()
        self._bridge.repo_done.connect(self._on_inspected)

        self.setWindowTitle(tr(self.lang, "repo_title"))
        self.resize(620, 380)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        desc = QLabel(tr(self.lang, "repo_desc"))
        desc.setWordWrap(True)
        lay.addWidget(desc)

        bar = QHBoxLayout()
        self.url_inp = QLineEdit()
        self.url_inp.setPlaceholderText(tr(self.lang, "repo_ph"))
        self.url_inp.returnPressed.connect(self._inspect)
        bar.addWidget(self.url_inp, stretch=1)

        self.btn_inspect = QPushButton(tr(self.lang, "repo_inspect"))
        self.btn_inspect.setObjectName("primaryBtn")
        self.btn_inspect.clicked.connect(self._inspect)
        bar.addWidget(self.btn_inspect)
        lay.addLayout(bar)

        self.result_box = QPlainTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setPlaceholderText(tr(self.lang, "repo_result_ph"))
        lay.addWidget(self.result_box, stretch=1)

        bot = QHBoxLayout()
        bot.addStretch()
        btn_cancel = QPushButton(tr(self.lang, "btn_cancel"))
        btn_cancel.clicked.connect(self.reject)
        bot.addWidget(btn_cancel)

        self.btn_add = QPushButton(tr(self.lang, "repo_add"))
        self.btn_add.setObjectName("successBtn")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._add_repo)
        bot.addWidget(self.btn_add)
        lay.addLayout(bot)

    def _inspect(self) -> None:
        url = self.url_inp.text().strip()
        if not url:
            return
        self.btn_inspect.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.result_box.setPlainText(tr(self.lang, "repo_inspecting"))
        tok = self.main_win.vault.get_secret("GITHUB_TOKEN")

        lang = self.lang

        def worker() -> None:
            try:
                info = inspect_github_repo(url, tok, lang=lang)
                safe_emit(self._bridge.repo_done, {"ok": True, "info": info})
            except Exception as exc:
                safe_emit(self._bridge.repo_done, {"ok": False, "error": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _on_inspected(self, payload: dict[str, Any]) -> None:
        self.btn_inspect.setEnabled(True)
        if not payload.get("ok"):
            self.detected_candidate = None
            self.result_box.setPlainText(tr(self.lang, "repo_err", err=payload.get("error", "")))
            return
        info = payload["info"]
        self.detected_candidate = info
        self.btn_add.setEnabled(True)
        kind_lbl = tool_kind_label(info["kind"], self.lang)
        self.result_box.setPlainText(
            tr(
                self.lang,
                "repo_summary",
                name=info["name"],
                stars=info["stars"],
                kind=kind_lbl,
                skills=info["skill_count"],
                desc=info["description"],
                cmd=info["install_cmd"],
                key=tr(self.lang, "yes" if info["needs_api_key"] else "no"),
            )
        )

    def _add_repo(self) -> None:
        info = self.detected_candidate
        if not info:
            return
        if any(t.repo_url.lower() == info["repo_url"].lower() for t in self.main_win.tools):
            QMessageBox.information(
                self,
                tr(self.lang, "repo_exists_title"),
                tr(self.lang, "repo_exists_msg", name=info["name"]),
            )
            return
        has_real_gear = bool(info["needs_api_key"])
        auto_tags = ["automation"] if info["needs_api_key"] else ["free_local", "automation"]
        self.added_tool = ToolSpec(
            id=info["id"],
            name=info["name"],
            kind=normalize_tool_kind(info["kind"]),
            version="v1.0.0",
            repo_url=info["repo_url"],
            schema_tokens=2000,
            summary=str(info.get("description") or f"{info['name']} custom tool."),
            details=f"Added from GitHub ({info['repo_url']}).",
            when_to_use="",
            enabled=True,
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=has_real_gear,
            param_label="Extra arguments / path" if has_real_gear else "",
            install_cmd=info["install_cmd"],
            mcp_server_key=info["id"] if info["mcp_command"] else "",
            mcp_command=info["mcp_command"],
            mcp_args=info["mcp_args"],
            tags=auto_tags,
        )
        self.accept()
