"""Serialized, atomic AI client configuration sync, Blender skills sync, and Caveman rule sync."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import shutil
import stat
import sys
import tempfile
import threading
import tomllib
from typing import Any

from .catalog import ToolSpec, localized_tool_modes
from .oauth import check_cli_oauth_ready, get_oauth_spec, resolve_cli_oauth_token, supports_oauth
from .security import auto_vault_key_for_tool, contains_embedded_secret, split_postgres_uri_secret
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


_AGY_SKILL_MARKER = ".aiconomy_managed"


def _sanitize_skill_folder_name(raw_name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", (raw_name or "").strip()).strip("._-")
    return clean or "skill"


def _remove_agy_skill_mirrors(agy_skills_root: pathlib.Path, mirror_prefix: str) -> None:
    """Remove AIconomy-managed Antigravity skill mirror folders for ``mirror_prefix``."""
    if not agy_skills_root.is_dir():
        return
    prefix_clean = _sanitize_skill_folder_name(mirror_prefix)
    direct = agy_skills_root / prefix_clean
    if direct.is_dir() and ((direct / _AGY_SKILL_MARKER).is_file() or prefix_clean == "caveman"):
        _force_rmtree(direct)
    for child in list(agy_skills_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(f"{prefix_clean}__") and (child / _AGY_SKILL_MARKER).is_file():
            _force_rmtree(child)


def _copy_single_skill_to_agy(
    src_dir: pathlib.Path,
    dst_dir: pathlib.Path,
    owner_id: str = "",
) -> None:
    if dst_dir.exists():
        _force_rmtree(dst_dir)
    dst_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src_dir,
        dst_dir,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"),
    )
    dst_skill_md = dst_dir / "SKILL.md"
    if dst_skill_md.is_file():
        raw_md = dst_skill_md.read_text(encoding="utf-8", errors="replace")
        fixed_md = _dedupe_yaml_frontmatter_keys(raw_md)
        if fixed_md != raw_md:
            _atomic_write_text(dst_skill_md, fixed_md)
    marker_txt = f"managed-by-aiconomy:{owner_id}\n" if owner_id else "managed-by-aiconomy\n"
    _atomic_write_text(dst_dir / _AGY_SKILL_MARKER, marker_txt)


def _mirror_skill_dir_to_agy(
    src_dir: pathlib.Path,
    agy_skills_root: pathlib.Path,
    mirror_prefix: str,
    owner_id: str = "",
) -> int:
    """Mirror one or more SKILL.md folders from ``src_dir`` into a target skills directory."""
    eff_owner = owner_id or mirror_prefix
    if owner_id:
        _clean_managed_skills_in_dir(agy_skills_root, owner_id=eff_owner)
    else:
        _remove_agy_skill_mirrors(agy_skills_root, mirror_prefix)
    if not src_dir.is_dir():
        return 0
    prefix_clean = _sanitize_skill_folder_name(mirror_prefix)
    if (src_dir / "SKILL.md").is_file():
        dst_f = agy_skills_root / prefix_clean
        if dst_f.exists() and not (dst_f / _AGY_SKILL_MARKER).is_file() and prefix_clean != "caveman":
            return 0
        _copy_single_skill_to_agy(src_dir, dst_f, owner_id=eff_owner)
        return 1

    copied = 0
    seen_names: set[str] = set()
    for skill_md in sorted(src_dir.rglob("SKILL.md")):
        if ".git" in skill_md.parts:
            continue
        skill_dir = skill_md.parent
        sub_name = _sanitize_skill_folder_name(skill_dir.name)
        target_name = f"{prefix_clean}__{sub_name}"
        if target_name in seen_names:
            continue
        seen_names.add(target_name)
        dst_f = agy_skills_root / target_name
        if dst_f.exists() and not (dst_f / _AGY_SKILL_MARKER).is_file():
            continue
        _copy_single_skill_to_agy(skill_dir, dst_f, owner_id=eff_owner)
        copied += 1
    return copied


def sync_caveman_on_disk(
    caveman_tool: ToolSpec,
    agents_root: pathlib.Path | None = None,
    agy_skills_root: pathlib.Path | None = None,
    lang: str = "en",
    runtime_active: bool = True,
    projects_map: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Enable/disable Caveman on disk (global or project-scoped), stamp Lite/Full/Ultra directive, and isolate per client."""
    is_tr = lang == "tr"
    root = agents_root or (pathlib.Path.home() / ".agents")
    if agy_skills_root is not None:
        agy_root = agy_skills_root
    elif agents_root is not None:
        agy_root = agents_root / "_agy_skills"
    else:
        agy_root = pathlib.Path.home() / ".gemini" / "config" / "skills"

    active_dir = root / "skills" / "caveman"
    disabled_dir = root / "skills_disabled" / "caveman"

    if not active_dir.is_dir() and not disabled_dir.is_dir():
        _remove_agy_skill_mirrors(agy_root, "caveman")
        if projects_map:
            for p_str in projects_map.values():
                _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agent" / "skills", owner_id="caveman")
                _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agents" / "skills", owner_id="caveman")
        msg = (
            "Caveman kuralı diske kurulu değil."
            if is_tr
            else "Caveman rule is not installed on disk."
        )
        return False, msg

    want_base = bool(runtime_active and getattr(caveman_tool, "in_workspace", True) and caveman_tool.enabled)
    want_agy = bool(want_base and caveman_tool.clients.get("AGY", False))
    want_agents = bool(
        want_base
        and (
            caveman_tool.clients.get("CDX", False)
            or caveman_tool.clients.get("CLD", False)
            or caveman_tool.clients.get("CUR", False)
        )
    )
    proj_scope = str(getattr(caveman_tool, "project_scope", "GLOBAL") or "GLOBAL")
    is_global_scope = proj_scope == "GLOBAL" or not projects_map or proj_scope not in projects_map

    if not want_agy and not want_agents:
        if active_dir.is_dir():
            disabled_dir.parent.mkdir(parents=True, exist_ok=True)
            if disabled_dir.exists():
                _force_rmtree(disabled_dir)
            shutil.move(str(active_dir), str(disabled_dir))
        _remove_agy_skill_mirrors(agy_root, "caveman")
        if projects_map:
            for p_str in projects_map.values():
                _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agent" / "skills", owner_id="caveman")
                _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agents" / "skills", owner_id="caveman")
        msg = (
            "Caveman disk üzerinde devre dışı bırakıldı."
            if is_tr
            else "Caveman disabled on disk."
        )
        return True, msg

    # Position master copy according to whether global Codex/Claude/Cursor (~/.agents/skills) is enabled
    if want_agents and is_global_scope:
        if not active_dir.is_dir() and disabled_dir.is_dir():
            active_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(disabled_dir), str(active_dir))
        master_dir = active_dir
    else:
        if active_dir.is_dir():
            disabled_dir.parent.mkdir(parents=True, exist_ok=True)
            if disabled_dir.exists():
                _force_rmtree(disabled_dir)
            shutil.move(str(active_dir), str(disabled_dir))
        master_dir = disabled_dir

    m_idx = max(0, min(int(caveman_tool.mode_index), 2))
    skill_md = master_dir / "SKILL.md"
    if skill_md.is_file():
        orig_txt = skill_md.read_text(encoding="utf-8", errors="replace")
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

    if want_agy and is_global_scope:
        _mirror_skill_dir_to_agy(master_dir, agy_root, "caveman")
    else:
        _remove_agy_skill_mirrors(agy_root, "caveman")

    if projects_map:
        for p_key, p_str in projects_map.items():
            p_root = pathlib.Path(p_str)
            if is_global_scope or p_key != proj_scope or not want_agy:
                _clean_managed_skills_in_dir(p_root / ".agent" / "skills", owner_id="caveman")
            if is_global_scope or p_key != proj_scope or not want_agents:
                _clean_managed_skills_in_dir(p_root / ".agents" / "skills", owner_id="caveman")
        if not is_global_scope:
            p_target = pathlib.Path(projects_map[proj_scope])
            if p_target.is_dir():
                if want_agy:
                    _mirror_skill_dir_to_agy(master_dir, p_target / ".agent" / "skills", "caveman", owner_id="caveman")
                if want_agents:
                    _mirror_skill_dir_to_agy(master_dir, p_target / ".agents" / "skills", "caveman", owner_id="caveman")

    modes = localized_tool_modes(caveman_tool, lang)
    mode_lbl = modes[m_idx] if m_idx < len(modes) else "Full (-65%)"
    msg = (
        f"Caveman aktif ({mode_lbl})."
        if is_tr
        else f"Caveman enabled ({mode_lbl})."
    )
    return True, msg


