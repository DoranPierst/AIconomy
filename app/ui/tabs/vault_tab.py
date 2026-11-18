"""Encrypted API Vault tab mixin (moved into Settings in Phase 3)."""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ...storage import WindowsDpapiVault


class VaultTabMixin:
    """Mixin implementing Tab 3 (Encrypted Vault)."""

    def _init_vault_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        vault_info = QLabel(
            "<b>🔐 Windows DPAPI Şifreli Anahtar Kasası</b> — Girilen anahtarlar bu programın veri klasöründe açık metin olarak "
            "saklanmaz; Windows kullanıcı oturumunuzla (CryptProtectData) şifrelenir.<br>"
            "<span style='color:#f59e0b;'><b>Not:</b> Anahtar gerektiren bir MCP aracı AÇIK olduğunda, AI istemcilerinin (Antigravity, "
            "Codex, Claude Code, Cursor) okuyabilmesi için anahtar ilgili config dosyasına (mcp_config.json, config.toml, "
            ".claude.json, mcp.json) <b>düz metin</b> olarak yazılır. Bu, MCP istemcilerinin çalışma biçiminden kaynaklanır.</span>"
        )
        vault_info.setWordWrap(True)
        lay.addWidget(vault_info)
        self.vault_inputs: dict[str, QLineEdit] = {}
        for key_name, desc in WindowsDpapiVault.STANDARD_KEYS:
            card = QFrame()
            card.setObjectName("card")
            r = QHBoxLayout(card)
            lbl = QLabel(f"<b>{key_name}</b><br><span style='color:#94a3b8;'>{desc}</span>")
            lbl.setFixedWidth(360)
            r.addWidget(lbl)

            inp = QLineEdit()
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            inp.setPlaceholderText("Anahtarı yapıştırın (boş bırakıp kaydederseniz silinir)...")
            self.vault_inputs[key_name] = inp
            r.addWidget(inp, stretch=1)

            btn_save = QPushButton("💾 Şifrele & Kaydet")
            btn_save.setObjectName("primaryBtn")
            btn_save.clicked.connect(lambda _=False, k=key_name: self._save_vault_key(k))
            r.addWidget(btn_save)
            lay.addWidget(card)

        lay.addStretch()
        self.tabs.addTab(tab, "🔐 Şifreli Kasa")

    def _refresh_vault_tab(self) -> None:
        for k, inp in self.vault_inputs.items():
            existing = self.vault.get_secret(k)
            inp.setText(existing)

    def _save_vault_key(self, key_name: str) -> None:
        val = self.vault_inputs[key_name].text()
        self.vault.set_secret(key_name, val)
        self.logs.add("INFO", "Şifreli Kasa", f"{key_name} Windows DPAPI ile güncellendi.")
        self.set_status(f"🔐 {key_name} şifreli kasaya kaydedildi.")
        self._refresh_logs_tab()
