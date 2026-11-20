"""Security primitives: secret redaction, least-privilege env scrubbing, and PBKDF2 vault entropy."""
from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from typing import Iterable

PBKDF2_ITERATIONS: int = 600_000

# Pre-compiled patterns for automatic secret redaction and plaintext leak prevention
_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test|proj|[A-Za-z0-9]{14,})[A-Za-z0-9_-]*\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:ntn_[A-Za-z0-9]{14,}|secret_[A-Za-z0-9]{20,})\b"),
    re.compile(r"\bsbp_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bsntryu_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bglsa_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{14,}\b"),
    re.compile(r"\br8_[A-Za-z0-9]{14,}\b"),
    re.compile(r"\bfigd_[A-Za-z0-9_-]{14,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\blin_api_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\btvly-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bfc-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bpplx-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+"),
    re.compile(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+"),
)

_BEARER_RE = re.compile(r"(?i)(\bBearer\s+)([A-Za-z0-9._~+/=-]{10,})")
_FLAG_KEY_RE = re.compile(r"(?i)(--(?:api[-_]?key|token|secret|password)(?:\s+|=))([^\s\"']+)")
_KV_SECRET_RE = re.compile(
    r"""(?i)(\b[A-Z0-9_]*(?:API_KEY|SECRET_KEY|ACCESS_TOKEN|AUTH_TOKEN|PRIVATE_KEY|PERSONAL_ACCESS_TOKEN|PASSWORD|PASSWD)\b\s*[=:]\s*["']?)([^\s"',;]{6,})"""
)
_URI_CRED_RE = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@\"']*:)(?!\*\*\*REDACTED\*\*\*)([^@\s/\"']+)(@)"
)
_PG_URI_SPLIT_RE = re.compile(
    r"^((?:postgres|postgresql)://)([^/\s:@\"']*)(?::([^@\s/\"']*))?(@.+)$",
    flags=re.IGNORECASE,
)

# Environment variable names/suffixes stripped from child MCP processes unless explicitly owned by that tool
_SENSITIVE_ENV_EXACT: frozenset[str] = frozenset(
    {
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "GITLAB_PERSONAL_ACCESS_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ELEVENLABS_API_KEY",
        "MESHY_API_KEY",
        "CONTEXT7_API_KEY",
        "STRIPE_SECRET_KEY",
        "SUPABASE_ACCESS_TOKEN",
        "NOTION_TOKEN",
        "SENTRY_ACCESS_TOKEN",
        "CLOUDFLARE_API_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "PGPASSWORD",
        "MYSQL_PWD",
        "DATABASE_URL",
        "POSTGRES_URL",
        "POSTGRES_CONNECTION_URI",
        "MONGODB_URI",
        "MDB_MCP_CONNECTION_STRING",
        "REDIS_URL",
    }
)

_SENSITIVE_ENV_SUFFIXES: tuple[str, ...] = (
    "_API_KEY",
    "_SECRET",
    "_SECRET_KEY",
    "_ACCESS_TOKEN",
    "_AUTH_TOKEN",
    "_PERSONAL_ACCESS_TOKEN",
    "_PRIVATE_KEY",
    "_PASSWORD",
    "_PASSWD",
    "_TOKEN",
    "_PAT",
    "_DSN",
    "_CONNECTION_STRING",
    "_CONNECTION_URI",
)


def derive_vault_entropy(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte optional DPAPI entropy key from a user passphrase using PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=32,
    )


def auto_vault_key_for_tool(tool_id: str) -> str:
    """Deterministic DPAPI vault slot name when a user enters a secret in a generic parameter field."""
    clean = re.sub(r"[^A-Z0-9]+", "_", (tool_id or "CUSTOM").upper()).strip("_") or "CUSTOM"
    return f"AICONOMY_PARAM_{clean}"


def contains_embedded_secret(text: str) -> bool:
    """Return True if ``text`` contains an API token, Bearer secret, key=value password, or URI password."""
    s = (text or "").strip()
    if not s:
        return False
    if _URI_CRED_RE.search(s):
        return True
    if _BEARER_RE.search(s) or _FLAG_KEY_RE.search(s) or _KV_SECRET_RE.search(s):
        return True
    return any(pat.search(s) for pat in _TOKEN_PATTERNS)


def split_postgres_uri_secret(uri: str) -> tuple[str, str]:
    """Strip inline password from a PostgreSQL URI so the password travels via PGPASSWORD env, never argv."""
    s = (uri or "").strip()
    m = _PG_URI_SPLIT_RE.match(s)
    if not m:
        return s, ""
    scheme, user, raw_pw, host_part = m.group(1), m.group(2), m.group(3) or "", m.group(4)
    if not raw_pw:
        return s, ""
    decoded_pw = urllib.parse.unquote(raw_pw)
    if user:
        return f"{scheme}{user}{host_part}", decoded_pw
    # Empty username (postgresql://:pass@host/db) -> strip '@' as well
    return f"{scheme}{host_part.lstrip('@')}", decoded_pw


def redact_secrets(text: str, extra_secrets: Iterable[str] = ()) -> str:
    """Mask API keys, tokens, URI passwords, Bearer headers, and known vault secrets from logs/prompts."""
    if not text:
        return text
    out = text
    for raw_sec in extra_secrets:
        s = (raw_sec or "").strip()
        if len(s) >= 6 and s in out:
            out = out.replace(s, "***REDACTED***")
        if "://" in s:
            _clean_u, pw = split_postgres_uri_secret(s)
            if len(pw) >= 4 and pw in out:
                out = out.replace(pw, "***REDACTED***")
    out = _URI_CRED_RE.sub(r"\1***REDACTED***\3", out)
    for pat in _TOKEN_PATTERNS:
        out = pat.sub("***REDACTED***", out)
    out = _BEARER_RE.sub(r"\1***REDACTED***", out)
    out = _FLAG_KEY_RE.sub(r"\1***REDACTED***", out)
    out = _KV_SECRET_RE.sub(r"\1***REDACTED***", out)
    return out


def build_isolated_child_env(
    allowed_Tool_env: dict[str, str],
    allowed_secret_key: str = "",
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return a child process environment with unrelated host API keys/tokens scrubbed out."""
    src = dict(os.environ if base_env is None else base_env)
    keep_upper = {k.upper() for k in allowed_Tool_env}
    if allowed_secret_key:
        keep_upper.add(allowed_secret_key.upper())

    cleaned: dict[str, str] = {}
    for k, v in src.items():
        ku = k.upper()
        if ku not in keep_upper:
            if ku in _SENSITIVE_ENV_EXACT or any(ku.endswith(sfx) for sfx in _SENSITIVE_ENV_SUFFIXES):
                continue
        cleaned[k] = v

    cleaned.setdefault("npm_config_ignore_scripts", "true")
    cleaned.update(allowed_Tool_env)
    return cleaned