def sync_custom_skill_tools_on_disk(
    tools: list[ToolSpec],
    agents_root: pathlib.Path | None = None,
    agy_skills_root: pathlib.Path | None = None,
    lang: str = "en",
    runtime_active: bool = True,
    projects_map: dict[str, str] | None = None,
) -> list[str]:
    """Sync Git-cloned custom skill packs / rules across global or project-scoped AGY and Agents directories."""
    is_tr = lang == "tr"
    root = agents_root or (pathlib.Path.home() / ".agents")
    if agy_skills_root is not None:
        agy_root = agy_skills_root
    elif agents_root is not None:
        agy_root = agents_root / "_agy_skills"
    else:
        agy_root = pathlib.Path.home() / ".gemini" / "config" / "skills"

    messages: list[str] = []
    for t in tools:
        if t.id in ("blender_skills", "caveman"):
            continue
        is_skill_tool = (
            t.kind in ("skill_pack", "rule")
            or (t.install_cmd or "").strip().startswith("git clone ")
        )
        if not is_skill_tool or t.mcp_server_key:
            continue

        active_dir = root / "skills" / t.id
        disabled_dir = root / "skills_disabled" / t.id
        if not active_dir.is_dir() and not disabled_dir.is_dir():
            _remove_agy_skill_mirrors(agy_root, t.id)
            if projects_map:
                for p_str in projects_map.values():
                    _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agent" / "skills", owner_id=t.id)
                    _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agents" / "skills", owner_id=t.id)
            continue

        want_on = bool(runtime_active and getattr(t, "in_workspace", True) and t.enabled)
        want_agy = bool(want_on and t.clients.get("AGY", False))
        want_agents = bool(
            want_on
            and (t.clients.get("CDX", False) or t.clients.get("CLD", False) or t.clients.get("CUR", False))
        )
        proj_scope = str(getattr(t, "project_scope", "GLOBAL") or "GLOBAL")
        is_global_scope = not getattr(t, "scope_selectable", True) or proj_scope == "GLOBAL" or not projects_map or proj_scope not in projects_map

        if not want_agy and not want_agents:
            if active_dir.is_dir():
                disabled_dir.parent.mkdir(parents=True, exist_ok=True)
                if disabled_dir.exists():
                    _force_rmtree(disabled_dir)
                shutil.move(str(active_dir), str(disabled_dir))
            _remove_agy_skill_mirrors(agy_root, t.id)
            if projects_map:
                for p_str in projects_map.values():
                    _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agent" / "skills", owner_id=t.id)
                    _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agents" / "skills", owner_id=t.id)
            messages.append(f"{t.name}: {'devre dışı' if is_tr else 'disabled'}")
            continue

        if want_agents and is_global_scope:
            if not active_dir.is_dir() and disabled_dir.is_dir():
                active_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(disabled_dir), str(active_dir))
            master_dir = active_dir
        else:
            if active_dir.is_dir():
                disabled_dir.parent.mkdir(parents=True, exist_ok=True)
                if disabled_dir.exists():
                    _force_rmtree(disabled_dir)
                shutil.move(str(active_dir), str(disabled_dir))
            master_dir = disabled_dir

        if want_agy and is_global_scope:
            mirrored = _mirror_skill_dir_to_agy(master_dir, agy_root, t.id)
            messages.append(
                f"{t.name}: AGY ({mirrored} skill)" if is_tr else f"{t.name}: AGY ({mirrored} skill(s))"
            )
        else:
            _remove_agy_skill_mirrors(agy_root, t.id)

        if projects_map:
            for p_key, p_str in projects_map.items():
                p_root = pathlib.Path(p_str)
                if is_global_scope or p_key != proj_scope or not want_agy:
                    _clean_managed_skills_in_dir(p_root / ".agent" / "skills", owner_id=t.id)
                if is_global_scope or p_key != proj_scope or not want_agents:
                    _clean_managed_skills_in_dir(p_root / ".agents" / "skills", owner_id=t.id)
            if not is_global_scope:
                p_target = pathlib.Path(projects_map[proj_scope])
                if p_target.is_dir():
                    mirrored_proj = 0
                    if want_agy:
                        mirrored_proj = _mirror_skill_dir_to_agy(
                            master_dir, p_target / ".agent" / "skills", t.id, owner_id=t.id
                        )
                    if want_agents:
                        mirrored_proj = max(
                            mirrored_proj,
                            _mirror_skill_dir_to_agy(
                                master_dir, p_target / ".agents" / "skills", t.id, owner_id=t.id
                            ),
                        )
                    messages.append(
                        f"{t.name}: {proj_scope} ({mirrored_proj} skill)"
                        if is_tr
                        else f"{t.name}: {proj_scope} ({mirrored_proj} skill(s))"
                    )
    return messages


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
    if (
        (home / ".codex").is_dir()
        or shutil.which("codex")
        or (home_dir is None and (local_app / "Microsoft" / "WindowsApps" / "ChatGPT.exe").exists())
    ):
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


