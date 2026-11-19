"""Persistent SQLite log store, Windows DPAPI encrypted vault, and application state persistence."""
from __future__ import annotations

import base64
import contextlib
import ctypes
import ctypes.wintypes as wintypes
import datetime as dt
import json
import pathlib
import shutil
import sqlite3
from typing import Any

from .catalog import (
    CheckOption,
    DEFAULT_ACTIVE_BLENDER_SKILLS,
    ToolSpec,
    default_projects_map,
    normalize_tool_kind,
)

STATE_FILENAME = "aiconomy-state.json"
LOG_DB_FILENAME = "aiconomy.db"
VAULT_FILENAME = "aiconomy-vault.dpapi.json"

_LEGACY_FILES: tuple[tuple[str, str], ...] = (
    ("hub_state.json", STATE_FILENAME),
    ("ai_hub_logs.db", LOG_DB_FILENAME),
    ("vault.dpapi.json", VAULT_FILENAME),
)


def migrate_legacy_data_files(data_dir: pathlib.Path) -> None:
    """Copy legacy v1.3.x data filenames to clean AIconomy filenames once (non-destructive)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    for old_name, new_name in _LEGACY_FILES:
        old_p = data_dir / old_name
        new_p = data_dir / new_name
        if old_p.is_file() and not new_p.exists():
            try:
                shutil.copy2(old_p, new_p)
            except OSError:
                continue


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


class WindowsDpapiVault:
    """Windows session-scoped CryptProtectData (DPAPI) encrypted API key vault."""

    STANDARD_KEYS: list[tuple[str, str]] = [
        ("MESHY_API_KEY", "set_key_meshy"),
        ("ELEVENLABS_API_KEY", "set_key_elevenlabs"),
        ("GITHUB_TOKEN", "set_key_github"),
        ("CONTEXT7_API_KEY", "set_key_context7"),
    ]

    def __init__(self, vault_file: pathlib.Path) -> None:
        self.vault_file = vault_file
        self.vault_file.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _protect(raw_text: str) -> str:
        data = raw_text.encode("utf-8")
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            "AIconomyVault",
            None,
            None,
            None,
            0x01,  # CRYPTPROTECT_UI_FORBIDDEN
            ctypes.byref(blob_out),
        )
        if not ok:
            raise OSError("Windows DPAPI encryption failed.")
        try:
            encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return base64.b64encode(encrypted).decode("ascii")
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    @staticmethod
    def _unprotect(cipher_b64: str) -> str:
        raw = base64.b64decode(cipher_b64.encode("ascii"))
        buf = ctypes.create_string_buffer(raw, len(raw))
        blob_in = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0x01,
            ctypes.byref(blob_out),
        )
        if not ok:
            raise OSError("Windows DPAPI decryption failed.")
        try:
            plain = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return plain.decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def _read_map(self) -> dict[str, str]:
        if not self.vault_file.is_file():
            return {}
        try:
            return json.loads(self.vault_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def set_secret(self, key_name: str, secret_value: str) -> None:
        data = self._read_map()
        cleaned = secret_value.strip()
        if not cleaned:
            data.pop(key_name, None)
        else:
            data[key_name] = self._protect(cleaned)
        self.vault_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_secret(self, key_name: str) -> str:
        data = self._read_map()
        enc = data.get(key_name)
        if not enc:
            return ""
        try:
            return self._unprotect(enc)
        except Exception:
            return ""

    def has_secret(self, key_name: str) -> bool:
        return bool(self.get_secret(key_name))

    def list_masked(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for k in self._read_map():
            val = self.get_secret(k)
            if val:
                prefix = val[:4] if len(val) >= 8 else val[:2]
                out[k] = f"{prefix}{'*' * 12}"
        return out


class LogDatabase:
    """Persistent SQLite log store for errors, warnings, and operational events."""

    def __init__(self, db_path: pathlib.Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> contextlib.AbstractContextManager[sqlite3.Connection]:
        return contextlib.closing(sqlite3.connect(self.db_path))

    def _init_db(self) -> None:
        with self._connect() as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    level TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    raw_detail TEXT NOT NULL,
                    port INTEGER
                )
                """
            )
            cur = conn.execute("SELECT COUNT(*) FROM logs")
            if cur.fetchone()[0] == 0:
                now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO logs (ts, level, tool, summary, raw_detail, port) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        now,
                        "INFO",
                        "AIconomy",
                        "AIconomy initialized.",
                        "SQLite log database and Windows DPAPI vault ready.",
                        None,
                    ),
                )

    def add(self, level: str, tool: str, summary: str, raw_detail: str = "", port: int | None = None) -> None:
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn, conn:
            conn.execute(
                "INSERT INTO logs (ts, level, tool, summary, raw_detail, port) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, level, tool, summary, raw_detail or summary, port),
            )

    def clear(self) -> None:
        with self._connect() as conn, conn:
            conn.execute("DELETE FROM logs")

    def query(self, level: str = "ALL", tool: str = "ALL", search: str = "", limit: int = 200) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if level != "ALL":
            clauses.append("level = ?")
            params.append(level)
        if tool != "ALL":
            clauses.append("tool = ?")
            params.append(tool)
        if search.strip():
            clauses.append("(LOWER(summary) LIKE ? OR LOWER(raw_detail) LIKE ? OR LOWER(tool) LIKE ?)")
            q = f"%{search.strip().lower()}%"
            params.extend([q, q, q])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT id, ts, level, tool, summary, raw_detail, port FROM logs {where} ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": r[0],
                "ts": r[1],
                "level": r[2],
                "tool": r[3],
                "summary": r[4],
                "raw_detail": r[5],
                "port": r[6],
            }
            for r in rows
        ]

    def latest_issue_for_tool(self, tool_name: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT level, summary FROM logs WHERE tool = ? AND level IN ('ERR', 'WARN') ORDER BY id DESC LIMIT 1",
                (tool_name,),
            ).fetchone()
        return f"[{row[0]}] {row[1]}" if row else ""

    def counts_by_level(self) -> dict[str, int]:
        out = {"ERR": 0, "WARN": 0, "INFO": 0, "DBG": 0}
        with self._connect() as conn:
            for lvl, cnt in conn.execute("SELECT level, COUNT(*) FROM logs GROUP BY level"):
                out[lvl] = cnt
        return out


