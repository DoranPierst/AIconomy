"""Serialized, atomic AI client configuration sync, Blender skills sync, and Caveman rule sync."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import shutil
import stat
import tempfile
import threading
from typing import Any

from .catalog import ToolSpec, localized_tool_modes
from .storage import WindowsDpapiVault

_CONFIG_LOCK = threading.Lock()

CODEX_BEGIN_TAG = "# >>> BEGIN AICONOMY >>>"
CODEX_END_TAG = "# <<< END AICONOMY <<<"
_LEGACY_CODEX_BEGIN_TAG = "# >>> BEGIN AI-ARAC-MERKEZI >>>"
_LEGACY_CODEX_END_TAG = "# <<< END AI-ARAC-MERKEZI <<<"

CAVEMAN_BEGIN_TAG = "<!-- BEGIN AICONOMY CAVEMAN MODE -->"
CAVEMAN_END_TAG = "<!-- END AICONOMY CAVEMAN MODE -->"

_CAVEMAN_MODE_DIRECTIVES: dict[int, str] = {
    0: (
        "## Active AIconomy Mode: Lite (-35%)\n"
        "Keep natural, readable full sentences while cutting greetings, filler, apologies, and closing recaps. "
        "Keep all explanations clear and concise."
    ),
    1: (
        "## Active AIconomy Mode: Full (-65%)\n"
        "Apply standard Caveman compression: answer first, zero ceremony, short direct sentences (max 20 words), "
        "articles optional when unambiguous, 100% of code/paths/negations verbatim."
    ),
    2: (
        "## Active AIconomy Mode: Ultra (-75%)\n"
        "Maximum telegraphic compression: terse fragments, bullet-level density, zero prose transitions, "
        "minimum words per fact while keeping every code block, flag, path, number, and negation exact."
    ),
}


def _force_rmtree(target: pathlib.Path) -> None:
    """Remove directories containing read-only files (such as .git pack files) on Windows."""
    if not target.exists():
        return

    def _handle_readonly(func: Any, fpath: str, _exc: Any) -> None:
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except Exception:
            pass

    shutil.rmtree(target, onexc=_handle_readonly)


def _dedupe_yaml_frontmatter_keys(md_text: str) -> str:
    if not md_text.startswith("---"):
        return md_text
    parts = md_text.split("---", 2)
    if len(parts) < 3:
        return md_text
    lines = parts[1].splitlines()
    out_lines: list[str] = []
    seen_per_indent: dict[int, set[str]] = {}
    for line in lines:
        m = re.match(r"^(\s*)([A-Za-z0-9_-]+)\s*:", line)
        if m:
            indent = len(m.group(1))
            key = m.group(2)
            for deeper in [k for k in seen_per_indent if k > indent]:
                seen_per_indent.pop(deeper, None)
            bucket = seen_per_indent.setdefault(indent, set())
            if key in bucket:
                continue
            bucket.add(key)
        out_lines.append(line)
    return "---" + "\n".join(out_lines) + "\n---" + parts[2]


def _atomic_write_text(path: pathlib.Path, text: str) -> None:
    """Write text to a sibling temporary file and atomically replace ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def sync_caveman_on_disk(
    caveman_tool: ToolSpec,
    agents_root: pathlib.Path | None = None,
    lang: str = "en",
) -> tuple[bool, str]:
    """Enable/disable Caveman on disk and stamp the selected Lite/Full/Ultra directive into SKILL.md."""
    is_tr = lang == "tr"
    root = agents_root or (pathlib.Path.home() / ".agents")
    active_dir = root / "skills" / "caveman"
    disabled_dir = root / "skills_disabled" / "caveman"

    if not active_dir.is_dir() and not disabled_dir.is_dir():
        msg = (
            "Caveman kuralı diske kurulu değil."
            if is_tr
            else "Caveman rule is not installed on disk."
        )
        return False, msg

    if not (getattr(caveman_tool, "in_workspace", True) and caveman_tool.enabled):
        if active_dir.is_dir():
            disabled_dir.parent.mkdir(parents=True, exist_ok=True)
            if disabled_dir.exists():
                _force_rmtree(disabled_dir)
            shutil.move(str(active_dir), str(disabled_dir))
        msg = (
            "Caveman disk üzerinde devre dışı bırakıldı."
            if is_tr
            else "Caveman disabled on disk."
        )
        return True, msg

    if not active_dir.is_dir() and disabled_dir.is_dir():
        active_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(disabled_dir), str(active_dir))

    m_idx = max(0, min(int(caveman_tool.mode_index), 2))
    skill_md = active_dir / "SKILL.md"
    if skill_md.is_file():
        orig_txt = skill_md.read_text(encoding="utf-8")
        cleaned = re.sub(
            rf"\n*{re.escape(CAVEMAN_BEGIN_TAG)}.*?{re.escape(CAVEMAN_END_TAG)}\s*",
            "",
            orig_txt,
            flags=re.DOTALL,
        ).rstrip()
        directive = _CAVEMAN_MODE_DIRECTIVES[m_idx]
        new_txt = f"{cleaned}\n\n{CAVEMAN_BEGIN_TAG}\n{directive}\n{CAVEMAN_END_TAG}\n"
        if new_txt != orig_txt:
            _atomic_write_text(skill_md, new_txt)

    modes = localized_tool_modes(caveman_tool, lang)
    mode_lbl = modes[m_idx] if m_idx < len(modes) else "Full (-65%)"
    msg = (
        f"Caveman aktif ({mode_lbl})."
        if is_tr
        else f"Caveman enabled ({mode_lbl})."
    )
    return True, msg