def _clean_managed_skills_in_dir(
    skills_root: pathlib.Path,
    prefix: str = "",
    owner_id: str = "",
) -> None:
    """Remove directories marked with ``.aiconomy_managed`` inside ``skills_root`` (scoped to ``owner_id`` when given)."""
    if not skills_root.is_dir():
        return
    for child in list(skills_root.iterdir()):
        if not child.is_dir():
            continue
        if prefix and not child.name.startswith(prefix):
            continue
        marker = child / _AGY_SKILL_MARKER
        if not marker.is_file():
            continue
        if owner_id:
            try:
                raw_m = marker.read_text(encoding="utf-8", errors="ignore").strip()
            except OSError:
                raw_m = ""
            if ":" in raw_m:
                if raw_m.split(":", 1)[1].strip() != owner_id:
                    continue
            elif owner_id != "blender_skills" and child.name != owner_id and not child.name.startswith(f"{owner_id}__"):
                continue
        _force_rmtree(child)


def unique_project_key(folder_path: pathlib.Path, projects_map: dict[str, str]) -> str:
    """Return a non-colliding project key for ``folder_path`` without overwriting distinct folders."""
    norm_new = str(folder_path.resolve())
    for existing_k, existing_v in projects_map.items():
        try:
            if str(pathlib.Path(existing_v).resolve()) == norm_new:
                return existing_k
        except OSError:
            continue
    base = folder_path.name or "Project"
    if base not in projects_map:
        return base
    parent_nm = folder_path.parent.name
    cand = f"{base} ({parent_nm})" if parent_nm else f"{base} (2)"
    if cand not in projects_map:
        return cand
    idx = 2
    while f"{cand} ({idx})" in projects_map:
        idx += 1
    return f"{cand} ({idx})"


def cleanup_removed_project_configs(proj_dir: pathlib.Path | str, tools: list[ToolSpec], lang: str = "en") -> None:
    """Clean AIconomy-managed MCP entries and managed skill copies from a removed project directory."""
    proj_dir = pathlib.Path(proj_dir)
    if not proj_dir.is_dir():
        return
    ws_tools = [t for t in tools if getattr(t, "in_workspace", True)]
    managed_keys = {t.mcp_server_key for t in ws_tools if t.mcp_server_key}
    if any(t.id == "unity_mcp" for t in ws_tools):
        managed_keys.add("unityMCP")
    with _CONFIG_LOCK:
        for rel_cfg in (".mcp.json", ".cursor/mcp.json"):
            p_cfg = proj_dir / rel_cfg
            if p_cfg.is_file():
                try:
                    _rewrite_mcp_json(p_cfg, managed_keys, {}, create_if_missing=False, lang=lang)
                except Exception:
                    pass
        _clean_managed_skills_in_dir(proj_dir / ".agent" / "skills")
        _clean_managed_skills_in_dir(proj_dir / ".agents" / "skills")


