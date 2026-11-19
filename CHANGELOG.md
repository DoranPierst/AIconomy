# Changelog

All notable changes to **AIconomy** are documented in this file.

## [1.5.0] - 2026-11-19

Major feature, UX, and catalog release introducing passive runtime control, a curated 100-tool library with zero auto-downloads, interactive token share analytics, task-driven profile creation, and dynamic DPAPI key management.

### Runtime Control & Real Settings Wiring
- **Passive Startup & Locked Start/Stop Control:** AIconomy never auto-starts background servers on launch. A single bidirectional top-bar and tray button (**Start Tools** green <-> **Stop Tools** amber) locks during transitions until `psutil.wait_procs` and TCP port release checks finish cleanly.
- **100% Real CLI, Env & Disk Settings:** Removed all placeholder modes and options; wired real runtime behaviors including **Caveman** disk rule toggling and `Lite/Full/Ultra` compression directives, **Serena** `--mode` / `--port` / `--open-web-dashboard False`, **Chrome DevTools** `--headless` / `--isolated`, **Blender MCP** `BLENDER_PORT`, **ElevenLabs** `ELEVENLABS_MCP_OUTPUT_PATH`, and declarative `param_arg_flag` / `param_env_var` bindings across library tools.
- **Windows `cmd /c npx` Compatibility & API Key Guard:** Wraps `npx` stdio MCP servers with `cmd /c npx` on Windows to prevent `spawn npx ENOENT` errors in Claude Code and Cursor, flags missing required API keys (`API key missing`) instead of falsely reporting `Ready`, dims uninstalled AI clients, and adds per-tool **Reset to Defaults**.

### Token Analytics, Priority Tags & Task Profile Wizard
- **Clickable Token Usage Breakdown:** Clicking the footer token badge opens an interactive breakdown dialog showing per-client 200K context load (`AGY`, `CDX`, `CLD`, `CUR`), aligned percentage share bars, **Token Saver** vs **Capability Schema** roles, and instant inline toggles.
- **Priority-Ordered 18-Color Capability Tags:** Every tool's tags are ordered strictly by core capability (e.g. `3D Modeling` first on Blender, `Unity` first on Unity MCP, `Shader & GPU` first on RenderDoc, `Coding & LSP` first on Serena, `Token Saver` first on Caveman), with 18 distinct muted semantic colors that **glow only when selected from the top profile, tag filter, or profile wizard**.
- **`+ Create Profile` Task Wizard & Refreshed Profiles:** Select what you are working on by tag to auto-filter matching tools (from your workspace or all 100 library tools), preview live schema token impact, and save/apply custom profiles in one click, alongside 5 refreshed built-in profiles and 6 Blender 94-skill subgroups.

### Curated 100-Tool Library & Dynamic DPAPI Vault
- **Two-Tier Workspace + 100 Curated Tools (Zero Downloads):** `Tools` displays only your active workspace tools (`14` starter tools out of the box), while `Plugins` offers a searchable, category/tag/status-filterable library of **100** Windows-compatible MCP/Skill/Rule tools across 10 categories. Clicking **+ Add to Workspace** adds the config definition with **zero background package downloads**.
- **Dynamic Windows DPAPI Vault:** `Settings > API Keys` automatically surfaces encrypted DPAPI inputs in a scrollable view for any workspace tool that supports an API key while preserving previously saved keys.

## [1.4.0] - 2026-11-19

Major public-release overhaul focused on reliability, minimalist UX, modular architecture, and 100% English + Turkish localization.

### UI & UX Redesign
- **Streamlined 3-Tab Layout:** Consolidated 5 tabs into **Tools**, **Plugins**, and **Logs**, moving API Keys, Projects, Appearance, Language, Tray behavior, and Backup/Restore into a tabbed **Settings** dialog and moving E2E tests + Stuck Port cleanup into a unified **Diagnostics** dialog.
- **Emoji-Free Minimalist Interface:** Replaced all UI emojis with crisp HiDPI `QPainter` vector icons, subtle status dots (`StatusBadgeWidget`), custom `ToggleSwitch` controls, and anti-aliased chevron dropdown arrows across Dark and Light themes.
- **Unified Profile Selector:** Replaced redundant quick-preset buttons with a single top-bar **Profile** dropdown covering built-in profiles (`Unity & Shader`, `3D Assets`, `Web`, `Minimal`) and user-saved custom profiles, plus a **Manage Profiles** dialog with JSON export/import.
- **Cleaner 6-Column Tools Matrix:** Removed the non-live Usage column, added clickable inline update pills (`v1.0.8 -> v2.3.0`), double-click detail view, right-click context menu, and a dismissible first-run welcome banner with neutral out-of-the-box defaults.
- **Localized System Tray:** Added full English/Turkish tray menu translation and a configurable **Minimize to system tray on close** preference.

### Reliability, Safety & Architecture
- **Managed-Only Process Control:** Stopping Unity MCP or Serena now targets only explicitly managed executables and command lines instead of killing arbitrary services on port `:8080` or `:9121`.
- **Serialized Atomic Config Sync:** Debounced background config writer with an in-process lock, atomic temp-file writes, no-op skipping, and automatic `.bak` backups before any change.
- **Reliable Single-Instance IPC:** Replaced window-title lookup with `QLocalServer` + per-session named mutex so second launches focus the existing window regardless of UI language.
- **Non-Blocking Background Workers & Thread Safety:** Moved `nvidia-smi` VRAM polling and DCC detection off the UI thread, guarded concurrent scans, and isolated worker threads with deep-copy snapshots and Qt signal delivery.
- **Windows AppData Storage & Non-Destructive Migration:** Stores state, SQLite logs, and DPAPI key vault in `%LOCALAPPDATA%\AIconomy\data` (`aiconomy-state.json`, `aiconomy.db`, `aiconomy-vault.dpapi.json`), with automatic one-time migration from legacy filenames and optional `portable.txt` opt-in.
- **Modular Codebase:** Split `app/system_ops.py` into `processes`, `host_apps`, `mcp_config`, `plugins`, and `diagnostics`, and split `app/main_window.py` into `app/ui/{theme,icons,widgets,workers,main_window}`, `app/ui/tabs/*`, and `app/ui/dialogs/*`.

### Localization & Repo Hygiene
- **100% English & Turkish Parity:** Removed 6 incomplete machine-translated languages and verified exact 1:1 key parity across all UI tabs, dialogs, backend status/error messages, catalog descriptions, and 94 Blender skill entries.
- **Tag-Only Release Workflow:** Updated `.github/workflows/release.yml` to build and publish releases exclusively on `v*` tags and `workflow_dispatch`.
- **Transparent Security Disclosure:** Explicitly documents that API keys are encrypted at rest via Windows DPAPI and written to enabled AI client config files only when synced.

## [1.3.0 - 1.3.3] - 2026-11-18

- Rebranded from legacy name to **AIconomy** with new transparent vector-style `.ico` / `.png` icon and explicit Windows `AppUserModelID`.
- Added in-app GitHub Releases self-updater and standalone PyInstaller `.exe` packaging.

## [1.0.0 - 1.2.x] - 2026-11-17

- Initial PySide6 desktop manager for MCP servers, AI client config sync (`AGY`, `CDX`, `CLD`, `CUR`), 94 Blender skills toggle manager, SQLite diagnostic logs, and Windows DPAPI API key vault.