def detect_installed_ai_clients(home_dir: pathlib.Path | None = None) -> set[str]:
    """Detect which AI coding clients (AGY, CDX, CLD, CUR) appear installed on this machine."""
    home = home_dir or pathlib.Path.home()
    local_app = pathlib.Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    detected: set[str] = set()
    if (
        (home / ".gemini").is_dir()
        or (local_app / "Programs" / "Antigravity").is_dir()
        or shutil.which("antigravity")
    ):
        detected.add("AGY")
    if (home / ".codex").is_dir() or shutil.which("codex"):
        detected.add("CDX")
    if (home / ".claude.json").is_file() or (home / ".claude").is_dir() or shutil.which("claude"):
        detected.add("CLD")
    if (
        (home / ".cursor").is_dir()
        or (local_app / "Programs" / "cursor").is_dir()
        or (local_app / "cursor").is_dir()
        or shutil.which("cursor")
    ):
        detected.add("CUR")
    if not detected:
        detected.add("AGY")
    return detected


def sync_blender_skills_on_disk(
    active_skills: set[str],
    plugin_enabled: bool,
    project_scope: str = "GLOBAL",
    projects_map: dict[str, str] | None = None,
    lang: str = "en",
) -> tuple[bool, str]:
    """Sync active Blender skills either globally or into the selected project's .agents/skills folder."""
    is_tr = lang == "tr"
    target_root = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
    skills_dir = target_root / "skills"
    disabled_dir = target_root / "skills_disabled"
    if not skills_dir.is_dir() and not disabled_dir.is_dir():
        msg = (
            "Blender Skills henüz diske indirilmedi (Eklentiler sekmesinden kurabilirsiniz)."
            if is_tr
            else "Blender Skills is not installed on disk yet (install from the Plugins tab)."
        )
        return False, msg

    skills_dir.mkdir(parents=True, exist_ok=True)
    disabled_dir.mkdir(parents=True, exist_ok=True)

    is_global_scope = project_scope == "GLOBAL" or not projects_map or project_scope not in projects_map
    global_effective = active_skills if (plugin_enabled and is_global_scope) else set()

    moved = 0
    for folder in list(skills_dir.iterdir()) + list(disabled_dir.iterdir()):
        if not folder.is_dir() or folder.name == "references":
            continue
        should_be_on = folder.name in global_effective
        desired_parent = skills_dir if should_be_on else disabled_dir
        if folder.parent != desired_parent:
            dest = desired_parent / folder.name
            if dest.exists():
                _force_rmtree(dest)
            shutil.move(str(folder), str(dest))
            moved += 1

    if not is_global_scope and projects_map:
        proj_dir = pathlib.Path(projects_map[project_scope])
        if proj_dir.is_dir():
            proj_skills = proj_dir / ".agents" / "skills"
            proj_skills.mkdir(parents=True, exist_ok=True)
            all_pool = {f.name: f for f in list(skills_dir.iterdir()) + list(disabled_dir.iterdir()) if f.is_dir()}
            for name, src_f in all_pool.items():
                if name == "references":
                    continue
                dst_f = proj_skills / name
                if dst_f.exists():
                    _force_rmtree(dst_f)
                if plugin_enabled and name in active_skills:
                    shutil.copytree(src_f, dst_f)
            if "references" in all_pool and plugin_enabled and active_skills:
                dst_ref = proj_skills / "references"
                if dst_ref.exists():
                    _force_rmtree(dst_ref)
                shutil.copytree(all_pool["references"], dst_ref)
            cnt = len(active_skills) if plugin_enabled else 0
            msg = (
                f"'{project_scope}' projesine senkronlandı ({cnt} skill -> .agents/skills)."
                if is_tr
                else f"Synced to project '{project_scope}' ({cnt} skills -> .agents/skills)."
            )
            return True, msg

    msg = (
        f"Global senkronizasyon tamamlandı ({moved} taşındı, {len(global_effective)} aktif)."
        if is_tr
        else f"Global sync complete ({moved} moved, {len(global_effective)} active)."
    )
    return True, msg