class StateStore:
    """Persist tool states, 94 Blender skills, profiles, projects, and user preferences."""

    def __init__(self, state_file: pathlib.Path) -> None:
        self.state_file = state_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    @property
    def has_saved_state(self) -> bool:
        return self.state_file.is_file()

    def load_into(self, tools: list[ToolSpec]) -> tuple[set[str], dict[str, Any]]:
        active_skills = set(DEFAULT_ACTIVE_BLENDER_SKILLS)
        meta: dict[str, Any] = {
            "theme": "dark",
            "minimize_to_tray": True,
            "auto_detect_apps": True,
            "first_run_dismissed": False,
            "projects": default_projects_map(),
            "plugin_checked_ids": [],
            "checked_blender_skills": [],
            "sort_key": "enabled",
            "sort_desc": True,
            "active_profile": "",
            "custom_presets": {},
        }
        if not self.state_file.is_file():
            return active_skills, meta
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return active_skills, meta

        # Existing users who already had a state file shouldn't see the first-run welcome banner
        meta["first_run_dismissed"] = True

        if isinstance(raw.get("active_blender_skills"), list):
            active_skills = set(raw["active_blender_skills"])
        saved_meta = raw.get("meta", {})
        saved_projs = saved_meta.get("projects", {})
        merged_projs = default_projects_map()
        if isinstance(saved_projs, dict):
            for k, v in saved_projs.items():
                if pathlib.Path(str(v)).exists():
                    merged_projs[str(k)] = str(v)
        meta.update(saved_meta)
        meta["projects"] = merged_projs

        # Migrate legacy sort_key values -> "enabled"
        if meta.get("sort_key") in ("usage", "mode"):
            meta["sort_key"] = "enabled"

        # Migrate legacy list active_profiles -> single active_profile key if empty
        if not meta.get("active_profile") and isinstance(meta.get("active_profiles"), list):
            ap = meta["active_profiles"]
            if len(ap) == 1:
                meta["active_profile"] = f"builtin:{ap[0]}"

        _legacy_prof_map = {
            "builtin:unity_game": "builtin:unity_shader",
            "builtin:asset_3d": "builtin:modeling_3d",
            "builtin:web_release": "builtin:web_security",
            "builtin:zero_token": "builtin:token_saver_only",
        }
        cur_ap = str(meta.get("active_profile") or "")
        if cur_ap in _legacy_prof_map:
            meta["active_profile"] = _legacy_prof_map[cur_ap]

        by_id = {t.id: t for t in tools}
        for tid, tdata in raw.get("tools", {}).items():
            if tid in by_id:
                t = by_id[tid]
                if "in_workspace" in tdata:
                    t.in_workspace = bool(tdata["in_workspace"])
                if "installed" in tdata:
                    t.installed = bool(tdata["installed"])
                elif t.in_workspace:
                    t.installed = True
                t.enabled = bool(tdata.get("enabled", t.enabled))
                if not t.in_workspace:
                    t.enabled = False
                if isinstance(tdata.get("clients"), dict):
                    t.clients.update({k: bool(v) for k, v in tdata["clients"].items()})
                if t.scope_selectable and "project_scope" in tdata:
                    sc = str(tdata["project_scope"])
                    t.project_scope = sc if (sc == "GLOBAL" or sc in merged_projs) else "GLOBAL"
                if t.modes:
                    t.mode_index = max(0, min(int(tdata.get("mode_index", t.mode_index)), len(t.modes) - 1))
                else:
                    t.mode_index = 0
                t.param_value = str(tdata.get("param_value", t.param_value))
                if t.id in ("serena", "unity_mcp", "blender_mcp") and t.param_value.isdigit():
                    p_int = int(t.param_value)
                    if 1 <= p_int <= 65535:
                        t.port = p_int
                t.version = str(tdata.get("version", t.version))
                opt_map = tdata.get("options", {})
                for opt in t.options:
                    if opt.key in opt_map:
                        opt.enabled = bool(opt_map[opt.key])
            elif tdata.get("_custom"):
                tools.append(
                    ToolSpec(
                        id=tid,
                        name=tdata["name"],
                        kind=normalize_tool_kind(tdata.get("kind", "stdio")),
                        version=tdata.get("version", "v1.0.0"),
                        repo_url=tdata.get("repo_url", ""),
                        schema_tokens=int(tdata.get("schema_tokens", 1800)),
                        summary=str(tdata.get("summary", "")),
                        details=str(tdata.get("details", "")),
                        when_to_use=str(tdata.get("when_to_use", "")),
                        enabled=bool(tdata.get("enabled", True)),
                        clients=tdata.get("clients", {"AGY": True, "CDX": True, "CLD": False, "CUR": False}),
                        scope_selectable=bool(tdata.get("scope_selectable", True)),
                        project_scope=str(tdata.get("project_scope", "GLOBAL")),
                        fixed_location_label=str(tdata.get("fixed_location_label", "")),
                        modes=tdata.get("modes", []),
                        mode_index=int(tdata.get("mode_index", 0)),
                        has_gear=bool(tdata.get("has_gear", False)),
                        param_label=tdata.get("param_label", ""),
                        param_value=tdata.get("param_value", ""),
                        param_help=tdata.get("param_help", ""),
                        param_arg_flag=str(tdata.get("param_arg_flag", "")),
                        param_env_var=str(tdata.get("param_env_var", "")),
                        vault_key_name=str(tdata.get("vault_key_name", "")),
                        vault_key_required=bool(tdata.get("vault_key_required", False)),
                        vault_key_desc=str(tdata.get("vault_key_desc", "")),
                        in_workspace=bool(tdata.get("in_workspace", True)),
                        installed=bool(tdata.get("installed", True)),
                        category=str(tdata.get("category", "coding_dev")),
                        install_cmd=tdata.get("install_cmd", ""),
                        mcp_server_key=tdata.get("mcp_server_key", tid),
                        mcp_command=tdata.get("mcp_command", ""),
                        mcp_args=tdata.get("mcp_args", []),
                        ai_question_hint=tdata.get(
                            "ai_question_hint",
                            "How should I optimize this tool's settings for my project?",
                        ),
                        tags=[str(x) for x in tdata.get("tags", ["automation"]) if x],
                        options=[
                            CheckOption(o["key"], o["label"], o["enabled"], o.get("help_text", ""))
                            for o in tdata.get("custom_options", [])
                        ],
                    )
                )
        return active_skills, meta

    def serialize(
        self, tools: list[ToolSpec], active_skills: set[str], meta: dict[str, Any], default_ids: set[str]
    ) -> dict[str, Any]:
        tools_dict: dict[str, Any] = {}
        for t in tools:
            entry: dict[str, Any] = {
                "name": t.name,
                "version": t.version,
                "in_workspace": bool(getattr(t, "in_workspace", True)),
                "installed": bool(getattr(t, "installed", getattr(t, "in_workspace", True))),
                "enabled": bool(t.enabled and getattr(t, "in_workspace", True)),
                "clients": dict(t.clients),
                "project_scope": t.project_scope,
                "mode_index": t.mode_index,
                "param_value": t.param_value,
                "options": {o.key: o.enabled for o in t.options},
            }
            if t.id not in default_ids:
                entry.update(
                    {
                        "_custom": True,
                        "kind": normalize_tool_kind(t.kind),
                        "category": getattr(t, "category", "coding_dev"),
                        "version": t.version,
                        "repo_url": t.repo_url,
                        "schema_tokens": t.schema_tokens,
                        "summary": t.summary,
                        "details": t.details,
                        "when_to_use": t.when_to_use,
                        "scope_selectable": t.scope_selectable,
                        "fixed_location_label": t.fixed_location_label,
                        "modes": t.modes,
                        "has_gear": t.has_gear,
                        "param_label": t.param_label,
                        "param_value": t.param_value,
                        "param_help": t.param_help,
                        "param_arg_flag": getattr(t, "param_arg_flag", ""),
                        "param_env_var": getattr(t, "param_env_var", ""),
                        "vault_key_name": t.vault_key_name,
                        "vault_key_required": t.vault_key_required,
                        "vault_key_desc": getattr(t, "vault_key_desc", ""),
                        "install_cmd": t.install_cmd,
                        "mcp_server_key": t.mcp_server_key,
                        "mcp_command": t.mcp_command,
                        "mcp_args": t.mcp_args,
                        "tags": list(t.tags),
                        "custom_options": [
                            {"key": o.key, "label": o.label, "enabled": o.enabled, "help_text": o.help_text}
                            for o in t.options
                        ],
                    }
                )
            tools_dict[t.id] = entry
        return {
            "exported_at": dt.datetime.now().isoformat(timespec="seconds"),
            "active_blender_skills": sorted(active_skills),
            "meta": meta,
            "tools": tools_dict,
        }

    def save(
        self, tools: list[ToolSpec], active_skills: set[str], meta: dict[str, Any], default_ids: set[str]
    ) -> None:
        payload = self.serialize(tools, active_skills, meta, default_ids)
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
