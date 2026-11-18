# Changelog

All notable changes to **AIconomy** are documented in this file.

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
