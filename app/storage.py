"""Kalıcı SQLite Log Veritabanı, Windows DPAPI Şifreli Kasa ve Durum/Yedek Yönetimi."""
from __future__ import annotations

import base64
import contextlib
import ctypes
import ctypes.wintypes as wintypes
import datetime as dt
import json
import pathlib
import sqlite3
from typing import Any

from .catalog import CheckOption, DEFAULT_ACTIVE_BLENDER_SKILLS, ToolSpec, default_projects_map


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


class WindowsDpapiVault:
    """Windows kullanıcı oturumuna özel CryptProtectData (DPAPI) şifreli anahtar kasası."""

    STANDARD_KEYS: list[tuple[str, str]] = [
        ("MESHY_API_KEY", "Meshy 3D Bulut API Anahtarı"),
        ("ELEVENLABS_API_KEY", "ElevenLabs Ses & SFX API Anahtarı"),
        ("GITHUB_TOKEN", "GitHub Kişisel Erişim Anahtarı ( Yüksek API Limiti )"),
        ("CONTEXT7_API_KEY", "Context7 Docs API Anahtarı (İsteğe Bağlı)"),
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
            "AIAracMerkeziVault",
            None,
            None,
            None,
            0x01,  # CRYPTPROTECT_UI_FORBIDDEN
            ctypes.byref(blob_out),
        )
        if not ok:
            raise OSError("Windows DPAPI şifreleme başarısız oldu.")
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
            raise OSError("Windows DPAPI şifre çözme başarısız oldu.")
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
                out[k] = f"{prefix}{'•' * 12}"
        return out


class LogDatabase:
    """Kalıcı SQLite hata, uyarı ve debug geçmişi."""

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
                        "Sistem",
                        "AI Araç & Token Ekonomisi Kontrol Merkezi başlatıldı.",
                        "SQLite log veritabanı ve Windows DPAPI şifreli kasa aktif.",
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
    """Araç durumları, 94 Blender Skill seçimi ve Export / Import ayar yönetimi."""

    def __init__(self, state_file: pathlib.Path) -> None:
        self.state_file = state_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def load_into(self, tools: list[ToolSpec]) -> tuple[set[str], dict[str, Any]]:
        active_skills = set(DEFAULT_ACTIVE_BLENDER_SKILLS)
        meta: dict[str, Any] = {
            "theme": "dark",
            "auto_detect_apps": True,
            "spent_tokens_k": 342,
            "projects": default_projects_map(),
            "plugin_checked_ids": [t.id for t in tools if t.enabled],
            "checked_blender_skills": [],
            "sort_key": "usage",
            "sort_desc": True,
        }
        if not self.state_file.is_file():
            return active_skills, meta
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return active_skills, meta

        if isinstance(raw.get("active_blender_skills"), list):
            active_skills = set(raw["active_blender_skills"])
        saved_meta = raw.get("meta", {})
        saved_projs = saved_meta.get("projects", {})
        merged_projs = default_projects_map()
        if isinstance(saved_projs, dict):
            merged_projs.update({str(k): str(v) for k, v in saved_projs.items()})
        meta.update(saved_meta)
        meta["projects"] = merged_projs

        by_id = {t.id: t for t in tools}
        for tid, tdata in raw.get("tools", {}).items():
            if tid in by_id:
                t = by_id[tid]
                t.enabled = bool(tdata.get("enabled", t.enabled))
                if isinstance(tdata.get("clients"), dict):
                    t.clients.update({k: bool(v) for k, v in tdata["clients"].items()})
                if t.scope_selectable and "project_scope" in tdata:
                    t.project_scope = str(tdata["project_scope"])
                t.mode_index = int(tdata.get("mode_index", t.mode_index))
                t.param_value = str(tdata.get("param_value", t.param_value))
                t.version = str(tdata.get("version", t.version))
                t.usage_count = int(tdata.get("usage_count", t.usage_count))
                opt_map = tdata.get("options", {})
                for opt in t.options:
                    if opt.key in opt_map:
                        opt.enabled = bool(opt_map[opt.key])
            elif tdata.get("_custom"):
                tools.append(
                    ToolSpec(
                        id=tid,
                        name=tdata["name"],
                        kind=tdata.get("kind", "stdio MCP"),
                        version=tdata.get("version", "v1.0.0"),
                        repo_url=tdata.get("repo_url", ""),
                        schema_tokens=int(tdata.get("schema_tokens", 1800)),
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
                        install_cmd=tdata.get("install_cmd", ""),
                        mcp_server_key=tdata.get("mcp_server_key", tid),
                        mcp_command=tdata.get("mcp_command", ""),
                        mcp_args=tdata.get("mcp_args", []),
                        ai_question_hint=tdata.get("ai_question_hint", "Bu aracın ayarlarını projem için nasıl optimize etmeliyim?"),
                        options=[CheckOption(o["key"], o["label"], o["enabled"]) for o in tdata.get("custom_options", [])],
                    )
                )
        return active_skills, meta

    def serialize(self, tools: list[ToolSpec], active_skills: set[str], meta: dict[str, Any], default_ids: set[str]) -> dict[str, Any]:
        tools_dict: dict[str, Any] = {}
        for t in tools:
            entry: dict[str, Any] = {
                "name": t.name,
                "version": t.version,
                "enabled": t.enabled,
                "clients": dict(t.clients),
                "project_scope": t.project_scope,
                "mode_index": t.mode_index,
                "param_value": t.param_value,
                "usage_count": t.usage_count,
                "options": {o.key: o.enabled for o in t.options},
            }
            if t.id not in default_ids:
                entry.update(
                    {
                        "_custom": True,
                        "kind": t.kind,
                        "version": t.version,
                        "repo_url": t.repo_url,
                        "schema_tokens": t.schema_tokens,
                        "scope_selectable": t.scope_selectable,
                        "fixed_location_label": t.fixed_location_label,
                        "modes": t.modes,
                        "has_gear": t.has_gear,
                        "param_label": t.param_label,
                        "param_value": t.param_value,
                        "install_cmd": t.install_cmd,
                        "mcp_server_key": t.mcp_server_key,
                        "mcp_command": t.mcp_command,
                        "mcp_args": t.mcp_args,
                        "custom_options": [{"key": o.key, "label": o.label, "enabled": o.enabled} for o in t.options],
                    }
                )
            tools_dict[t.id] = entry
        return {
            "exported_at": dt.datetime.now().isoformat(timespec="seconds"),
            "active_blender_skills": sorted(active_skills),
            "meta": meta,
            "tools": tools_dict,
        }

    def save(self, tools: list[ToolSpec], active_skills: set[str], meta: dict[str, Any], default_ids: set[str]) -> None:
        payload = self.serialize(tools, active_skills, meta, default_ids)
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
