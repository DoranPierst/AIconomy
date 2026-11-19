"""Realistic context token budget & per-client / per-tool share calculator (emoji-free, EN & TR)."""
from __future__ import annotations

from dataclasses import dataclass
import pathlib
import shutil
from typing import Callable

from .catalog import (
    AI_CLIENTS,
    BLENDER_SKILL_INDEX_TOKENS,
    BLENDER_SKILLS_94,
    ToolSpec,
)

CONTEXT_WINDOW_TOKENS: int = 200_000

TOKEN_SAVER_IDS: frozenset[str] = frozenset({"caveman", "serena", "context7"})

SAVER_NOTE_KEYS: dict[str, str] = {
    "caveman": "tok_saver_caveman",
    "serena": "tok_saver_serena",
    "context7": "tok_saver_context7",
}


@dataclass
class ToolTokenShare:
    tool: ToolSpec
    effective_tokens: int
    nominal_tokens: int
    share_percent: float
    is_token_saver: bool
    active_clients: list[str]
    zero_reason_key: str = ""


@dataclass
class ClientTokenLoad:
    code: str
    full_name: str
    tokens: int
    context_percent: float
    tool_count: int
    is_installed: bool


@dataclass
class TokenBreakdown:
    active_tokens: int
    saved_tokens: int
    context_window: int
    clients: list[ClientTokenLoad]
    tool_shares: list[ToolTokenShare]


def fmt_tokens(tok: int) -> str:
    """Format a raw token count cleanly (e.g. 0 -> '0 tok', 600 -> '600 tok', 4600 -> '4.6K tok')."""
    val = max(0, int(tok))
    if val < 1000:
        return f"{val} tok"
    if val < 10_000:
        tenths = round(val / 1000.0, 1)
        return f"{int(tenths)}K tok" if tenths.is_integer() else f"{tenths:.1f}K tok"
    return f"{round(val / 1000.0):.0f}K tok"


def is_tool_installed_for_tokens(
    tool: ToolSpec,
    projects_map: dict[str, str],
    home_dir: pathlib.Path | None = None,
    which_cache: dict[str, bool] | None = None,
    which_fn: Callable[[str], str | None] = shutil.which,
) -> bool:
    """Fast filesystem/PATH check so uninstalled tools are never counted as fake 'Saved' tokens."""
    home = home_dir or pathlib.Path.home()

    def _has_cmd(cmd: str) -> bool:
        if which_cache is not None and cmd in which_cache:
            return which_cache[cmd]
        found = bool(which_fn(f"{cmd}.cmd") or which_fn(cmd))
        if which_cache is not None:
            which_cache[cmd] = found
        return found

    if tool.id == "blender_skills":
        plug = home / ".gemini" / "config" / "plugins" / "blender-skills"
        return (plug / "skills").is_dir() or (plug / "skills_disabled").is_dir()

    if tool.id == "caveman":
        return (
            (home / ".agents" / "skills" / "caveman" / "SKILL.md").is_file()
            or (home / ".agents" / "skills_disabled" / "caveman" / "SKILL.md").is_file()
        )

    if tool.id == "trellis":
        if not tool.param_value:
            return False
        return (pathlib.Path(tool.param_value) / "runtime" / "trellis-cli.exe").is_file()

    if tool.id == "unity_pipeline":
        target = projects_map.get(tool.project_scope, tool.param_value)
        if not target:
            return False
        manifest = pathlib.Path(target) / "Packages" / "manifest.json"
        if not manifest.is_file():
            return False
        try:
            return "com.unity.pipeline" in manifest.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False

    if tool.id == "serena":
        return (home / ".local" / "bin" / "serena.exe").is_file() or _has_cmd("serena")

    if tool.id == "unity_mcp":
        local_bin = home / ".local" / "bin"
        return (
            (local_bin / "mcp-for-unity.exe").is_file()
            or (local_bin / "unity-mcp.exe").is_file()
            or _has_cmd("mcp-for-unity")
            or _has_cmd("unity-mcp")
            or _has_cmd("uvx")
        )

    if tool.mcp_command:
        return _has_cmd(tool.mcp_command)

    return True


