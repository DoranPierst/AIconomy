<p align="center">
  <img src="assets/aiconomy.png" alt="AIconomy Logo" width="112" />
</p>

<h1 align="center">AIconomy</h1>

<p align="center">
  A minimalist native Windows desktop control center (PySide6 / Qt 6) for managing MCP servers, AI coding client configs, skill packs, local GPU/3D bridges, and context token budgets from one place.
</p>

<p align="center">
  <a href="https://github.com/DoranPierst/AIconomy/releases/latest"><img src="https://img.shields.io/github/v/release/DoranPierst/AIconomy?style=flat-square" alt="Latest Release" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4?style=flat-square" alt="Windows 10/11" />
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square" alt="Python 3.11+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-22C55E?style=flat-square" alt="MIT License" /></a>
</p>

<p align="center">
  <img src="assets/screenshot_dark.png" alt="AIconomy Dark Mode Interface" width="960" />
</p>

---

## Download (Windows 10 / 11)

No Python installation required:

1. Download **`AIconomy.exe`** from the [**Latest Release**](https://github.com/DoranPierst/AIconomy/releases/latest).
2. Double-click `AIconomy.exe` to launch.
3. Click the version badge in the footer (or **More menu -> Check for App Updates**) anytime to pull future GitHub releases automatically.

> **Windows SmartScreen note:** `AIconomy.exe` is currently unsigned, so Windows Defender SmartScreen may show a warning on first run (**More info** -> **Run anyway**). You can also inspect the source and build the executable locally with `build_exe.bat`.

---

## Key Features

- **Passive Startup & Locked Start/Stop Control:** Opens with zero unsolicited background server spawns; a single bidirectional **Start Tools** / **Stop Tools** button stays safely locked until managed processes (`psutil.wait_procs`) and local TCP ports settle.
- **Unified Per-Client MCP Matrix (`AGY / CDX / CLD / CUR`):** Enable or disable MCP servers, CLI tools, rules, and skill packs per AI client (**Google Antigravity**, **OpenAI Codex**, **Claude Code**, **Cursor**), with automatic Windows `cmd /c npx` wrapping and uninstalled-client dimming.
- **Curated 100-Tool Library with On-Demand Install:** Keep your **Tools** workspace lean (`14` installed starter tools) and browse **86** additional verified Windows-compatible MCP/Skill/Rule entries in **Plugins** — library entries stay uninstalled on disk until you click **Download & Install**.
- **General + App-Specific Scoped Tags & `+ Create Profile` Wizard:** Distinguishes general software tags (`Coding & LSP`, `Testing & QA`) from host-specific tags (`Unity: Testing & QA`, `Blender: 3D Modeling`, `Chrome: Testing & QA`) with dynamic per-app rows in **+ Create Profile** and calm muted colors that glow only when selected.
- **Interactive Token Usage Breakdown:** Click the footer token badge anytime to inspect per-client 200K context load, per-tool schema share bars, **Token Saver** vs **Capability Schema** classifications, and live tool toggles.
- **Dynamic Windows DPAPI Key Vault:** API key fields appear automatically in **Settings -> API Keys** whenever you add a key-backed tool to your workspace, encrypted at rest via Windows `CryptProtectData`.
- **Diagnostics Center & SQLite Logs:** Run live end-to-end MCP handshakes (`initialize`, Blender socket, `stdio` JSON-RPC), release stuck local ports safely, reset individual tools to factory defaults, and export structured AI troubleshooting prompts.
- **100% English & Turkish UI:** Full live language switching with Windows OS locale auto-detection, Dark and Light themes (updated screenshot below), and system tray controls.

---

## Files AIconomy Modifies

When you toggle tools or change scopes, AIconomy updates **only its own managed entries** inside the AI client configs below using atomic writes. A `.bak` backup is written before any modification, and untouched files are never rewritten:

| Client | Configuration File(s) |
|---|---|
| Google Antigravity | `%USERPROFILE%\.gemini\config\mcp_config.json` |
| OpenAI Codex | `%USERPROFILE%\.codex\config.toml` (marked `# >>> BEGIN AICONOMY >>>` block) |
| Claude Code | `%USERPROFILE%\.claude.json`, `<project>\.mcp.json` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json`, `<project>\.cursor\mcp.json` |

### Data Storage & Portable Mode

- Application state (`aiconomy-state.json`), SQLite logs (`aiconomy.db`), and encrypted API keys (`aiconomy-vault.dpapi.json`) are stored in `%LOCALAPPDATA%\AIconomy\data`.
- Existing files from earlier versions (`hub_state.json`, `ai_hub_logs.db`, `vault.dpapi.json`) are migrated non-destructively on first launch.
- To run in **portable mode**, create an empty `portable.txt` file next to `AIconomy.exe` to store data in a local `data\` folder beside the executable.

### Security & API Keys

- API keys entered in **Settings -> API Keys** are encrypted at rest on disk using Windows DPAPI (`CryptProtectData`, scoped to the current Windows user account).
- **Plaintext-on-sync notice:** When a tool that requires an API key is enabled and synced to an AI client, that key is written **in plain text** into the enabled client's MCP config file listed above, because MCP clients read environment variables directly from those config files.

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

Released under the [MIT License](LICENSE). See [CHANGELOG.md](CHANGELOG.md) for release history.