def sync_blender_skills_on_disk(
    active_skills: set[str],
    plugin_enabled: bool,
    project_scope: str = "GLOBAL",
    projects_map: dict[str, str] | None = None,
    lang: str = "en",
    clients: dict[str, bool] | None = None,
    runtime_active: bool = True,
    home_dir: pathlib.Path | None = None,
) -> tuple[bool, str]:
    """Sync active Blender skills per client (AGY vs CDX/CLD/CUR) or into the selected project's .agents/skills folder."""
    is_tr = lang == "tr"
    home = home_dir or pathlib.Path.home()
    target_root = home / ".gemini" / "config" / "plugins" / "blender-skills"
    skills_dir = target_root / "skills"
    disabled_dir = target_root / "skills_disabled"
    agents_skills_root = home / ".agents" / "skills"

    if not skills_dir.is_dir() and not disabled_dir.is_dir():
        _clean_managed_skills_in_dir(agents_skills_root, prefix="blender-skills__")
        if projects_map:
            for p_str in projects_map.values():
                _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agent" / "skills", owner_id="blender_skills")
                _clean_managed_skills_in_dir(pathlib.Path(p_str) / ".agents" / "skills", owner_id="blender_skills")
        msg = (
            "Blender Skills henüz diske indirilmedi (Eklentiler sekmesinden kurabilirsiniz)."
            if is_tr
            else "Blender Skills is not installed on disk yet (install from the Plugins tab)."
        )
        return False, msg

    skills_dir.mkdir(parents=True, exist_ok=True)
    disabled_dir.mkdir(parents=True, exist_ok=True)

    eff_enabled = bool(plugin_enabled and runtime_active)
    c_map = clients if clients is not None else {"AGY": True}
    want_agy = bool(eff_enabled and c_map.get("AGY", False))
    want_agents = bool(
        eff_enabled and (c_map.get("CDX", False) or c_map.get("CLD", False) or c_map.get("CUR", False))
    )

    is_global_scope = project_scope == "GLOBAL" or not projects_map or project_scope not in projects_map
    global_agy_effective = active_skills if (want_agy and is_global_scope) else set()

    moved = 0
    for folder in list(skills_dir.iterdir()) + list(disabled_dir.iterdir()):
        if not folder.is_dir() or folder.name == "references":
            continue
        should_be_on = folder.name in global_agy_effective
        desired_parent = skills_dir if should_be_on else disabled_dir
        if folder.parent != desired_parent:
            dest = desired_parent / folder.name
            if dest.exists():
                _force_rmtree(dest)
            shutil.move(str(folder), str(dest))
            moved += 1

    # Sync global ~/.agents/skills/blender-skills__* for CDX / CLD / CUR isolation
    _clean_managed_skills_in_dir(agents_skills_root, prefix="blender-skills__")
    all_pool = {f.name: f for f in list(skills_dir.iterdir()) + list(disabled_dir.iterdir()) if f.is_dir()}
    if want_agents and is_global_scope and active_skills:
        agents_skills_root.mkdir(parents=True, exist_ok=True)
        for name in sorted(active_skills):
            src_f = all_pool.get(name)
            if src_f is not None and name != "references":
                _copy_single_skill_to_agy(
                    src_f,
                    agents_skills_root / f"blender-skills__{name}",
                    owner_id="blender_skills",
                )

    # Always clean stale AIconomy-managed Blender copies across non-target projects (never touches other skills!)
    if projects_map:
        for p_key, p_dir_str in projects_map.items():
            p_root = pathlib.Path(p_dir_str)
            if is_global_scope or p_key != project_scope or not want_agy:
                _clean_managed_skills_in_dir(p_root / ".agent" / "skills", owner_id="blender_skills")
            if is_global_scope or p_key != project_scope or not want_agents:
                _clean_managed_skills_in_dir(p_root / ".agents" / "skills", owner_id="blender_skills")

    if not is_global_scope and projects_map:
        proj_dir = pathlib.Path(projects_map[project_scope])
        if proj_dir.is_dir():
            target_buckets: list[tuple[bool, pathlib.Path]] = [
                (want_agy, proj_dir / ".agent" / "skills"),
                (want_agents, proj_dir / ".agents" / "skills"),
            ]
            for should_write, bucket_dir in target_buckets:
                _clean_managed_skills_in_dir(bucket_dir, owner_id="blender_skills")
                if should_write and active_skills:
                    bucket_dir.mkdir(parents=True, exist_ok=True)
                    for name in sorted(active_skills):
                        src_f = all_pool.get(name)
                        if src_f is None or name == "references":
                            continue
                        dst_f = bucket_dir / name
                        if dst_f.exists() and not (dst_f / _AGY_SKILL_MARKER).is_file():
                            # Preserve user's own non-AIconomy skill folder if same name exists
                            continue
                        _copy_single_skill_to_agy(src_f, dst_f, owner_id="blender_skills")
                    if "references" in all_pool:
                        dst_ref = bucket_dir / "references"
                        if not dst_ref.exists() or (dst_ref / _AGY_SKILL_MARKER).is_file():
                            _copy_single_skill_to_agy(all_pool["references"], dst_ref, owner_id="blender_skills")
            cnt = len(active_skills) if (want_agy or want_agents) else 0
            msg = (
                f"'{project_scope}' projesine senkronlandı ({cnt} skill)."
                if is_tr
                else f"Synced to project '{project_scope}' ({cnt} skills)."
            )
            return True, msg

    eff_cnt = len(active_skills) if (want_agy or want_agents) else 0
    msg = (
        f"Global senkronizasyon tamamlandı ({moved} taşındı, {eff_cnt} aktif)."
        if is_tr
        else f"Global sync complete ({moved} moved, {eff_cnt} active)."
    )
    return True, msg


def _is_http_mcp_tool(t: ToolSpec) -> bool:
    return bool(t.port and t.id in ("serena", "unity_mcp"))


def is_tool_credential_ready(t: ToolSpec, vault: WindowsDpapiVault) -> bool:
    """Return True when the tool's active auth_mode ('oauth' or 'key') has usable credentials."""
    if getattr(t, "auth_mode", "key") == "oauth" and supports_oauth(t.id):
        ospec = get_oauth_spec(t.id)
        if ospec and ospec.kind == "remote_mcp":
            return True
        if ospec and ospec.kind == "cli_login":
            return check_cli_oauth_ready(t.id)
    if t.vault_key_required and t.vault_key_name:
        return vault.has_secret(t.vault_key_name)
    return True