def _is_http_mcp_tool(t: ToolSpec) -> bool:
    return bool(t.port and t.id in ("serena", "unity_mcp"))


def build_effective_stdio_spec(
    t: ToolSpec,
    vault: WindowsDpapiVault,
    wrap_windows_npx: bool = True,
) -> tuple[str, list[str], dict[str, str]] | None:
    """Resolve effective (command, args, env) for a stdio MCP tool, or None when blocked by a missing required key."""
    if not t.mcp_command:
        return None
    if t.vault_key_required and t.vault_key_name and not vault.has_secret(t.vault_key_name):
        return None

    args = list(t.mcp_args)
    opt_map = {o.key: bool(o.enabled) for o in t.options}
    if t.id == "chrome_devtools":
        if opt_map.get("headless_mode", False) and "--headless" not in args:
            args.append("--headless")
        if opt_map.get("isolated_profile", False) and "--isolated" not in args:
            args.append("--isolated")

    env: dict[str, str] = {}
    if t.vault_key_name:
        secret = vault.get_secret(t.vault_key_name)
        if secret:
            if t.id == "context7" and "--api-key" not in args:
                args.extend(["--api-key", secret])
            env[t.vault_key_name] = secret

    p_val = t.param_value.strip()
    if t.id == "blender_mcp":
        b_port = int(t.port or (int(p_val) if p_val.isdigit() else 9876))
        if b_port != 9876:
            env["BLENDER_PORT"] = str(b_port)
    elif t.id == "elevenlabs_mcp" and p_val:
        env["ELEVENLABS_MCP_OUTPUT_PATH"] = p_val
    elif t.id == "renderdoc_mcp" and p_val:
        env["RENDERDOC_CAPTURE_DIR"] = p_val
    else:
        if p_val and getattr(t, "param_env_var", ""):
            env[t.param_env_var] = p_val
        if p_val and getattr(t, "param_arg_flag", ""):
            if t.param_arg_flag == "__POSITIONAL__":
                if p_val not in args:
                    args.append(p_val)
            elif t.param_arg_flag not in args:
                args.extend([t.param_arg_flag, p_val])

    cmd = t.mcp_command
    if wrap_windows_npx and os.name == "nt" and cmd.lower() == "npx":
        cmd = "cmd"
        args = ["/c", "npx", *args]

    return cmd, args, env


def _build_mcp_entry(t: ToolSpec, vault: WindowsDpapiVault) -> dict[str, Any] | None:
    if _is_http_mcp_tool(t):
        return {"url": f"http://127.0.0.1:{t.port}/mcp"}
    spec = build_effective_stdio_spec(t, vault, wrap_windows_npx=True)
    if spec is None:
        return None
    cmd, args, env = spec
    entry: dict[str, Any] = {"command": cmd, "args": args}
    if env:
        entry["env"] = env
    return entry


def _rewrite_mcp_json(
    cfg_path: pathlib.Path,
    managed_keys: set[str],
    wanted_entries: dict[str, dict[str, Any]],
    create_if_missing: bool,
    lang: str = "en",
) -> tuple[bool, str]:
    """Update only AIconomy-managed keys in an mcpServers JSON file.

    Returns (written, error_message). Skips writes and .bak backups when unchanged.
    """
    is_tr = lang == "tr"
    if not cfg_path.is_file() and not (create_if_missing and wanted_entries):
        return False, ""
    data: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            raw_txt = cfg_path.read_text(encoding="utf-8")
            data = json.loads(raw_txt) if raw_txt.strip() else {}
        except Exception as exc:
            return False, (f"okuma hatası ({exc})" if is_tr else f"read error ({exc})")
        if not isinstance(data, dict):
            return False, ("beklenmeyen JSON biçimi" if is_tr else "unexpected JSON format")
    original = copy.deepcopy(data)

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    for key in list(servers.keys()):
        if key in managed_keys:
            servers.pop(key, None)
    servers.update(wanted_entries)
    if servers or "mcpServers" in data:
        data["mcpServers"] = servers

    if data == original:
        return False, ""
    if cfg_path.is_file():
        shutil.copyfile(cfg_path, cfg_path.with_suffix(cfg_path.suffix + ".bak"))
    _atomic_write_text(cfg_path, json.dumps(data, ensure_ascii=False, indent=2))
    return True, ""