def compute_token_breakdown(
    tools: list[ToolSpec],
    active_skills_count: int,
    projects_map: dict[str, str],
    missing_required_keys: set[str] | None = None,
    installed_clients: set[str] | None = None,
    home_dir: pathlib.Path | None = None,
    which_fn: Callable[[str], str | None] = shutil.which,
) -> TokenBreakdown:
    """Compute realistic active schema load, honest disabled savings, per-client totals, and per-tool % shares."""
    missing_keys = missing_required_keys or set()
    inst_clients = installed_clients if installed_clients is not None else {c for c, _ in AI_CLIENTS}
    which_cache: dict[str, bool] = {}

    client_totals: dict[str, int] = {c: 0 for c, _ in AI_CLIENTS}
    client_counts: dict[str, int] = {c: 0 for c, _ in AI_CLIENTS}

    active_tokens = 0
    saved_tokens = 0
    raw_shares: list[ToolTokenShare] = []

    sk_clamped = max(0, min(int(active_skills_count), len(BLENDER_SKILLS_94)))

    for t in tools:
        if not getattr(t, "in_workspace", True):
            continue

        active_clients = [c for c, _ in AI_CLIENTS if t.clients.get(c, False)]
        has_missing_key = bool(
            getattr(t, "auth_mode", "key") != "oauth"
            and t.vault_key_required
            and t.vault_key_name
            and t.vault_key_name in missing_keys
        )
        is_installed = is_tool_installed_for_tokens(
            t, projects_map, home_dir=home_dir, which_cache=which_cache, which_fn=which_fn
        )

        nominal = (
            sk_clamped * BLENDER_SKILL_INDEX_TOKENS
            if t.id == "blender_skills"
            else int(t.schema_tokens)
        )

        if t.enabled:
            if has_missing_key:
                eff = 0
                zero_reason = "tok_zero_missing_key"
            elif not active_clients:
                eff = 0
                zero_reason = "tok_zero_no_client"
            elif t.id in ("blender_skills", "caveman", "trellis", "unity_pipeline") and not is_installed:
                eff = 0
                zero_reason = "tok_zero_not_installed"
            else:
                eff = nominal
                zero_reason = ""

            if eff > 0:
                active_tokens += eff
                for c in active_clients:
                    client_totals[c] += eff
                    client_counts[c] += 1
                if t.id == "blender_skills":
                    saved_tokens += (len(BLENDER_SKILLS_94) - sk_clamped) * BLENDER_SKILL_INDEX_TOKENS

            raw_shares.append(
                ToolTokenShare(
                    tool=t,
                    effective_tokens=eff,
                    nominal_tokens=nominal,
                    share_percent=0.0,
                    is_token_saver=(t.id in TOKEN_SAVER_IDS),
                    active_clients=active_clients,
                    zero_reason_key=zero_reason,
                )
            )
        else:
            # Disabled tool: count toward 'Saved' ONLY if installed, has >= 1 client checked, and key is present
            if active_clients and not has_missing_key and is_installed:
                if t.id == "blender_skills":
                    saved_tokens += len(BLENDER_SKILLS_94) * BLENDER_SKILL_INDEX_TOKENS
                else:
                    saved_tokens += int(t.schema_tokens)

    for row in raw_shares:
        row.share_percent = (row.effective_tokens / active_tokens * 100.0) if active_tokens > 0 else 0.0

    raw_shares.sort(
        key=lambda r: (-r.effective_tokens, 1 if r.is_token_saver else 0, r.tool.name.lower())
    )

    client_cards = [
        ClientTokenLoad(
            code=code,
            full_name=full_name,
            tokens=client_totals[code],
            context_percent=(client_totals[code] / CONTEXT_WINDOW_TOKENS * 100.0),
            tool_count=client_counts[code],
            is_installed=(code in inst_clients),
        )
        for code, full_name in AI_CLIENTS
    ]

    return TokenBreakdown(
        active_tokens=active_tokens,
        saved_tokens=saved_tokens,
        context_window=CONTEXT_WINDOW_TOKENS,
        clients=client_cards,
        tool_shares=raw_shares,
    )
