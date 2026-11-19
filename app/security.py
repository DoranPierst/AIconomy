"""Security primitives: secret redaction, least-privilege env scrubbing, and PBKDF2 vault entropy."""
from __future__ import annotations

import hashlib
import os
import re
from typing import Iterable

PBKDF2_ITERATIONS: int = 600_000

# Pre-compiled patterns for automatic secret redaction in logs and diagnostic prompts
_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test|proj|[A-Za-z0-9]{14,})[A-Za-z0-9_-]*\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:ntn_[A-Za-z0-9]{14,}|secret_[A-Za-z0-9]{20,})\b"),
    re.compile(r"\bsntryu_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bglsa_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{14,}\b"),
    re.compile(r"\br8_[A-Za-z0-9]{14,}\b"),
    re.compile(r"\bfigd_[A-Za-z0-9_-]{14,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
)

_BEARER_RE = re.compile(r"(?i)(\bBearer\s+)([A-Za-z0-9._~+/=-]{10,})")
_FLAG_KEY_RE = re.compile(r"(?i)(--(?:api[-_]?key|token|secret|password)(?:\s+|=))([^\s\"']+)")
_KV_SECRET_RE = re.compile(
    r"""(?i)(\b[A-Z0-9_]*(?:API_KEY|SECRET_KEY|ACCESS_TOKEN|AUTH_TOKEN|PRIVATE_KEY|PERSONAL_ACCESS_TOKEN|PASSWORD)\b\s*[=:]\s*["']?)([^\s"',;]{8,})"""
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


def redact_secrets(text: str, extra_secrets: Iterable[str] = ()) -> str:
    """Mask API keys, tokens, Bearer headers, and known vault secrets from logs/prompts."""
    if not text:
        return text
    out = text
    for raw_sec in extra_secrets:
        s = (raw_sec or "").strip()
        if len(s) >= 6 and s in out:
            out = out.replace(s, "***REDACTED***")
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

    cleaned.update(allowed_Tool_env)
    return cleaned
