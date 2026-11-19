"""JSON-backed curated 86-tool library loader with SHA-256 verified remote refresh (offline-first)."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .catalog import ToolSpec

OFFICIAL_RAW_BASE = "https://raw.githubusercontent.com/DoranPierst/AIconomy/main/assets"
REMOTE_CATALOG_FILENAME = "catalog-remote.json"
REMOTE_SHA_FILENAME = "catalog-remote.sha256"

_TR_LIBRARY_TEXT: dict[str, dict[str, Any]] = {}
_CACHED_DOC: dict[str, Any] | None = None


def _bundled_assets_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            cand = pathlib.Path(meipass) / "assets"
            if cand.is_dir():
                return cand
        return pathlib.Path(sys.executable).resolve().parent / "assets"
    return pathlib.Path(__file__).resolve().parent.parent / "assets"


def _default_user_data_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        root = pathlib.Path(sys.executable).resolve().parent
    else:
        root = pathlib.Path(__file__).resolve().parent.parent
    if (root / "portable.txt").is_file():
        return root / "data"
    base = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
    return pathlib.Path(base) / "AIconomy" / "data"


def _parse_sha256_file(text: str) -> str:
    if not text:
        return ""
    first = text.strip().split()[0].lower()
    if first.startswith("sha256:"):
        first = first.split(":", 1)[1]
    return first if re.fullmatch(r"[0-9a-f]{64}", first) else ""


def verify_catalog_bytes(raw_bytes: bytes, expected_sha256: str) -> bool:
    norm = _parse_sha256_file(expected_sha256)
    if not norm or not raw_bytes:
        return False
    actual = hashlib.sha256(raw_bytes).hexdigest().lower()
    return actual == norm


def _normalize_tr_dict(raw_tr: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for tid, entry in raw_tr.items():
        if not isinstance(entry, dict):
            continue
        norm_entry = dict(entry)
        opts = norm_entry.get("options")
        if isinstance(opts, dict):
            norm_opts: dict[str, tuple[str, str]] = {}
            for k, val in opts.items():
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    norm_opts[str(k)] = (str(val[0]), str(val[1]))
            norm_entry["options"] = norm_opts
        out[str(tid)] = norm_entry
    return out


def _read_verified_catalog(json_path: pathlib.Path, sha_path: pathlib.Path) -> dict[str, Any] | None:
    if not json_path.is_file() or not sha_path.is_file():
        return None
    try:
        raw_bytes = json_path.read_bytes()
        expected = sha_path.read_text(encoding="utf-8")
        if not verify_catalog_bytes(raw_bytes, expected):
            return None
        doc = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
            return None
        return doc
    except Exception:
        return None


def load_catalog_document(force_reload: bool = False, data_dir: pathlib.Path | None = None) -> dict[str, Any]:
    """Load bundled ``assets/catalog.json`` (or a newer SHA-256 verified remote catalog in ``data_dir``)."""
    global _CACHED_DOC
    if _CACHED_DOC is not None and not force_reload:
        return _CACHED_DOC

    assets_dir = _bundled_assets_dir()
    bundled_doc = _read_verified_catalog(assets_dir / "catalog.json", assets_dir / "catalog.sha256")
    if bundled_doc is None and (assets_dir / "catalog.json").is_file():
        bundled_doc = json.loads((assets_dir / "catalog.json").read_text(encoding="utf-8"))
    if bundled_doc is None:
        bundled_doc = {"schema_version": 1, "catalog_revision": 0, "tools": [], "tr_text": {}}

    chosen = bundled_doc
    bundled_rev = int(bundled_doc.get("catalog_revision", 0) or 0)

    ddir = data_dir or _default_user_data_dir()
    remote_doc = _read_verified_catalog(ddir / REMOTE_CATALOG_FILENAME, ddir / REMOTE_SHA_FILENAME)
    if remote_doc is not None:
        rem_rev = int(remote_doc.get("catalog_revision", 0) or 0)
        if rem_rev > bundled_rev:
            chosen = remote_doc

    _TR_LIBRARY_TEXT.clear()
    _TR_LIBRARY_TEXT.update(_normalize_tr_dict(chosen.get("tr_text") or {}))
    _CACHED_DOC = chosen
    return chosen


def refresh_remote_catalog(data_dir: pathlib.Path | None = None, lang: str = "en") -> tuple[bool, bool, str]:
    """Fetch official remote ``catalog.json`` + ``catalog.sha256``, verify SHA-256, and cache if newer.

    Returns ``(ok, updated, message)``.
    """
    is_tr = lang == "tr"
    ddir = data_dir or _default_user_data_dir()
    ddir.mkdir(parents=True, exist_ok=True)
    cur_doc = load_catalog_document(data_dir=ddir)
    cur_rev = int(cur_doc.get("catalog_revision", 0) or 0)

    try:
        sha_req = urllib.request.Request(
            f"{OFFICIAL_RAW_BASE}/catalog.sha256",
            headers={"User-Agent": "AIconomy-CatalogSync"},
        )
        with urllib.request.urlopen(sha_req, timeout=6) as resp:
            sha_txt = resp.read().decode("utf-8").strip()
        expected_sha = _parse_sha256_file(sha_txt)
        if not expected_sha:
            return (
                False,
                False,
                "Uzak katalog SHA-256 özeti geçersiz." if is_tr else "Invalid remote catalog SHA-256 manifest.",
            )

        cat_req = urllib.request.Request(
            f"{OFFICIAL_RAW_BASE}/catalog.json",
            headers={"User-Agent": "AIconomy-CatalogSync"},
        )
        with urllib.request.urlopen(cat_req, timeout=8) as resp:
            raw_bytes = resp.read()

        if not verify_catalog_bytes(raw_bytes, expected_sha):
            return (
                False,
                False,
                "Güvenlik engeli: Uzak catalog.json SHA-256 doğrulaması başarısız!"
                if is_tr
                else "Security block: Remote catalog.json failed SHA-256 verification!",
            )

        doc = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
            return False, False, ("Geçersiz katalog şeması." if is_tr else "Invalid catalog JSON schema.")

        rem_rev = int(doc.get("catalog_revision", 0) or 0)
        if rem_rev <= cur_rev:
            return (
                True,
                False,
                f"Katalog güncel (rev {cur_rev})." if is_tr else f"Catalog is up to date (rev {cur_rev}).",
            )

        fd, tmp_json = tempfile.mkstemp(prefix=".catalog.", suffix=".tmp", dir=str(ddir))
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw_bytes)
        os.replace(tmp_json, ddir / REMOTE_CATALOG_FILENAME)
        (ddir / REMOTE_SHA_FILENAME).write_text(f"{expected_sha}  catalog.json\n", encoding="utf-8")

        load_catalog_document(force_reload=True, data_dir=ddir)
        return (
            True,
            True,
            f"Uzak katalog güncellendi (rev {cur_rev} -> {rem_rev}, SHA-256 doğrulandı)."
            if is_tr
            else f"Updated remote catalog (rev {cur_rev} -> {rem_rev}, SHA-256 verified).",
        )
    except Exception as exc:
        return False, False, (f"Katalog yenileme hatası: {exc}" if is_tr else f"Catalog refresh error: {exc}")


def build_library_catalog(data_dir: pathlib.Path | None = None) -> list["ToolSpec"]:
    """Instantiate the 86 curated Windows-compatible library ToolSpec items from ``catalog.json``."""
    from .catalog import CheckOption, ToolSpec

    doc = load_catalog_document(data_dir=data_dir)
    docs_dir = str(pathlib.Path.home() / "Documents")
    default_sqlite = str(pathlib.Path.home() / "Documents" / "local.db")

    out: list[ToolSpec] = []
    for item in doc.get("tools", []):
        if not isinstance(item, dict):
            continue
        pval = str(item.get("param_value", "") or "")
        if pval == "{{DEFAULT_SQLITE}}":
            pval = default_sqlite
        elif pval == "{{DOCS_DIR}}":
            pval = docs_dir

        opts = [
            CheckOption(
                str(o.get("key", "")),
                str(o.get("label", "")),
                bool(o.get("enabled", False)),
                str(o.get("help_text", "")),
            )
            for o in item.get("options", [])
            if isinstance(o, dict)
        ]
        param_lbl = str(item.get("param_label", "") or "")
        vk_name = str(item.get("vault_key_name", "") or "")
        out.append(
            ToolSpec(
                id=str(item["id"]),
                name=str(item["name"]),
                category=str(item.get("category", "coding_dev")),
                in_workspace=False,
                installed=False,
                enabled=False,
                kind=str(item.get("kind", "stdio")),
                version=str(item.get("version", "v1.0.0")),
                repo_url=str(item.get("repo_url", "")),
                schema_tokens=int(item.get("schema_tokens", 1800)),
                summary=str(item.get("summary", "")),
                details=str(item.get("details", "")),
                when_to_use=str(item.get("when_to_use", "")),
                clients=dict(item.get("clients") or {"AGY": True, "CDX": True, "CLD": False, "CUR": False}),
                scope_selectable=bool(item.get("scope_selectable", True)),
                project_scope=str(item.get("project_scope", "GLOBAL")),
                fixed_location_label=str(item.get("fixed_location_label", "")),
                modes=list(item.get("modes") or []),
                mode_index=int(item.get("mode_index", 0)),
                has_gear=bool(item.get("has_gear", bool(param_lbl or vk_name))),
                gear_kind=str(item.get("gear_kind", "standard")),
                port=item.get("port"),
                health_url=str(item.get("health_url", "")),
                param_label=param_lbl,
                param_value=pval,
                param_help=str(item.get("param_help", "")),
                param_arg_flag=str(item.get("param_arg_flag", "")),
                param_env_var=str(item.get("param_env_var", "")),
                vault_key_name=vk_name,
                vault_key_required=bool(item.get("vault_key_required", False)),
                vault_key_desc=str(item.get("vault_key_desc", "")),
                install_cmd=str(item.get("install_cmd", "")),
                mcp_server_key=str(item.get("mcp_server_key", "")),
                mcp_command=str(item.get("mcp_command", "")),
                mcp_args=list(item.get("mcp_args") or []),
                tags=list(item.get("tags") or []),
                options=opts,
            )
        )
    return out


# Preload _TR_LIBRARY_TEXT at import time so localized_tool_text works immediately
load_catalog_document()
