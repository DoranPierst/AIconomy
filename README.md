<p align="center">
  <img src="assets/aiconomy.png" alt="AIconomy Logo" width="112" />
</p>

<h1 align="center">AIconomy</h1>

<p align="center">
  Native Windows desktop control center (PySide6 / Qt 6) for managing MCP servers, AI coding client configs, Browser OAuth &amp; zero-plaintext DPAPI credentials, skill packs, and context token budgets from one place.
</p>

<p align="center">
  <a href="https://github.com/DoranPierst/AIconomy/releases/latest"><img src="https://img.shields.io/github/v/release/DoranPierst/AIconomy?style=flat-square" alt="Latest Release" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4?style=flat-square" alt="Windows 10/11" />
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square" alt="Python 3.11+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-22C55E?style=flat-square" alt="MIT License" /></a>
</p>

<p align="center">
  <img src="assets/screenshot_dark.png" alt="AIconomy Interface" width="960" />
</p>

---

## Download (Windows 10 / 11)

No Python installation required:

1. Download **`AIconomy.exe`** from the [**Latest Release**](https://github.com/DoranPierst/AIconomy/releases/latest).
2. Double-click `AIconomy.exe` to launch.
3. Click the version badge in the footer (or **More menu -> Check for updates**) anytime to check and apply future GitHub releases automatically.

> **Windows SmartScreen note:** `AIconomy.exe` is currently unsigned, so Windows Defender SmartScreen may show a warning on first run (**More info** -> **Run anyway**). You can also inspect the source and build the executable locally with `build_exe.bat`.

---

## Key Features

- **Passive Startup & Locked Start/Stop Control:** Opens with zero unsolicited background server spawns; a single bidirectional **Start Tools** / **Stop Tools** button stays safely locked until managed processes (`psutil.wait_procs`) and local TCP ports settle.
- **Unified Per-Client MCP Matrix (`AGY / CDX / CLD / CUR`):** Enable or disable MCP servers, CLI tools, rules, and skill packs per AI client (**Google Antigravity**, **OpenAI Codex**, **Claude Code**, **Cursor**), with automatic Windows `cmd /c npx` wrapping and uninstalled-client dimming.
- **Curated 100-Tool Library with On-Demand Install:** Keep your **Tools** workspace lean (`14` starter tools) and browse **86** additional verified Windows-compatible MCP, Skill, and Rule entries in **Plugins** — library entries remain uninstalled on disk until you click **Download & Install**.
- **Zero-Plaintext `--mcp-exec` RAM Bridge & Optional Vault PIN:** API keys are encrypted at rest via Windows DPAPI (`CryptProtectData`) with an optional `600,000`-iteration `PBKDF2-HMAC-SHA256` Master Passphrase, and injected solely into child process RAM at launch — **raw secrets are never written to `.json` or `.toml` AI client config files**.
- **Keyless Browser OAuth 2.1 & Official CLI Sign-In:** Connect supported services (**Cloudflare**, **Linear**, **Sentry**, **Notion**, **Atlassian**, **Supabase**, **Netlify**, **Stripe** via `mcp-remote`, plus **GitHub**, **Azure**, **Google Cloud**, **Snyk**, and **Railway** CLI OAuth) directly through your browser without copying static API tokens.
- **General + App-Specific Scoped Tags & `+ Create Profile` Wizard:** Separates general software tags (`Coding & LSP`, `Testing & QA`) from host-specific tags (`Unity: Testing & QA`, `Blender: 3D Modeling`, `Chrome: Testing & QA`) with dynamic per-app rows in **+ Create Profile** and calm muted colors that glow only when selected.
- **Interactive Live Token Usage Breakdown:** Click the footer token badge anytime to inspect per-client 200K context load, live **`tools/list` Measured** vs **Estimated** schema badges, **Token Saver** vs **Capability Schema** classifications, and instant tool toggles.
- **Supply-Chain Armor & SHA-256 Self-Updater:** Pinned npm/PyPI versions (zero `@latest`), `npm install --ignore-scripts`, GitHub-to-npm/PyPI ownership verification against typosquatting, and a locked official self-updater with mandatory GitHub `sha256` digest verification.
- **Zero-Subprocess `nvml.dll` VRAM, Adaptive Tray Sleep & True Uninstall:** Reads NVIDIA GPU VRAM directly via `nvml.dll` (`ctypes`, `<0.1ms`), sleeps at 60s intervals when minimized to the system tray, auto-stops local HTTP MCP ports when AI editors close (optional), and offers both **Hide from Tools Only** and **Uninstall from PC**.
- **Diagnostics Center & Auto-Redacted SQLite Logs:** Run live end-to-end MCP handshakes (`initialize`, Blender socket, `stdio` JSON-RPC), release stuck local ports safely, reset individual tools to factory defaults, and export structured AI troubleshooting prompts with automatic token/secret redaction.
- **100% English & Turkish UI:** Full live language switching with Windows OS locale auto-detection, Dark and Light themes, and system tray controls.

---

## Files AIconomy Modifies

When you toggle tools or change scopes, AIconomy updates **only its own managed entries** inside the AI client configs below using serialized atomic writes. A `.bak` backup is created before any modification, and unchanged files are never touched:

| Client | Configuration File(s) |
|---|---|
| Google Antigravity | `%USERPROFILE%\.gemini\config\mcp_config.json` |
| OpenAI Codex | `%USERPROFILE%\.codex\config.toml` (marked `# >>> BEGIN AICONOMY >>>` block) |
| Claude Code | `%USERPROFILE%\.claude.json`, `<project>\.mcp.json` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json`, `<project>\.cursor\mcp.json` |

### Data Storage & Portable Mode

- Application state (`aiconomy-state.json`), auto-redacted SQLite logs (`aiconomy.db`), and encrypted credentials (`aiconomy-vault.dpapi.json`) are stored in `%LOCALAPPDATA%\AIconomy\data`.
- To run in **portable mode**, create an empty `portable.txt` file next to `AIconomy.exe` to store data in a local `data\` folder beside the executable.

### Security Architecture

- **Zero Plaintext on Disk:** Credential-backed `stdio` MCP servers are registered in AI client config files via the native zero-extraction `aiconomy-bridge` launcher (`--mcp-exec <tool_id>`), resolving secrets strictly in memory at launch (`<85ms` warm start, zero `_MEI*` bundle extraction) while scrubbing unrelated sensitive environment variables from child MCP processes.
- **DPAPI + Optional Master Passphrase:** Secrets are protected by Windows `CryptProtectData` tied to your Windows user account, with an optional **Vault Master Passphrase / PIN** (`PBKDF2-HMAC-SHA256`, `600,000` iterations) in **Settings -> API Keys** so other processes in the same session cannot decrypt the vault without your PIN.
- **Automatic Secret Redaction & Kernel-Verified IPC:** Known API token formats (`sk-...`, `ghp_...`, `github_pat_...`, `ntn_...`, `sntryu_...`, `Bearer ...`) and stored vault values are automatically masked (`***REDACTED***`) before touching SQLite logs or diagnostic prompts, and the single-instance local pipe is restricted to the current Windows user (`UserAccessOption`) with Win32 kernel peer PID/path verification (`GetNamedPipeClientProcessId`) on single-secret resolution.

---

## Running from Source / Building Standalone EXE

Requires **Windows 10/11**, **Python 3.11+**, and [**uv**](https://docs.astral.sh/uv/).

```powershell
uv sync
uv run python main.py
```

- Double-click `start.bat` to launch from source without a console window.
- Double-click `build_exe.bat` to build a standalone `dist\AIconomy.exe` via PyInstaller.

---

## License

Copyright (c) 2026 [DoranPierst](https://github.com/DoranPierst). Released under the [MIT License](LICENSE). See [CHANGELOG.md](CHANGELOG.md) for release history.
