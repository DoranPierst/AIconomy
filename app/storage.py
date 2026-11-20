"""Persistent SQLite log store, Windows DPAPI encrypted vault, and application state persistence."""
from __future__ import annotations

import base64
import contextlib
import ctypes
import ctypes.wintypes as wintypes
import datetime as dt
import json
import os
import pathlib
import shutil
import sqlite3
import threading
import time
from typing import Any

from .catalog import (
    CheckOption,
    DEFAULT_ACTIVE_BLENDER_SKILLS,
    ToolSpec,
    default_projects_map,
    normalize_tool_kind,
)
from .security import auto_vault_key_for_tool, contains_embedded_secret, derive_vault_entropy, redact_secrets

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


def _atomic_write_text(path: pathlib.Path, content: str) -> None:
    """Atomically write UTF-8 text via a temporary sibling file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            with contextlib.suppress(OSError):
                os.fsync(fh.fileno())
        last_err: OSError | None = None
        for attempt in range(4):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError as exc:
                last_err = exc
                time.sleep(0.02 * (attempt + 1))
        if last_err is not None:
            raise last_err
    finally:
        with contextlib.suppress(OSError):
            if tmp_path.exists():
                tmp_path.unlink()


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


class WindowsDpapiVault:
    """Windows session-scoped CryptProtectData (DPAPI) encrypted API key vault with optional PBKDF2 PIN entropy."""

    META_KEY = "__vault_meta__"
    VERIFIER_PLAINTEXT = "AICONOMY_VAULT_OK_V1"

    STANDARD_KEYS: list[tuple[str, str]] = [
        ("MESHY_API_KEY", "set_key_meshy"),
        ("ELEVENLABS_API_KEY", "set_key_elevenlabs"),
        ("GITHUB_TOKEN", "set_key_github"),
        ("CONTEXT7_API_KEY", "set_key_context7"),
    ]

    def __init__(self, vault_file: pathlib.Path) -> None:
        self.vault_file = vault_file
        self.vault_file.parent.mkdir(parents=True, exist_ok=True)
        self._entropy: bytes | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _make_entropy_blob(entropy: bytes | None) -> tuple[Any, Any]:
        if not entropy:
            return None, None
        ebuf = ctypes.create_string_buffer(entropy, len(entropy))
        eblob = DATA_BLOB(len(entropy), ctypes.cast(ebuf, ctypes.POINTER(ctypes.c_char)))
        return ebuf, ctypes.byref(eblob)

    @classmethod
    def _protect(cls, raw_text: str, entropy: bytes | None = None) -> str:
        data = raw_text.encode("utf-8")
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        _ebuf, entropy_ptr = cls._make_entropy_blob(entropy)
        blob_out = DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            "AIconomyVault",
            entropy_ptr,
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

    @classmethod
    def _unprotect(cls, cipher_b64: str, entropy: bytes | None = None) -> str:
        raw = base64.b64decode(cipher_b64.encode("ascii"))
        buf = ctypes.create_string_buffer(raw, len(raw))
        blob_in = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        _ebuf, entropy_ptr = cls._make_entropy_blob(entropy)
        blob_out = DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            entropy_ptr,
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

    def _read_raw_doc(self) -> dict[str, Any]:
        with self._lock:
            if not self.vault_file.is_file():
                return {}
            for attempt in range(3):
                try:
                    doc = json.loads(self.vault_file.read_text(encoding="utf-8"))
                    return doc if isinstance(doc, dict) else {}
                except PermissionError:
                    if attempt < 2:
                        time.sleep(0.02 * (attempt + 1))
                        continue
                    return {}
                except Exception:
                    return {}
            return {}

    def _write_raw_doc(self, doc: dict[str, Any]) -> None:
        with self._lock:
            _atomic_write_text(self.vault_file, json.dumps(doc, indent=2))

    def _read_map(self) -> dict[str, str]:
        with self._lock:
            raw = self._read_raw_doc()
            return {k: v for k, v in raw.items() if not k.startswith("__") and isinstance(v, str)}

    def is_passphrase_enabled(self) -> bool:
        with self._lock:
            meta = self._read_raw_doc().get(self.META_KEY)
            return bool(isinstance(meta, dict) and meta.get("protected"))

    def is_locked(self) -> bool:
        with self._lock:
            return self.is_passphrase_enabled() and self._entropy is None

    def lock(self) -> None:
        with self._lock:
            self._entropy = None

    def unlock(self, passphrase: str) -> bool:
        with self._lock:
            doc = self._read_raw_doc()
            meta = doc.get(self.META_KEY)
            if not isinstance(meta, dict) or not meta.get("protected"):
                self._entropy = None
                return True
            if not passphrase:
                return False
            try:
                salt = base64.b64decode(str(meta["salt_b64"]).encode("ascii"))
                cand = derive_vault_entropy(passphrase, salt)
                plain = self._unprotect(str(meta["verifier"]), entropy=cand)
                if plain == self.VERIFIER_PLAINTEXT:
                    self._entropy = cand
                    return True
            except Exception:
                return False
            return False

    def unlock_with_entropy_hex(self, entropy_hex: str) -> bool:
        """Unlock in-memory using a hex entropy key received over the user-scoped IPC pipe."""
        with self._lock:
            doc = self._read_raw_doc()
            meta = doc.get(self.META_KEY)
            if not isinstance(meta, dict) or not meta.get("protected"):
                return True
            try:
                cand = bytes.fromhex(entropy_hex.strip())
                if self._unprotect(str(meta["verifier"]), entropy=cand) == self.VERIFIER_PLAINTEXT:
                    self._entropy = cand
                    return True
            except Exception:
                return False
            return False

    def export_entropy_hex(self) -> str:
        with self._lock:
            return self._entropy.hex() if self._entropy else ""

    def set_passphrase(self, new_passphrase: str, current_passphrase: str = "") -> bool:
        """Enable, change, or clear (when new_passphrase == '') the vault Master Passphrase."""
        with self._lock:
            if self.is_locked() and not self.unlock(current_passphrase):
                return False
            secret_map = self._read_map()
            decrypted: dict[str, str] = {}
            for k, enc in secret_map.items():
                try:
                    decrypted[k] = self._unprotect(enc, entropy=self._entropy)
                except Exception:
                    return False

            clean_new = new_passphrase.strip()
            new_doc: dict[str, Any] = {}
            if clean_new:
                salt = os.urandom(16)
                new_ent = derive_vault_entropy(clean_new, salt)
                new_doc[self.META_KEY] = {
                    "protected": True,
                    "salt_b64": base64.b64encode(salt).decode("ascii"),
                    "verifier": self._protect(self.VERIFIER_PLAINTEXT, entropy=new_ent),
                }
                for k, plain_val in decrypted.items():
                    if plain_val:
                        new_doc[k] = self._protect(plain_val, entropy=new_ent)
                self._entropy = new_ent
            else:
                for k, plain_val in decrypted.items():
                    if plain_val:
                        new_doc[k] = self._protect(plain_val, entropy=None)
                self._entropy = None

            self._write_raw_doc(new_doc)
            return True

    def has_key_entry(self, key_name: str) -> bool:
        """Return True when a cipher entry exists on disk (even while locked)."""
        with self._lock:
            return bool(key_name and key_name in self._read_map())

    def set_secret(self, key_name: str, secret_value: str) -> None:
        with self._lock:
            if self.is_locked():
                raise PermissionError("Vault is locked; unlock with Master Passphrase first.")
            doc = self._read_raw_doc()
            cleaned = secret_value.strip()
            if not cleaned:
                doc.pop(key_name, None)
            else:
                doc[key_name] = self._protect(cleaned, entropy=self._entropy)
            self._write_raw_doc(doc)

    def get_secret(self, key_name: str) -> str:
        with self._lock:
            if self.is_locked():
                return ""
            enc = self._read_map().get(key_name)
            if not enc:
                return ""
            try:
                return self._unprotect(enc, entropy=self._entropy)
            except Exception:
                return ""

    def has_secret(self, key_name: str) -> bool:
        with self._lock:
            if self.is_locked():
                return self.has_key_entry(key_name)
            return bool(self.get_secret(key_name))

    def all_unlocked_values(self) -> list[str]:
        with self._lock:
            if self.is_locked():
                return []
            vals: list[str] = []
            for k in self._read_map():
                v = self.get_secret(k)
                if v:
                    vals.append(v)
            return vals

    def list_masked(self) -> dict[str, str]:
        with self._lock:
            out: dict[str, str] = {}
            for k in self._read_map():
                if self.is_locked():
                    out[k] = f"locked{'*' * 10}"
                    continue
                val = self.get_secret(k)
                if val:
                    prefix = val[:4] if len(val) >= 8 else val[:2]
                    out[k] = f"{prefix}{'*' * 12}"
            return out


class LogDatabase:
    """Persistent SQLite log store for errors, warnings, and operational events (auto-redacts secrets)."""

    MAX_LOG_ROWS = 5000

    def __init__(self, db_path: pathlib.Path, vault: WindowsDpapiVault | None = None) -> None:
        self.db_path = db_path
        self.vault = vault
        self._db_lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> contextlib.AbstractContextManager[sqlite3.Connection]:
        return contextlib.closing(sqlite3.connect(self.db_path, timeout=10.0))

    def _prune_locked(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "DELETE FROM logs WHERE id <= COALESCE((SELECT id FROM logs ORDER BY id DESC LIMIT 1 OFFSET ?), 0)",
            (self.MAX_LOG_ROWS,),
        )

    def _init_db(self) -> None:
        with self._db_lock, self._connect() as conn, conn:
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
            else:
                self._prune_locked(conn)

    def add(self, level: str, tool: str, summary: str, raw_detail: str = "", port: int | None = None) -> None:
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        extra = self.vault.all_unlocked_values() if self.vault is not None else ()
        safe_summary = redact_secrets(summary, extra_secrets=extra)
        safe_raw = redact_secrets(raw_detail or summary, extra_secrets=extra)
        with contextlib.suppress(sqlite3.Error, OSError), self._db_lock, self._connect() as conn, conn:
            conn.execute(
                "INSERT INTO logs (ts, level, tool, summary, raw_detail, port) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, level, tool, safe_summary, safe_raw, port),
            )
            self._prune_locked(conn)

    def clear(self) -> None:
        with contextlib.suppress(sqlite3.Error, OSError), self._db_lock, self._connect() as conn, conn:
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
        try:
            with self._db_lock, self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except (sqlite3.Error, OSError):
            return []
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
        try:
            with self._db_lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT level, summary FROM logs WHERE tool = ? AND level IN ('ERR', 'WARN') ORDER BY id DESC LIMIT 1",
                    (tool_name,),
                ).fetchone()
            return f"[{row[0]}] {row[1]}" if row else ""
        except (sqlite3.Error, OSError):
            return ""

    def counts_by_level(self) -> dict[str, int]:
        out = {"ERR": 0, "WARN": 0, "INFO": 0, "DBG": 0}
        with contextlib.suppress(sqlite3.Error, OSError), self._db_lock, self._connect() as conn:
            for lvl, cnt in conn.execute("SELECT level, COUNT(*) FROM logs GROUP BY level"):
                out[lvl] = cnt
        return out


class StateStore:
    """Persist tool states, 94 Blender skills, profiles, projects, and user preferences."""

    _LEGACY_DUMMY_DB_URIS: frozenset[str] = frozenset(
        {
            "postgresql://localhost:5432/postgres",
            "mongodb://127.0.0.1:27017",
            "redis://127.0.0.1:6379/0",
        }
    )

    def __init__(self, state_file: pathlib.Path, vault: WindowsDpapiVault | None = None) -> None:
        self.state_file = state_file
        self.vault = vault
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    @property
    def has_saved_state(self) -> bool:
        return self.state_file.is_file()

    def _migrate_tool_secret_in_ram(self, t: ToolSpec, eff_vault: WindowsDpapiVault | None) -> bool:
        """Move any legacy URI or embedded secret out of ``t.param_value`` into DPAPI vault."""
        pv = (t.param_value or "").strip()
        if not pv:
            return False
        is_db_uri_tool = t.id in ("postgres_mcp", "mongodb_mcp", "redis_mcp")
        has_secret = contains_embedded_secret(pv)
        if not is_db_uri_tool and not has_secret:
            return False

        if is_db_uri_tool and pv in self._LEGACY_DUMMY_DB_URIS:
            t.param_value = ""
            return True

        vk = t.vault_key_name or auto_vault_key_for_tool(t.id)
        if not t.vault_key_name:
            t.vault_key_name = vk
        if eff_vault is not None and not eff_vault.is_locked():
            if not eff_vault.has_key_entry(vk) or has_secret:
                eff_vault.set_secret(vk, pv)
            t.param_value = ""
            return True
        if has_secret or is_db_uri_tool:
            t.param_value = ""
            return True
        return False

    def _scrub_custom_presets_in_meta(
        self,
        meta: dict[str, Any],
        by_id: dict[str, ToolSpec],
        eff_vault: WindowsDpapiVault | None,
    ) -> bool:
        """Scrub and migrate any DB URI or embedded secret inside ``meta['custom_presets']`` into DPAPI vault."""
        presets = meta.get("custom_presets")
        if not isinstance(presets, dict):
            return False
        scrubbed = False
        for pdata in presets.values():
            if not isinstance(pdata, dict):
                continue
            tools_map = pdata.get("tools")
            if not isinstance(tools_map, dict):
                continue
            for tid, tcfg in tools_map.items():
                if not isinstance(tcfg, dict):
                    continue
                pv = str(tcfg.get("param_value") or "").strip()
                if not pv:
                    continue
                is_db_uri_tool = tid in ("postgres_mcp", "mongodb_mcp", "redis_mcp")
                has_secret = contains_embedded_secret(pv)
                if not is_db_uri_tool and not has_secret:
                    continue
                if is_db_uri_tool and pv in self._LEGACY_DUMMY_DB_URIS:
                    tcfg["param_value"] = ""
                    scrubbed = True
                    continue
                spec = by_id.get(tid)
                vk = (spec.vault_key_name if spec and spec.vault_key_name else "") or auto_vault_key_for_tool(tid)
                if spec is not None and not spec.vault_key_name:
                    spec.vault_key_name = vk
                if eff_vault is not None and not eff_vault.is_locked():
                    if not eff_vault.has_key_entry(vk) or has_secret:
                        eff_vault.set_secret(vk, pv)
                tcfg["param_value"] = ""
                scrubbed = True
        return scrubbed

    def load_into(
        self,
        tools: list[ToolSpec],
        vault: WindowsDpapiVault | None = None,
    ) -> tuple[set[str], dict[str, Any]]:
        eff_vault = vault or self.vault
        active_skills = set(DEFAULT_ACTIVE_BLENDER_SKILLS)
        meta: dict[str, Any] = {
            "theme": "dark",
            "minimize_to_tray": False,
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
            if not isinstance(raw, dict):
                raise ValueError("State root must be a JSON object")
        except Exception:
            with contextlib.suppress(OSError):
                shutil.copyfile(self.state_file, self.state_file.with_suffix(".json.corrupt.bak"))
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
                v_str = str(v).strip()
                if v_str:
                    merged_projs[str(k)] = v_str
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

        scrubbed_any = False
        by_id = {t.id: t for t in tools}
        for tid, tdata in raw.get("tools", {}).items():
            if not isinstance(tdata, dict):
                continue
            if tid in by_id:
                t = by_id[tid]
                if "in_workspace" in tdata:
                    t.in_workspace = bool(tdata["in_workspace"])
                if "installed" in tdata:
                    t.installed = bool(tdata["installed"])
                elif t.in_workspace:
                    t.installed = True
                if tdata.get("auth_mode") in ("key", "oauth"):
                    t.auth_mode = str(tdata["auth_mode"])
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
                if not t.vault_key_name and str(tdata.get("vault_key_name", "")).startswith("AICONOMY_PARAM_"):
                    t.vault_key_name = str(tdata["vault_key_name"])
                t.param_value = str(tdata.get("param_value", t.param_value))
                if self._migrate_tool_secret_in_ram(t, eff_vault):
                    scrubbed_any = True
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
                cust_t = ToolSpec(
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
                    auth_mode=str(tdata.get("auth_mode", "key")),
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
                if self._migrate_tool_secret_in_ram(cust_t, eff_vault):
                    scrubbed_any = True
                tools.append(cust_t)

        by_id_all = {t.id: t for t in tools}
        if self._scrub_custom_presets_in_meta(meta, by_id_all, eff_vault):
            scrubbed_any = True

        if scrubbed_any:
            with contextlib.suppress(OSError):
                self.save(tools, active_skills, meta, set(by_id.keys()))
        return active_skills, meta

    def serialize(
        self, tools: list[ToolSpec], active_skills: set[str], meta: dict[str, Any], default_ids: set[str]
    ) -> dict[str, Any]:
        by_id_all = {t.id: t for t in tools}
        self._scrub_custom_presets_in_meta(meta, by_id_all, self.vault)
        tools_dict: dict[str, Any] = {}
        for t in tools:
            self._migrate_tool_secret_in_ram(t, self.vault)
            safe_pv = "" if contains_embedded_secret(t.param_value) else t.param_value
            entry: dict[str, Any] = {
                "name": t.name,
                "version": t.version,
                "in_workspace": bool(getattr(t, "in_workspace", True)),
                "installed": bool(getattr(t, "installed", getattr(t, "in_workspace", True))),
                "auth_mode": str(getattr(t, "auth_mode", "key")),
                "enabled": bool(t.enabled and getattr(t, "in_workspace", True)),
                "clients": dict(t.clients),
                "project_scope": t.project_scope,
                "mode_index": t.mode_index,
                "param_value": safe_pv,
                "options": {o.key: o.enabled for o in t.options},
            }
            if t.vault_key_name.startswith("AICONOMY_PARAM_"):
                entry["vault_key_name"] = t.vault_key_name
            if t.id not in default_ids:
                safe_args = [a for a in t.mcp_args if not contains_embedded_secret(str(a))]
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
                        "param_value": safe_pv,
                        "param_help": t.param_help,
                        "param_arg_flag": getattr(t, "param_arg_flag", ""),
                        "param_env_var": getattr(t, "param_env_var", ""),
                        "vault_key_name": t.vault_key_name,
                        "vault_key_required": t.vault_key_required,
                        "vault_key_desc": getattr(t, "vault_key_desc", ""),
                        "install_cmd": "" if contains_embedded_secret(t.install_cmd) else t.install_cmd,
                        "mcp_server_key": t.mcp_server_key,
                        "mcp_command": t.mcp_command,
                        "mcp_args": safe_args,
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
        _atomic_write_text(self.state_file, json.dumps(payload, ensure_ascii=False, indent=2))