def build_mcp_exec_launcher_entry(t: ToolSpec, vault: WindowsDpapiVault) -> dict[str, Any]:
    """Build a zero-plaintext --mcp-exec config entry so secrets never touch disk JSON/TOML files."""
    from .mcp_bridge import ensure_fast_bridge_binary

    data_dir = vault.vault_file.resolve().parent
    data_dir_str = str(data_dir)
    fast_bridge = ensure_fast_bridge_binary(data_dir)
    if fast_bridge is not None:
        return {
            "command": str(fast_bridge.resolve()),
            "args": ["--mcp-exec", t.id, "--data-dir", data_dir_str],
        }
    exe_str = str(pathlib.Path(sys.executable).resolve())
    if getattr(sys, "frozen", False):
        return {
            "command": exe_str,
            "args": ["--mcp-exec", t.id, "--data-dir", data_dir_str],
        }
    main_py = str(pathlib.Path(__file__).resolve().parent.parent / "main.py")
    return {
        "command": exe_str,
        "args": [main_py, "--mcp-exec", t.id, "--data-dir", data_dir_str],
    }


def _migrate_inline_tool_secret(t: ToolSpec, vault: WindowsDpapiVault) -> None:
    """Ensure any secret accidentally placed in ``t.param_value`` is moved into DPAPI vault in RAM."""
    pv = (t.param_value or "").strip()
    if not pv or not contains_embedded_secret(pv):
        return
    vk = t.vault_key_name or auto_vault_key_for_tool(t.id)
    if not t.vault_key_name:
        t.vault_key_name = vk
    if not vault.is_locked():
        vault.set_secret(vk, pv)
        t.param_value = ""


def write_bridge_specs_manifest(
    tools: list[ToolSpec],
    vault: WindowsDpapiVault,
    runtime_active: bool = True,
) -> None:
    """Write secret-free launch specifications for ``aiconomy-bridge.exe`` (<85ms zero-extraction launch)."""
    from .mcp_bridge import BRIDGE_MANIFEST_FILENAME

    data_dir = vault.vault_file.resolve().parent
    manifest_path = data_dir / BRIDGE_MANIFEST_FILENAME
    entries: dict[str, dict[str, Any]] = {}
    if runtime_active:
        for t in tools:
            if not getattr(t, "in_workspace", True) or not t.enabled or _is_http_mcp_tool(t):
                continue
            is_oauth = getattr(t, "auth_mode", "key") == "oauth" and supports_oauth(t.id)
            ospec = get_oauth_spec(t.id) if is_oauth else None
            if ospec is not None and ospec.kind == "remote_mcp":
                continue
            if not t.mcp_command:
                continue

            _migrate_inline_tool_secret(t, vault)
            args = [str(a) for a in t.mcp_args if not contains_embedded_secret(str(a))]
            opt_map = {o.key: bool(o.enabled) for o in t.options}
            if t.id == "chrome_devtools":
                if opt_map.get("headless_mode", False) and "--headless" not in args:
                    args.append("--headless")
                if opt_map.get("isolated_profile", False) and "--isolated" not in args:
                    args.append("--isolated")

            plain_env: dict[str, str] = {}
            p_val = "" if contains_embedded_secret(t.param_value) else t.param_value.strip()
            if t.id == "blender_mcp":
                b_port = int(t.port or (int(p_val) if p_val.isdigit() else 9876))
                if b_port != 9876:
                    plain_env["BLENDER_PORT"] = str(b_port)
            elif t.id == "elevenlabs_mcp" and p_val:
                plain_env["ELEVENLABS_MCP_OUTPUT_PATH"] = p_val
            elif t.id == "renderdoc_mcp" and p_val:
                plain_env["RENDERDOC_CAPTURE_DIR"] = p_val
            else:
                if p_val and getattr(t, "param_env_var", ""):
                    plain_env[t.param_env_var] = p_val
                if p_val and getattr(t, "param_arg_flag", ""):
                    if t.param_arg_flag == "__POSITIONAL__":
                        if p_val not in args:
                            args.append(p_val)
                    elif t.param_arg_flag not in args:
                        args.extend([t.param_arg_flag, p_val])

            use_oauth_cli = bool(is_oauth and ospec is not None and ospec.kind == "cli_login" and ospec.token_args)
            sec_flag = ""
            sec_env_var = t.vault_key_name
            if not use_oauth_cli:
                if t.id == "postgres_mcp":
                    sec_flag = "__PG_POSITIONAL__"
                    sec_env_var = ""
                elif t.vault_key_name.startswith("AICONOMY_PARAM_"):
                    sec_flag = getattr(t, "param_arg_flag", "") or ""
                    sec_env_var = getattr(t, "param_env_var", "") or t.vault_key_name

            entries[t.id] = {
                "name": t.name,
                "cmd": t.mcp_command,
                "args": args,
                "env": plain_env,
                "vault_key": t.vault_key_name,
                "vault_required": bool(t.vault_key_required),
                "secret_arg_flag": sec_flag,
                "secret_env_var": sec_env_var,
                "oauth_mode": use_oauth_cli,
                "oauth_cli_bin": ospec.cli_binary if (use_oauth_cli and ospec is not None) else "",
                "oauth_token_args": list(ospec.token_args) if (use_oauth_cli and ospec is not None) else [],
            }

    payload = json.dumps({"version": 1, "tools": entries}, ensure_ascii=False, indent=2)
    try:
        _atomic_write_text(manifest_path, payload)
    except OSError:
        pass


