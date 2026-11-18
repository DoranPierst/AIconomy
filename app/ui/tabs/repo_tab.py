"""GitHub repository discovery tab mixin (converted to Add from GitHub dialog in Phase 3)."""
from __future__ import annotations

import threading
from typing import Any

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...catalog import ToolSpec
from ...plugins import inspect_github_repo


class RepoTabMixin:
    """Mixin implementing Tab 4 (Add GitHub Repository)."""

    def _init_repo_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        bar = QHBoxLayout()
        self.repo_inp = QLineEdit("https://github.com/Linkingooo/renderdoc-mcp")
        self.repo_inp.setPlaceholderText("GitHub repo adresini yapıştırın (örn: https://github.com/owner/repo)...")
        bar.addWidget(self.repo_inp, stretch=1)

        self.btn_probe_repo = QPushButton("🔍 Sorgula & Tanı")
        self.btn_probe_repo.setObjectName("primaryBtn")
        self.btn_probe_repo.clicked.connect(self._handle_inspect_repo)
        bar.addWidget(self.btn_probe_repo)
        lay.addLayout(bar)

        quick = QHBoxLayout()
        quick.addWidget(QLabel("Hızlı Test:"))
        for sample in (
            "https://github.com/qybaihe/bla",
            "https://github.com/arjun988/blender-skills",
            "https://github.com/Linkingooo/renderdoc-mcp",
            "https://github.com/elevenlabs/elevenlabs-mcp",
        ):
            short = sample.split("github.com/")[1]
            b = QPushButton(short)
            b.clicked.connect(lambda _=False, u=sample: (self.repo_inp.setText(u), self._handle_inspect_repo()))
            quick.addWidget(b)
        quick.addStretch()
        lay.addLayout(quick)

        self.repo_result_box = QPlainTextEdit()
        self.repo_result_box.setReadOnly(True)
        self.repo_result_box.setPlaceholderText("GitHub bağlantısını sorguladığınızda algılanan kurulum yapısı burada görünecek...")
        lay.addWidget(self.repo_result_box, stretch=1)

        add_bar = QHBoxLayout()
        add_bar.addStretch()
        self.btn_add_repo = QPushButton("+ Kütüphaneye ve Ana Panele Ekle")
        self.btn_add_repo.setObjectName("successBtn")
        self.btn_add_repo.setEnabled(False)
        self.btn_add_repo.clicked.connect(self._handle_add_detected_repo)
        add_bar.addWidget(self.btn_add_repo)
        lay.addLayout(add_bar)

        self.tabs.addTab(tab, "📚 + Repo Ekle")

    def _handle_inspect_repo(self) -> None:
        url = self.repo_inp.text().strip()
        if not url:
            return
        self.btn_probe_repo.setEnabled(False)
        self.btn_add_repo.setEnabled(False)
        self.repo_result_box.setPlainText("GitHub API üzerinden repo yapısı sorgulanıyor...")
        tok = self.vault.get_secret("GITHUB_TOKEN")

        def worker() -> None:
            try:
                info = inspect_github_repo(url, tok)
                self.bridge.repo_done.emit({"ok": True, "info": info})
            except Exception as exc:
                self.bridge.repo_done.emit({"ok": False, "error": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _on_repo_inspected(self, payload: dict[str, Any]) -> None:
        self.btn_probe_repo.setEnabled(True)
        if not payload.get("ok"):
            self.detected_repo_candidate = None
            self.repo_result_box.setPlainText(f"Sorgulama hatası: {payload.get('error')}")
            return
        info = payload["info"]
        self.detected_repo_candidate = info
        self.btn_add_repo.setEnabled(True)
        self.repo_result_box.setPlainText(
            f"Ad: {info['name']}  (⭐ {info['stars']})\n"
            f"Algılanan Tür: {info['kind']}  |  SKILL.md Sayısı: {info['skill_count']}\n"
            f"Açıklama: {info['description']}\n"
            f"Kurulum / Çalıştırma: {info['install_cmd']}\n"
            f"API Anahtarı İhtiyacı: {'Evet (⚙️ Çark eklenecek)' if info['needs_api_key'] else 'Hayır (Sade satır — gereksiz çark eklenmeyecek)'}"
        )

    def _handle_add_detected_repo(self) -> None:
        info = self.detected_repo_candidate
        if not info:
            return
        if any(t.repo_url.lower() == info["repo_url"].lower() for t in self.tools):
            QMessageBox.information(self, "Zaten Ekli", f"{info['name']} zaten araç listenizde bulunuyor.")
            return
        has_real_gear = bool(info["needs_api_key"])
        new_tool = ToolSpec(
            id=info["id"],
            name=info["name"],
            kind=info["kind"],
            version="v1.0.0",
            repo_url=info["repo_url"],
            schema_tokens=2000,
            summary=str(info.get("description") or f"{info['name']} özel eklentisi."),
            details=f"GitHub üzerinden eklenen {info['kind']} aracı ({info['repo_url']}).",
            when_to_use="İlgili projede bu eklentinin özelliklerine ihtiyacınız olduğunda AÇIN; kullanmadığınızda şema tasarrufu için KAPATIN.",
            enabled=True,
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=has_real_gear,
            param_label="Ek Argüman / Yol" if has_real_gear else "",
            install_cmd=info["install_cmd"],
            mcp_server_key=info["id"] if info["mcp_command"] else "",
            mcp_command=info["mcp_command"],
            mcp_args=info["mcp_args"],
        )
        self.tools.append(new_tool)
        cur_p_chk = self._get_panel_checked_set()
        cur_p_chk.add(new_tool.id)
        self.meta["panel_checked_ids"] = [t.id for t in self.tools if t.id in cur_p_chk]
        self._save_state()
        self._refresh_table()
        self._refresh_plugins_tab()
        self.tabs.setTabText(0, f"📊 Araç Paneli ({len(self.tools)})")
        self.tabs.setCurrentIndex(0)
        self.set_status(f"📚 {info['name']} kütüphaneye ve ana panele eklendi!")