def sync_mcp_json_clients(
    tools: list[ToolSpec],
    vault: WindowsDpapiVault,
    projects_map: dict[str, str] | None = None,
    lang: str = "en",
) -> list[str]:
    """Synchronize all AI client config files under a single lock to avoid concurrent writes."""
    with _CONFIG_LOCK:
        return _sync_mcp_json_clients_impl(tools, vault, projects_map, lang=lang)


def _strip_marked_codex_blocks(toml_text: str) -> str:
    cleaned = toml_text
    for begin_tag, end_tag in (
        (CODEX_BEGIN_TAG, CODEX_END_TAG),
        (_LEGACY_CODEX_BEGIN_TAG, _LEGACY_CODEX_END_TAG),
    ):
        cleaned = re.sub(
            rf"\n?{re.escape(begin_tag)}.*?{re.escape(end_tag)}\n?",
            "\n",
            cleaned,
            flags=re.DOTALL,
        )
    return cleaned.rstrip()


def _sync_mcp_json_clients_impl(
    tools: list[ToolSpec],
    vault: WindowsDpapiVault,
    projects_map: dict[str, str] | None = None,
    lang: str = "en",
) -> list[str]:
    """Write global and project-scoped MCP client configs with .bak backups."""
    is_tr = lang == "tr"
    unchanged_word = "değişmedi" if is_tr else "unchanged"
    projects_map = projects_map or {}
    client_paths = {
        "AGY": pathlib.Path.home() / ".gemini" / "config" / "mcp_config.json",
        "CLD": pathlib.Path.home() / ".claude.json",
        "CUR": pathlib.Path.home() / ".cursor" / "mcp.json",
    }
    messages: list[str] = []
    managed_keys = {t.mcp_server_key for t in tools if t.mcp_server_key} | {"unityMCP"}

    for code, cfg_path in client_paths.items():
        wanted: dict[str, dict[str, Any]] = {}
        for t in tools:
            if not t.mcp_server_key or not (getattr(t, "in_workspace", True) and t.enabled and t.clients.get(code, False)):
                continue
            if code in ("CLD", "CUR") and t.scope_selectable and t.project_scope != "GLOBAL":
                continue
            entry = _build_mcp_entry(t, vault)
            if entry:
                wanted[t.mcp_server_key] = entry
        try:
            written, err = _rewrite_mcp_json(cfg_path, managed_keys, wanted, create_if_missing=(code == "AGY"), lang=lang)
        except Exception as exc:
            written, err = False, (f"yazma hatası ({exc})" if is_tr else f"write error ({exc})")
        if err:
            messages.append(f"{code}: {err}")
        elif cfg_path.is_file():
            messages.append(f"{code} Global ({len(wanted)} MCP{'' if written else f', {unchanged_word}'})")

    for proj_name, proj_dir_str in projects_map.items():
        proj_dir = pathlib.Path(proj_dir_str)
        if not proj_dir.is_dir():
            continue
        scoped_tools = [
            t
            for t in tools
            if t.mcp_server_key
            and getattr(t, "in_workspace", True)
            and t.enabled
            and t.scope_selectable
            and t.project_scope == proj_name
        ]
        for target_code, rel_cfg in [("CLD", ".mcp.json"), ("CUR", ".cursor/mcp.json")]:
            p_wanted: dict[str, dict[str, Any]] = {}
            for t in scoped_tools:
                if t.clients.get(target_code, False):
                    entry = _build_mcp_entry(t, vault)
                    if entry:
                        p_wanted[t.mcp_server_key] = entry
            p_cfg = proj_dir / rel_cfg
            try:
                written, err = _rewrite_mcp_json(p_cfg, managed_keys, p_wanted, create_if_missing=True, lang=lang)
            except Exception as exc:
                written, err = False, (f"yazma hatası ({exc})" if is_tr else f"write error ({exc})")
            if err:
                messages.append(f"{proj_name}/{rel_cfg}: {err}")
            elif written:
                messages.append(f"{proj_name}/{rel_cfg} ({len(p_wanted)} MCP)")

    codex_cfg = pathlib.Path.home() / ".codex" / "config.toml"
    if codex_cfg.is_file():
        try:
            orig_toml = codex_cfg.read_text(encoding="utf-8-sig")
            cleaned = _strip_marked_codex_blocks(orig_toml)

            alias_map: dict[str, ToolSpec] = {}
            for t in tools:
                if t.mcp_server_key:
                    alias_map[t.mcp_server_key] = t
                    if t.id == "unity_mcp":
                        alias_map["unityMCP"] = t

            def _sync_existing_codex_section(sec_name: str, should_enable: bool, text_in: str) -> tuple[str, bool]:
                hdr_pat = re.compile(rf"(^\[mcp_servers\.{re.escape(sec_name)}\]\s*$)", flags=re.MULTILINE)
                m = hdr_pat.search(text_in)
                if not m:
                    return text_in, False
                start = m.end()
                next_sec = re.search(r"^\[", text_in[start:], flags=re.MULTILINE)
                end = start + next_sec.start() if next_sec else len(text_in)
                body = text_in[start:end]
                val_str = "true" if should_enable else "false"
                if re.search(r"^\s*enabled\s*=", body, flags=re.MULTILINE):
                    body = re.sub(
                        r"^\s*enabled\s*=\s*(true|false)",
                        f"enabled = {val_str}",
                        body,
                        count=1,
                        flags=re.MULTILINE,
                    )
                else:
                    body = f"\nenabled = {val_str}" + body
                return text_in[:start] + body + text_in[end:], True

            handled_existing: set[str] = set()
            for sec_key, t_obj in alias_map.items():
                has_req_key = not (
                    t_obj.vault_key_required
                    and t_obj.vault_key_name
                    and not vault.has_secret(t_obj.vault_key_name)
                )
                want_cdx = bool(
                    getattr(t_obj, "in_workspace", True)
                    and t_obj.enabled
                    and t_obj.clients.get("CDX", False)
                    and has_req_key
                )
                cleaned, found_sec = _sync_existing_codex_section(sec_key, want_cdx, cleaned)
                if found_sec:
                    handled_existing.add(t_obj.id)

            cdx_lines: list[str] = [CODEX_BEGIN_TAG]
            cdx_added = 0
            for t in tools:
                if not t.mcp_server_key or not (
                    getattr(t, "in_workspace", True) and t.enabled and t.clients.get("CDX", False)
                ):
                    continue
                entry = _build_mcp_entry(t, vault)
                if entry is None:
                    continue
                if t.id in handled_existing:
                    cdx_added += 1
                    continue
                if "url" in entry:
                    cdx_lines.append(f"[mcp_servers.{t.mcp_server_key}]")
                    cdx_lines.append(f"url = {json.dumps(entry['url'])}")
                    cdx_added += 1
                else:
                    args_toml = ", ".join(json.dumps(a) for a in entry.get("args", []))
                    cdx_lines.append(f"[mcp_servers.{t.mcp_server_key}]")
                    cdx_lines.append(f"command = {json.dumps(entry['command'])}")
                    cdx_lines.append(f"args = [{args_toml}]")
                    env_dict = entry.get("env") or {}
                    if env_dict:
                        cdx_lines.append(f"[mcp_servers.{t.mcp_server_key}.env]")
                        for ek, ev in env_dict.items():
                            cdx_lines.append(f"{ek} = {json.dumps(ev)}")
                    cdx_added += 1
            cdx_lines.append(CODEX_END_TAG)
            new_toml = cleaned + "\n\n" + "\n".join(cdx_lines) + "\n"
            if new_toml != orig_toml:
                shutil.copyfile(codex_cfg, codex_cfg.with_suffix(".toml.bak"))
                _atomic_write_text(codex_cfg, new_toml)
                messages.append(f"CDX ({cdx_added} MCP)")
            else:
                messages.append(f"CDX ({cdx_added} MCP, {unchanged_word})")
        except Exception as exc:
            messages.append(f"CDX hatası ({exc})" if is_tr else f"CDX error ({exc})")

    return messages