def build_effective_stdio_spec(
    t: ToolSpec,
    vault: WindowsDpapiVault,
    wrap_windows_npx: bool = True,
    override_secret: str | None = None,
) -> tuple[str, list[str], dict[str, str]] | None:
    """Resolve effective in-RAM (command, args, env) for a stdio MCP tool, or None when credentials are missing."""
    is_oauth = getattr(t, "auth_mode", "key") == "oauth" and supports_oauth(t.id)
    ospec = get_oauth_spec(t.id) if is_oauth else None

    if ospec is not None and ospec.kind == "remote_mcp":
        cmd = "npx"
        args = ["-y", "mcp-remote", ospec.remote_mcp_url]
        if wrap_windows_npx and os.name == "nt":
            cmd = "cmd"
            args = ["/c", "npx", *args]
        return cmd, args, {}

    if not t.mcp_command:
        return None
    _migrate_inline_tool_secret(t, vault)
    if (
        not is_oauth
        and t.vault_key_required
        and t.vault_key_name
        and override_secret is None
        and not vault.has_secret(t.vault_key_name)
    ):
        return None
    if not is_oauth and t.vault_key_required and override_secret is not None and not override_secret:
        return None

    args = list(t.mcp_args)
    opt_map = {o.key: bool(o.enabled) for o in t.options}
    if t.id == "chrome_devtools":
        if opt_map.get("headless_mode", False) and "--headless" not in args:
            args.append("--headless")
        if opt_map.get("isolated_profile", False) and "--isolated" not in args:
            args.append("--isolated")

    env: dict[str, str] = {}
    if is_oauth and ospec is not None and ospec.kind == "cli_login":
        if ospec.token_args and t.vault_key_name:
            cli_tok = resolve_cli_oauth_token(t.id)
            if not cli_tok and t.vault_key_required:
                return None
            if cli_tok:
                env[t.vault_key_name] = cli_tok
    elif t.vault_key_name:
        secret = override_secret if override_secret is not None else vault.get_secret(t.vault_key_name)
        if secret:
            if t.id == "postgres_mcp":
                clean_uri, pg_pw = split_postgres_uri_secret(secret)
                if clean_uri and clean_uri not in args:
                    args.append(clean_uri)
                if pg_pw:
                    env["PGPASSWORD"] = pg_pw
            elif t.vault_key_name.startswith("AICONOMY_PARAM_"):
                target_env = getattr(t, "param_env_var", "") or t.vault_key_name
                env[target_env] = secret
                p_flag = getattr(t, "param_arg_flag", "")
                if p_flag == "__POSITIONAL__":
                    if secret not in args:
                        args.append(secret)
                elif p_flag and p_flag not in args:
                    args.extend([p_flag, secret])
            else:
                env[t.vault_key_name] = secret

    p_val = "" if contains_embedded_secret(t.param_value) else t.param_value.strip()
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
    """Build a disk-safe MCP client config entry with ZERO plaintext API keys, tokens, or DB passwords."""
    if _is_http_mcp_tool(t):
        return {"url": f"http://127.0.0.1:{t.port}/mcp"}
    _migrate_inline_tool_secret(t, vault)
    if not is_tool_credential_ready(t, vault):
        return None

    is_oauth = getattr(t, "auth_mode", "key") == "oauth" and supports_oauth(t.id)
    ospec = get_oauth_spec(t.id) if is_oauth else None

    if is_oauth and ospec is not None:
        if ospec.kind == "remote_mcp":
            if os.name == "nt":
                return {"command": "cmd", "args": ["/c", "npx", "-y", "mcp-remote", ospec.remote_mcp_url]}
            return {"command": "npx", "args": ["-y", "mcp-remote", ospec.remote_mcp_url]}
        if ospec.token_args:
            return build_mcp_exec_launcher_entry(t, vault)

    # Whenever a tool uses a required or stored vault secret, or has any embedded secret, route through --mcp-exec!
    if not is_oauth and t.vault_key_name and (t.vault_key_required or vault.has_key_entry(t.vault_key_name)):
        return build_mcp_exec_launcher_entry(t, vault)
    if contains_embedded_secret(t.param_value) or any(contains_embedded_secret(str(a)) for a in t.mcp_args):
        return build_mcp_exec_launcher_entry(t, vault)

    spec = build_effective_stdio_spec(t, vault, wrap_windows_npx=True)
    if spec is None:
        return None
    cmd, args, env = spec
    if any(contains_embedded_secret(str(a)) for a in args) or any(
        contains_embedded_secret(str(v)) for v in env.values()
    ):
        return build_mcp_exec_launcher_entry(t, vault)
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
            raw_txt = cfg_path.read_text(encoding="utf-8-sig")
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
    serialized = json.dumps(data, ensure_ascii=False, indent=2)
    json.loads(serialized)  # Mandatory syntax gate before disk write
    if cfg_path.is_file():
        shutil.copyfile(cfg_path, cfg_path.with_suffix(cfg_path.suffix + ".bak"))
    _atomic_write_text(cfg_path, serialized)
    return True, ""


def sync_mcp_json_clients(
    tools: list[ToolSpec],
    vault: WindowsDpapiVault,
    projects_map: dict[str, str] | None = None,
    lang: str = "en",
    runtime_active: bool = True,
    extra_managed_keys: set[str] | None = None,
) -> list[str]:
    """Synchronize all AI client config files under a single lock to avoid concurrent writes."""
    with _CONFIG_LOCK:
        return _sync_mcp_json_clients_impl(
            tools,
            vault,
            projects_map,
            lang=lang,
            runtime_active=runtime_active,
            extra_managed_keys=extra_managed_keys,
        )


def _repair_glued_toml_headers(toml_text: str) -> str:
    """Repair any corrupted '[section]key = val' lines missing a newline after the closing bracket."""
    return re.sub(
        r"^(\[[^\r\n\]]+\])([ \t]*[A-Za-z0-9_.-]+[ \t]*=)",
        r"\1\n\2",
        toml_text,
        flags=re.MULTILINE,
    )


def _format_toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


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
    runtime_active: bool = True,
    extra_managed_keys: set[str] | None = None,
) -> list[str]:
    """Write global and project-scoped MCP client configs with .bak backups."""
    is_tr = lang == "tr"
    unchanged_word = "değişmedi" if is_tr else "unchanged"
    projects_map = projects_map or {}
    home = pathlib.Path.home()
    installed_clients = detect_installed_ai_clients(home)
    client_paths = {
        "AGY": home / ".gemini" / "config" / "mcp_config.json",
        "CLD": home / ".claude.json",
        "CUR": home / ".cursor" / "mcp.json",
    }
    messages: list[str] = []
    write_bridge_specs_manifest(tools, vault, runtime_active=runtime_active)
    # Only touch keys of tools actually added to the user's AIconomy workspace (never wipe user's unrelated MCPs!)
    ws_tools = [t for t in tools if getattr(t, "in_workspace", True)]
    managed_keys = {t.mcp_server_key for t in ws_tools if t.mcp_server_key}
    if any(t.id == "unity_mcp" for t in ws_tools):
        managed_keys.add("unityMCP")
    if extra_managed_keys:
        managed_keys.update(k for k in extra_managed_keys if k)

    for code, cfg_path in client_paths.items():
        wanted: dict[str, dict[str, Any]] = {}
        if runtime_active:
            for t in tools:
                if not t.mcp_server_key or not (getattr(t, "in_workspace", True) and t.enabled and t.clients.get(code, False)):
                    continue
                if code in ("CLD", "CUR") and t.scope_selectable and t.project_scope != "GLOBAL":
                    continue
                entry = _build_mcp_entry(t, vault)
                if entry:
                    wanted[t.mcp_server_key] = entry
        allow_create = bool(runtime_active and wanted and (code == "AGY" or code in installed_clients))
        try:
            written, err = _rewrite_mcp_json(
                cfg_path,
                managed_keys,
                wanted,
                create_if_missing=allow_create,
                lang=lang,
            )
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
        scoped_tools = (
            [
                t
                for t in tools
                if t.mcp_server_key
                and getattr(t, "in_workspace", True)
                and t.enabled
                and t.scope_selectable
                and t.project_scope == proj_name
            ]
            if runtime_active
            else []
        )
        for target_code, rel_cfg in [("CLD", ".mcp.json"), ("CUR", ".cursor/mcp.json")]:
            p_wanted: dict[str, dict[str, Any]] = {}
            for t in scoped_tools:
                if t.clients.get(target_code, False):
                    entry = _build_mcp_entry(t, vault)
                    if entry:
                        p_wanted[t.mcp_server_key] = entry
            p_cfg = proj_dir / rel_cfg
            try:
                written, err = _rewrite_mcp_json(p_cfg, managed_keys, p_wanted, create_if_missing=runtime_active, lang=lang)
            except Exception as exc:
                written, err = False, (f"yazma hatası ({exc})" if is_tr else f"write error ({exc})")
            if err:
                messages.append(f"{proj_name}/{rel_cfg}: {err}")
            elif written:
                messages.append(f"{proj_name}/{rel_cfg} ({len(p_wanted)} MCP)")

    codex_cfg = home / ".codex" / "config.toml"
    has_cdx_wanted = bool(
        runtime_active
        and any(
            t.mcp_server_key and t.enabled and t.clients.get("CDX", False) and _build_mcp_entry(t, vault) is not None
            for t in ws_tools
        )
    )
    if codex_cfg.is_file() or (has_cdx_wanted and ("CDX" in installed_clients or codex_cfg.parent.is_dir())):
        try:
            orig_toml = codex_cfg.read_text(encoding="utf-8-sig") if codex_cfg.is_file() else ""
            cleaned = _repair_glued_toml_headers(_strip_marked_codex_blocks(orig_toml))
            # Verify base TOML is parseable before modifying anything (never corrupt an unreadable file)
            base_parsed = tomllib.loads(cleaned) if cleaned.strip() else {}

            alias_map: dict[str, ToolSpec] = {}
            for t in ws_tools:
                if t.mcp_server_key:
                    alias_map[t.mcp_server_key] = t
                    if t.id == "unity_mcp":
                        alias_map["unityMCP"] = t

            def _replace_toml_args_assignment(body_text: str, args_toml_inner: str) -> str:
                m_args = re.search(r"^[ \t]*args[ \t]*=[ \t]*\[", body_text, flags=re.MULTILINE)
                if not m_args:
                    return body_text
                idx_scan = m_args.end() - 1  # points to '['
                depth = 0
                in_dq = False
                in_sq = False
                esc = False
                end_idx = -1
                while idx_scan < len(body_text):
                    ch = body_text[idx_scan]
                    if in_dq:
                        if esc:
                            esc = False
                        elif ch == "\\":
                            esc = True
                        elif ch == '"':
                            in_dq = False
                    elif in_sq:
                        if ch == "'":
                            in_sq = False
                    else:
                        if ch == '"':
                            in_dq = True
                        elif ch == "'":
                            in_sq = True
                        elif ch == "#":
                            nl = body_text.find("\n", idx_scan)
                            if nl < 0:
                                break
                            idx_scan = nl
                            continue
                        elif ch == "[":
                            depth += 1
                        elif ch == "]":
                            depth -= 1
                            if depth == 0:
                                end_idx = idx_scan + 1
                                break
                    idx_scan += 1
                if end_idx < 0:
                    return body_text
                return body_text[: m_args.start()] + f"args = [{args_toml_inner}]" + body_text[end_idx:]

            def _strip_codex_env_subtable(sec_name: str, text_in: str) -> str:
                env_pat = re.compile(
                    rf'^\[mcp_servers\.(?:"{re.escape(sec_name)}"|\'{re.escape(sec_name)}\'|{re.escape(sec_name)})\.env\][ \t]*(?:#[^\r\n]*)?(?:\r?\n|\Z)',
                    flags=re.MULTILINE,
                )
                while True:
                    m_env = env_pat.search(text_in)
                    if not m_env:
                        break
                    e_start = m_env.end()
                    next_s = re.search(r"^\[", text_in[e_start:], flags=re.MULTILINE)
                    e_end = e_start + next_s.start() if next_s else len(text_in)
                    prefix = text_in[: m_env.start()].rstrip(" \t\r\n")
                    suffix = text_in[e_end:].lstrip("\r\n")
                    text_in = (prefix + "\n\n" + suffix) if (prefix and suffix) else (prefix + suffix)
                return text_in

            def _sync_existing_codex_section(
                sec_name: str,
                should_enable: bool,
                desired_entry: dict[str, Any] | None,
                text_in: str,
            ) -> tuple[str, bool]:
                hdr_pat = re.compile(
                    rf'^\[mcp_servers\.(?:"{re.escape(sec_name)}"|\'{re.escape(sec_name)}\'|{re.escape(sec_name)})\][ \t]*(?:#[^\r\n]*)?(?:\r?\n|\Z)',
                    flags=re.MULTILINE,
                )
                m = hdr_pat.search(text_in)
                if not m:
                    return text_in, False
                header_chunk = m.group(0)
                start = m.end()
                next_sec = re.search(r"^\[", text_in[start:], flags=re.MULTILINE)
                end = start + next_sec.start() if next_sec else len(text_in)
                body = text_in[start:end]
                val_str = "true" if should_enable else "false"
                if re.search(r"^[ \t]*enabled[ \t]*=[ \t]*(?:true|false)", body, flags=re.MULTILINE):
                    body = re.sub(
                        r"^[ \t]*enabled[ \t]*=[ \t]*(?:true|false)",
                        f"enabled = {val_str}",
                        body,
                        count=1,
                        flags=re.MULTILINE,
                    )
                else:
                    body = f"enabled = {val_str}\n" + body.lstrip("\r\n")

                if should_enable and desired_entry is not None:
                    if "url" in desired_entry:
                        url_toml = json.dumps(desired_entry["url"])
                        if re.search(r"^[ \t]*url[ \t]*=", body, flags=re.MULTILINE):
                            body = re.sub(
                                r"^[ \t]*url[ \t]*=[^\r\n]*",
                                lambda _m, u=url_toml: f"url = {u}",
                                body,
                                count=1,
                                flags=re.MULTILINE,
                            )
                    elif "command" in desired_entry:
                        cmd_toml = json.dumps(desired_entry["command"])
                        args_toml = ", ".join(json.dumps(a) for a in desired_entry.get("args", []))
                        if re.search(r"^[ \t]*command[ \t]*=", body, flags=re.MULTILINE):
                            body = re.sub(
                                r"^[ \t]*command[ \t]*=[^\r\n]*",
                                lambda _m, c=cmd_toml: f"command = {c}",
                                body,
                                count=1,
                                flags=re.MULTILINE,
                            )
                        body = _replace_toml_args_assignment(body, args_toml)

                if not header_chunk.endswith("\n"):
                    header_chunk = header_chunk + "\n"
                updated_txt = text_in[: m.start()] + header_chunk + body + text_in[end:]
                if desired_entry is None or not desired_entry.get("env"):
                    updated_txt = _strip_codex_env_subtable(sec_name, updated_txt)
                return updated_txt, True

            handled_existing: set[str] = set()
            for sec_key, t_obj in alias_map.items():
                has_req_key = is_tool_credential_ready(t_obj, vault)
                want_cdx = bool(
                    runtime_active
                    and getattr(t_obj, "in_workspace", True)
                    and t_obj.enabled
                    and t_obj.clients.get("CDX", False)
                    and has_req_key
                )
                eff_entry = _build_mcp_entry(t_obj, vault) if want_cdx else None
                cleaned, found_sec = _sync_existing_codex_section(sec_key, want_cdx, eff_entry, cleaned)
                if found_sec:
                    handled_existing.add(t_obj.id)

            existing_codex_servers = set((base_parsed.get("mcp_servers") or {}).keys())
            cdx_lines: list[str] = [CODEX_BEGIN_TAG]
            cdx_added = 0
            if runtime_active:
                for t in ws_tools:
                    if not t.mcp_server_key or not (t.enabled and t.clients.get("CDX", False)):
                        continue
                    entry = _build_mcp_entry(t, vault)
                    if entry is None:
                        continue
                    if t.id in handled_existing or t.mcp_server_key in existing_codex_servers:
                        cdx_added += 1
                        continue
                    safe_key = _format_toml_key(t.mcp_server_key)
                    if "url" in entry:
                        cdx_lines.append(f"[mcp_servers.{safe_key}]")
                        cdx_lines.append(f"url = {json.dumps(entry['url'])}")
                        cdx_added += 1
                    else:
                        args_toml = ", ".join(json.dumps(a) for a in entry.get("args", []))
                        cdx_lines.append(f"[mcp_servers.{safe_key}]")
                        cdx_lines.append(f"command = {json.dumps(entry['command'])}")
                        cdx_lines.append(f"args = [{args_toml}]")
                        env_dict = entry.get("env") or {}
                        if env_dict:
                            cdx_lines.append(f"[mcp_servers.{safe_key}.env]")
                            for ek, ev in env_dict.items():
                                cdx_lines.append(f"{_format_toml_key(ek)} = {json.dumps(ev)}")
                        cdx_added += 1
            cdx_lines.append(CODEX_END_TAG)
            if cdx_added > 0:
                new_toml = cleaned.rstrip() + "\n\n" + "\n".join(cdx_lines) + "\n"
            else:
                new_toml = cleaned.rstrip() + "\n"

            # Mandatory TOML syntax gate: never write invalid config.toml that could break Codex/ChatGPT
            tomllib.loads(new_toml)

            if new_toml != orig_toml:
                if codex_cfg.is_file():
                    shutil.copyfile(codex_cfg, codex_cfg.with_suffix(".toml.bak"))
                _atomic_write_text(codex_cfg, new_toml)
                messages.append(f"CDX ({cdx_added} MCP)")
            else:
                messages.append(f"CDX ({cdx_added} MCP, {unchanged_word})")
        except Exception as exc:
            messages.append(f"CDX hatası ({exc})" if is_tr else f"CDX error ({exc})")

    return messages
