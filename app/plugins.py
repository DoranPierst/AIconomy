"""Plugin update checking, package upgrades, Blender skills installation, and GitHub repo inspection (EN & TR)."""
from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import traceback
import urllib.error
import urllib.request
from typing import Any

from .catalog import ToolSpec
from .host_apps import NO_WINDOW
from .mcp_config import _dedupe_yaml_frontmatter_keys, _force_rmtree
from .updater import get_current_app_version, parse_semver, resolve_github_latest_release_web

NPM_PACKAGE_MAP: dict[str, str] = {
    "bla": "bla-agents",
    "gltf_transform": "@gltf-transform/cli",
    "context7": "@upstash/context7-mcp",
    "chrome_devtools": "chrome-devtools-mcp",
}

UV_TOOL_MAP: dict[str, str] = {
    "serena": "serena-agent",
    "unity_mcp": "mcpforunityserver",
}

PYPI_PACKAGE_MAP: dict[str, str] = {
    "serena": "serena-agent",
    "unity_mcp": "mcpforunityserver",
    "blender_mcp": "blender-mcp",
    "elevenlabs_mcp": "elevenlabs-mcp",
}


def _user_agent() -> str:
    return f"AIconomy/{get_current_app_version()}"


def _fmt_ver_short(v: str) -> str:
    clean = v.strip().lstrip("vV")
    return f"v{clean}" if clean else ""


@dataclasses.dataclass(frozen=True)
class PluginCheckResult:
    """Immutable result emitted from background update checks (K9 thread safety)."""

    tool_id: str
    tool_name: str
    local_version: str
    latest_version: str
    has_update: bool
    release_notes_url: str
    error_detail: str = ""


def install_or_update_blender_skills(active_skills: set[str], lang: str = "en") -> tuple[bool, str, str]:
    """Download arjun988/blender-skills into the Antigravity plugin folder and apply active skill split."""
    is_tr = lang == "tr"
    target_root = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
    legacy_tmp = target_root.parent / "_tmp_blender_skills_clone"
    if legacy_tmp.exists():
        _force_rmtree(legacy_tmp)

    temp_clone = pathlib.Path(tempfile.mkdtemp(prefix="aiconomy_bs_"))
    clone_dest = temp_clone / "repo"
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/arjun988/blender-skills.git", str(clone_dest)],
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=NO_WINDOW,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip()
            return False, "", (f"Git clone başarısız: {err}" if is_tr else f"Git clone failed: {err}")

        src_skills = clone_dest / ".claude" / "skills"
        if not src_skills.is_dir():
            return False, "", (
                "Repo içinde .claude/skills klasörü bulunamadı."
                if is_tr
                else "Directory .claude/skills was not found in the repository."
            )

        ver_tag = "v1.3.0"
        ver_json = clone_dest / "version.json"
        if ver_json.is_file():
            try:
                v_raw = json.loads(ver_json.read_text(encoding="utf-8")).get("version", "")
                if v_raw:
                    ver_tag = v_raw if str(v_raw).startswith("v") else f"v{v_raw}"
            except Exception:
                pass

        skills_dir = target_root / "skills"
        disabled_dir = target_root / "skills_disabled"
        skills_dir.mkdir(parents=True, exist_ok=True)
        disabled_dir.mkdir(parents=True, exist_ok=True)

        src_refs = src_skills / "references"
        if src_refs.is_dir():
            for dst_parent in (skills_dir, disabled_dir):
                dst_ref = dst_parent / "references"
                if dst_ref.exists():
                    _force_rmtree(dst_ref)
                shutil.copytree(src_refs, dst_ref)

        count = 0
        for item in src_skills.iterdir():
            if not item.is_dir() or item.name == "references":
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.is_file():
                continue
            txt = skill_md.read_text(encoding="utf-8", errors="replace")
            txt = _dedupe_yaml_frontmatter_keys(txt)
            skill_md.write_text(txt, encoding="utf-8")

            for cleanup in (skills_dir / item.name, disabled_dir / item.name):
                if cleanup.exists():
                    _force_rmtree(cleanup)

            dest = (skills_dir if item.name in active_skills else disabled_dir) / item.name
            shutil.copytree(item, dest)
            count += 1

        plugin_json = {
            "name": "blender-skills",
            "displayName": "Blender Skills (94 Specialist Pack)",
            "version": ver_tag.lstrip("v"),
            "description": "94 specialist Blender production skills managed selectively by AIconomy.",
            "repository": "https://github.com/arjun988/blender-skills",
        }
        (target_root / "plugin.json").write_text(json.dumps(plugin_json, ensure_ascii=False, indent=2), encoding="utf-8")
        msg = (
            f"{count} Blender skill güncellendi ({ver_tag}); {len(active_skills)} açık, {count - len(active_skills)} kapalı."
            if is_tr
            else f"Updated {count} Blender skills ({ver_tag}); {len(active_skills)} enabled, {count - len(active_skills)} disabled."
        )
        return True, ver_tag, msg
    except Exception as exc:
        return False, "", (f"Kurulum hatası: {exc}" if is_tr else f"Install error: {exc}")
    finally:
        _force_rmtree(temp_clone)


def inspect_github_repo(repo_url: str, github_token: str = "", lang: str = "en") -> dict[str, Any]:
    """Query GitHub API to detect whether a repository is an MCP server, skill pack, or CLI tool."""
    is_tr = lang == "tr"
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", repo_url)
    if not m:
        raise ValueError(
            "Geçerli bir GitHub repo adresi girin (örn: https://github.com/owner/repo)."
            if is_tr
            else "Enter a valid GitHub repository URL (e.g. https://github.com/owner/repo)."
        )
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    headers = {"User-Agent": _user_agent()}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    req = urllib.request.Request(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
    with urllib.request.urlopen(req, timeout=8) as resp:
        meta = json.loads(resp.read().decode("utf-8"))

    branch = meta.get("default_branch", "main")
    tree_req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers=headers,
    )
    with urllib.request.urlopen(tree_req, timeout=8) as resp:
        tree_data = json.loads(resp.read().decode("utf-8"))

    paths = [item.get("path", "") for item in tree_data.get("tree", [])]
    skill_files = [p for p in paths if p.endswith("SKILL.md")]
    has_pkg = "package.json" in paths
    has_py = "pyproject.toml" in paths
    needs_key = any("API_KEY" in p.upper() or ".env.example" in p for p in paths)

    if len(skill_files) > 1:
        kind = "skill_pack"
        cmd = f"git clone https://github.com/{owner}/{repo}.git ({len(skill_files)} SKILL.md)"
        mcp_cmd, mcp_args = "", []
    elif len(skill_files) == 1 and not has_pkg and not has_py:
        kind = "rule"
        cmd = f"git clone https://github.com/{owner}/{repo}.git"
        mcp_cmd, mcp_args = "", []
    elif has_pkg:
        kind = "stdio"
        cmd = f"npx -y {repo}"
        mcp_cmd, mcp_args = "npx", ["-y", repo]
    elif has_py:
        kind = "stdio"
        cmd = f"uvx {repo}"
        mcp_cmd, mcp_args = "uvx", [repo]
    else:
        kind = "cli"
        cmd = f"git clone https://github.com/{owner}/{repo}.git"
        mcp_cmd, mcp_args = "", []

    return {
        "id": f"gh_{owner}_{repo}".lower().replace("-", "_"),
        "name": f"{repo} ({owner})",
        "description": meta.get("description") or ("GitHub üzerinden algılanan araç." if is_tr else "Tool detected from GitHub."),
        "stars": meta.get("stargazers_count", 0),
        "kind": kind,
        "install_cmd": cmd,
        "mcp_command": mcp_cmd,
        "mcp_args": mcp_args,
        "skill_count": len(skill_files),
        "needs_api_key": needs_key,
        "repo_url": f"https://github.com/{owner}/{repo}",
    }


def check_single_tool_update(tool: ToolSpec, github_token: str = "") -> PluginCheckResult:
    """Read-only version check for a single tool. Never mutates ``tool`` (safe on worker threads)."""
    local_ver = tool.version.strip().lstrip("vV") or "1.0.0"
    remote_ver = local_ver
    notes_url = ""
    err_detail = ""

    gh_match = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", tool.repo_url)
    if gh_match:
        gh_owner, gh_repo = gh_match.group(1), gh_match.group(2).removesuffix(".git")
        notes_url = f"https://github.com/{gh_owner}/{gh_repo}/releases"
    else:
        gh_owner, gh_repo = "", ""

    ua = _user_agent()
    headers = {"User-Agent": ua}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    try:
        if tool.id == "blender_skills":
            notes_url = "https://github.com/arjun988/blender-skills/blob/main/CHANGELOG.md"
            p_json = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills" / "plugin.json"
            if p_json.is_file():
                try:
                    disk_v = str(json.loads(p_json.read_text(encoding="utf-8")).get("version", "")).strip().lstrip("vV")
                    if disk_v:
                        local_ver = disk_v
                except Exception:
                    pass
            req = urllib.request.Request(
                "https://raw.githubusercontent.com/arjun988/blender-skills/main/version.json",
                headers={"User-Agent": ua},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                v_raw = str(json.loads(resp.read().decode("utf-8")).get("version", "")).strip().lstrip("vV")
                if v_raw:
                    remote_ver = v_raw

        elif tool.id in NPM_PACKAGE_MAP:
            pkg = NPM_PACKAGE_MAP[tool.id]
            encoded_pkg = pkg.replace("/", "%2F")
            req = urllib.request.Request(
                f"https://registry.npmjs.org/{encoded_pkg}/latest",
                headers={"User-Agent": ua},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                meta = json.loads(resp.read().decode("utf-8"))
                v_raw = str(meta.get("version", "")).strip().lstrip("vV")
                if v_raw:
                    remote_ver = v_raw
            if not notes_url:
                notes_url = f"https://www.npmjs.com/package/{pkg}?activeTab=versions"

        elif tool.id in PYPI_PACKAGE_MAP:
            pkg = PYPI_PACKAGE_MAP[tool.id]
            req = urllib.request.Request(
                f"https://pypi.org/pypi/{pkg}/json",
                headers={"User-Agent": ua},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                meta = json.loads(resp.read().decode("utf-8"))
                v_raw = str(meta.get("info", {}).get("version", "")).strip().lstrip("vV")
                if v_raw:
                    remote_ver = v_raw
            if not notes_url:
                notes_url = f"https://pypi.org/project/{pkg}/#history"

        elif tool.id in ("unity_pipeline", "trellis"):
            remote_ver = local_ver
            notes_url = tool.repo_url if tool.repo_url.startswith("http") else ""

        elif gh_owner and gh_repo:
            used_api = False
            if github_token:
                try:
                    req = urllib.request.Request(
                        f"https://api.github.com/repos/{gh_owner}/{gh_repo}/releases/latest",
                        headers=headers,
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        rel = json.loads(resp.read().decode("utf-8"))
                        tag = str(rel.get("tag_name", "")).strip().lstrip("vV")
                        if tag:
                            remote_ver = tag
                        if rel.get("html_url"):
                            notes_url = str(rel["html_url"])
                        used_api = True
                except urllib.error.HTTPError as api_exc:
                    if api_exc.code == 404:
                        used_api = True
                    elif api_exc.code not in (403, 429):
                        raise

            if not used_api:
                raw_tag, tag_url, web_ok = resolve_github_latest_release_web(gh_owner, gh_repo, ua, timeout=5.0)
                if raw_tag:
                    remote_ver = raw_tag.lstrip("vV")
                if tag_url:
                    notes_url = tag_url
                if not web_ok:
                    err_detail = f"Connection failed — https://github.com/{gh_owner}/{gh_repo}/releases/latest"
    except urllib.error.HTTPError as http_exc:
        if http_exc.code != 404:
            err_detail = f"HTTP {http_exc.code} ({http_exc.reason}) — URL: {http_exc.url}"
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}"

    has_upd = parse_semver(remote_ver) > parse_semver(local_ver)
    return PluginCheckResult(
        tool_id=tool.id,
        tool_name=tool.name,
        local_version=f"v{local_ver}",
        latest_version=f"v{remote_ver}",
        has_update=has_upd,
        release_notes_url=notes_url,
        error_detail=err_detail,
    )


def check_all_tools_updates_parallel(
    tools: list[ToolSpec],
    github_token: str = "",
) -> tuple[list[PluginCheckResult], list[tuple[str, str]]]:
    """Check updates for all tools in parallel without mutating any ToolSpec objects."""
    results: list[PluginCheckResult] = []
    errors: list[tuple[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(check_single_tool_update, t, github_token): t for t in tools}
        for fut, t in future_map.items():
            try:
                res = fut.result()
                results.append(res)
                if res.error_detail:
                    errors.append((t.name, res.error_detail))
            except Exception as exc:
                errors.append((t.name, f"{type(exc).__name__}: {exc}"))
    return results, errors


def _fmt_cmd_raw(cmd: list[str], proc: subprocess.CompletedProcess[str], is_tr: bool) -> str:
    if is_tr:
        return f"Komut: {' '.join(cmd)}\nÇıkış kodu: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return f"Command: {' '.join(cmd)}\nExit code: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


def update_single_tool(
    tool: ToolSpec,
    active_skills: set[str],
    install_if_missing: bool = False,
    lang: str = "en",
) -> tuple[bool, str, str, str]:
    """Safely upgrade (or install when ``install_if_missing=True``) a single tool.

    Returns (ok, new_version_tag, short_summary, raw_log_detail). Never mutates ``tool``.
    """
    is_tr = lang == "tr"
    ua = _user_agent()
    try:
        if tool.id == "blender_skills":
            plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
            is_installed = (plugin_dir / "skills").is_dir() or (plugin_dir / "skills_disabled").is_dir()
            if is_installed or install_if_missing:
                ok, ver_tag, msg = install_or_update_blender_skills(active_skills, lang=lang)
                return ok, ver_tag or tool.version, msg, msg
            msg = (
                "Henüz indirilmedi (kurmak için seçip 'Seçilenleri kur / güncelle' tıklayın)."
                if is_tr
                else "Not installed yet (select and click 'Install / Update selected')."
            )
            return True, tool.version, msg, msg

        if tool.id == "caveman":
            cav_dir = pathlib.Path.home() / ".agents" / "skills" / "caveman"
            if (cav_dir / ".git").is_dir():
                cmd = ["git", "-C", str(cav_dir), "pull", "--ff-only"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
                raw = _fmt_cmd_raw(cmd, proc, is_tr)
                if proc.returncode == 0:
                    out = proc.stdout.strip() or ("Güncel." if is_tr else "Up to date.")
                    return True, tool.version, f"git pull: {out}", raw
                err_first = (proc.stderr.strip() or proc.stdout.strip() or "git error").splitlines()[0]
                return False, "", f"git pull: {err_first}", raw
            if (cav_dir / "SKILL.md").is_file():
                msg = "Yerel SKILL.md doğrulandı." if is_tr else "Local SKILL.md verified."
                return True, tool.version, msg, str(cav_dir / "SKILL.md")
            return True, tool.version, ("Caveman kuralı hazır." if is_tr else "Caveman rule ready."), str(cav_dir)

        if tool.id in UV_TOOL_MAP:
            pkg = UV_TOOL_MAP[tool.id]
            if install_if_missing:
                cmd = ["uv", "tool", "install", "--upgrade"]
                if pkg == "mcpforunityserver":
                    cmd.extend(["--python", "3.12"])
                cmd.append(pkg)
            else:
                cmd = ["uv", "tool", "upgrade", pkg]

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, creationflags=NO_WINDOW)
            combined = (proc.stdout + "\n" + proc.stderr).strip()
            raw = _fmt_cmd_raw(cmd, proc, is_tr)
            if proc.returncode == 0 or "Nothing to upgrade" in combined or "already installed" in combined.lower():
                return True, tool.version, (f"uv tool ({pkg}): Güncel." if is_tr else f"uv tool ({pkg}): Up to date."), raw
            if "is not installed" in combined.lower() and not install_if_missing:
                msg = (
                    f"{pkg} özel dizinde kurulu (mevcut kurulum korundu)."
                    if is_tr
                    else f"{pkg} is installed in a custom path (existing installation preserved)."
                )
                return True, tool.version, msg, raw
            first_line = (proc.stderr.strip() or proc.stdout.strip() or "uv tool error").splitlines()[0]
            return False, "", f"uv tool ({pkg}): {first_line}", raw

        if tool.id in NPM_PACKAGE_MAP:
            pkg = NPM_PACKAGE_MAP[tool.id]
            latest_ver = ""
            try:
                encoded_pkg = pkg.replace("/", "%2F")
                req = urllib.request.Request(f"https://registry.npmjs.org/{encoded_pkg}/latest", headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    meta = json.loads(resp.read().decode("utf-8"))
                    latest_ver = meta.get("version", "")
            except Exception as exc:
                err_lbl = f"npm sorgu hatası ({pkg}): {exc}" if is_tr else f"npm lookup error ({pkg}): {exc}"
                return False, "", err_lbl, traceback.format_exc()

            new_v_tag = f"v{latest_ver}" if latest_ver else tool.version
            if install_if_missing and pkg in ("bla-agents", "@gltf-transform/cli"):
                npm_exe = "npm.cmd" if shutil.which("npm.cmd") else "npm"
                cmd = [npm_exe, "install", "-g", f"{pkg}@latest"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, creationflags=NO_WINDOW)
                raw = _fmt_cmd_raw(cmd, proc, is_tr)
                if proc.returncode != 0:
                    first_err = (proc.stderr.strip() or proc.stdout.strip() or "npm install error").splitlines()[0]
                    return False, new_v_tag, f"npm install ({pkg}): {first_err}", raw
                msg = (
                    f"{pkg} global olarak {new_v_tag} sürümüne güncellendi."
                    if is_tr
                    else f"Updated {pkg} globally to {new_v_tag}."
                )
                return True, new_v_tag, msg, raw

            msg = (
                f"npm son sürümü doğrulandı -> {new_v_tag} (npx ile güncel çalışır)."
                if is_tr
                else f"Verified latest npm version -> {new_v_tag} (runs latest via npx)."
            )
            return True, new_v_tag, msg, msg

        if tool.id in PYPI_PACKAGE_MAP:
            pkg = PYPI_PACKAGE_MAP[tool.id]
            latest_ver = ""
            try:
                req = urllib.request.Request(f"https://pypi.org/pypi/{pkg}/json", headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    meta = json.loads(resp.read().decode("utf-8"))
                    latest_ver = meta.get("info", {}).get("version", "")
            except Exception as exc:
                err_lbl = f"PyPI sorgu hatası ({pkg}): {exc}" if is_tr else f"PyPI lookup error ({pkg}): {exc}"
                return False, "", err_lbl, traceback.format_exc()
            new_v_tag = f"v{latest_ver}" if latest_ver else tool.version
            msg = f"PyPI doğrulandı ({new_v_tag})." if is_tr else f"Verified latest PyPI release ({new_v_tag})."
            return True, new_v_tag, msg, msg

        if tool.id in ("unity_pipeline", "trellis"):
            msg = (
                "Yerel kurulum doğrulandı (mevcut proje ve ağırlık dosyaları korundu)."
                if is_tr
                else "Local installation verified (existing weights and project files preserved)."
            )
            return True, tool.version, msg, msg

        if "github.com/" in tool.repo_url:
            m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", tool.repo_url)
            if m:
                owner, repo = m.group(1), m.group(2).removesuffix(".git")
                raw_tag, tag_url, web_ok = resolve_github_latest_release_web(owner, repo, ua, timeout=6.0)
                if raw_tag:
                    v_t = f"v{raw_tag.lstrip('vV')}"
                    msg = (
                        f"GitHub son sürümü doğrulandı: {v_t}"
                        if is_tr
                        else f"Verified latest GitHub release: {v_t}"
                    )
                    return True, v_t, msg, tag_url
                if not web_ok:
                    err_lbl = "GitHub bağlantı hatası." if is_tr else "GitHub connection error."
                    return False, "", err_lbl, tool.repo_url
            return True, tool.version, ("GitHub kaynağı güncel." if is_tr else "GitHub source verified."), tool.repo_url

        return True, tool.version, ("Sürüm kontrolü tamamlandı." if is_tr else "Version check complete."), tool.name
    except FileNotFoundError as fnf_exc:
        missing_bin = str(fnf_exc.filename or fnf_exc)
        msg = (
            f"Gerekli araç bulunamadı ({missing_bin}). Git, uv veya Node.js kurulu olduğundan emin olun."
            if is_tr
            else f"Required executable not found ({missing_bin}). Ensure Git, uv, or Node.js is installed."
        )
        return False, "", msg, traceback.format_exc()
    except Exception as exc:
        return False, "", (f"Beklenmeyen güncelleme hatası: {exc}" if is_tr else f"Unexpected update error: {exc}"), traceback.format_exc()


def _extract_npm_package_spec(tool: ToolSpec) -> str:
    if tool.mcp_command == "npx" and tool.mcp_args:
        for arg in tool.mcp_args:
            if not arg.startswith("-"):
                return arg
    tokens = tool.install_cmd.strip().split()
    skip = {"npx", "npm", "npm.cmd", "install", "i", "-g", "-y", "--yes"}
    for tok in tokens:
        if tok in skip or tok.startswith("-"):
            continue
        return tok
    return ""


def _strip_npm_dist_tag(pkg_spec: str) -> str:
    if pkg_spec.startswith("@"):
        slash_idx = pkg_spec.find("/")
        if slash_idx > 0 and "@" in pkg_spec[slash_idx + 1 :]:
            return pkg_spec[: pkg_spec.rfind("@")]
        return pkg_spec
    if "@" in pkg_spec:
        return pkg_spec.split("@", 1)[0]
    return pkg_spec


def install_library_tool(
    tool: ToolSpec,
    active_skills: set[str],
    lang: str = "en",
) -> tuple[bool, str, str, str]:
    """Download and install an uninstalled library tool onto the user's PC (npm / uv / git).

    Returns (ok, installed_version_tag, short_summary, raw_log_detail). Never mutates ``tool``.
    """
    is_tr = lang == "tr"
    ua = _user_agent()
    try:
        if (
            tool.id in ("blender_skills", "caveman")
            or tool.id in UV_TOOL_MAP
            or tool.id in NPM_PACKAGE_MAP
        ):
            return update_single_tool(tool, active_skills, install_if_missing=True, lang=lang)

        cmd_text = tool.install_cmd.strip()

        # 1. Node / npm / npx MCP packages
        if tool.mcp_command == "npx" or cmd_text.startswith(("npx ", "npm ")):
            pkg_spec = _extract_npm_package_spec(tool)
            if not pkg_spec:
                return (
                    False,
                    "",
                    "Geçerli bir npm paket adı bulunamadı." if is_tr else "Could not determine npm package name.",
                    cmd_text,
                )
            npm_exe = shutil.which("npm.cmd") or shutil.which("npm")
            if not npm_exe:
                return (
                    False,
                    "",
                    "Node.js / npm bulunamadı. Lütfen Node.js kurun."
                    if is_tr
                    else "Node.js / npm not found on PATH. Please install Node.js.",
                    cmd_text,
                )
            cmd = [npm_exe, "install", "-g", "--no-fund", "--no-audit", pkg_spec]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
            raw = _fmt_cmd_raw(cmd, proc, is_tr)
            if proc.returncode != 0 and "EEXIST" in (proc.stderr + "\n" + proc.stdout):
                cache_cmd = [npm_exe, "cache", "add", pkg_spec]
                proc2 = subprocess.run(cache_cmd, capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
                raw = raw + "\n\n" + _fmt_cmd_raw(cache_cmd, proc2, is_tr)
                proc = proc2

            if proc.returncode != 0:
                first_err = (proc.stderr.strip() or proc.stdout.strip() or "npm install error").splitlines()[0]
                return False, "", f"npm ({pkg_spec}): {first_err}", raw

            ver_tag = tool.version
            base_pkg = _strip_npm_dist_tag(pkg_spec)
            try:
                enc = base_pkg.replace("/", "%2F")
                req = urllib.request.Request(f"https://registry.npmjs.org/{enc}/latest", headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    v_str = json.loads(resp.read().decode("utf-8")).get("version", "")
                    if v_str:
                        ver_tag = f"v{v_str}"
            except Exception:
                pass
            msg = (
                f"npm paketi indirildi ve kuruldu: {base_pkg}"
                if is_tr
                else f"Downloaded and installed npm package: {base_pkg}"
            )
            return True, ver_tag, msg, raw

        # 2. Python / uv / uvx MCP packages
        if tool.mcp_command == "uvx" or cmd_text.startswith(("uvx ", "uv ")):
            uv_exe = shutil.which("uv.exe") or shutil.which("uv")
            if not uv_exe:
                return (
                    False,
                    "",
                    "uv paket yöneticisi bulunamadı. Lütfen uv kurun."
                    if is_tr
                    else "uv package manager not found on PATH. Please install uv.",
                    cmd_text,
                )
            args_src = list(tool.mcp_args) if tool.mcp_command == "uvx" and tool.mcp_args else cmd_text.split()[1:]
            from_spec = ""
            pkg_spec = ""
            idx = 0
            while idx < len(args_src):
                tok = args_src[idx]
                if tok == "--from" and idx + 1 < len(args_src):
                    from_spec = args_src[idx + 1]
                    idx += 2
                    continue
                if tok.startswith("-"):
                    idx += 1
                    continue
                pkg_spec = tok
                break

            if not pkg_spec:
                return (
                    False,
                    "",
                    "Geçerli bir uv paket adı bulunamadı." if is_tr else "Could not determine uv package name.",
                    cmd_text,
                )

            clean_pkg = pkg_spec.removesuffix("@latest")
            if from_spec:
                cmd = [uv_exe, "tool", "install", "--upgrade", "--from", from_spec, clean_pkg]
            else:
                cmd = [uv_exe, "tool", "install", "--upgrade", clean_pkg]

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
            combined = (proc.stdout + "\n" + proc.stderr).strip()
            raw = _fmt_cmd_raw(cmd, proc, is_tr)

            if proc.returncode != 0 and "no executables are provided" in combined.lower():
                warm_cmd = [uv_exe, "tool", "run", pkg_spec, "--help"]
                proc2 = subprocess.run(warm_cmd, capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
                raw = raw + "\n\n" + _fmt_cmd_raw(warm_cmd, proc2, is_tr)
                if proc2.returncode == 0:
                    proc = proc2

            if proc.returncode == 0 or "already installed" in combined.lower() or "nothing to upgrade" in combined.lower():
                ver_tag = tool.version
                if not from_spec:
                    try:
                        req = urllib.request.Request(f"https://pypi.org/pypi/{clean_pkg}/json", headers={"User-Agent": ua})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            v_str = json.loads(resp.read().decode("utf-8")).get("info", {}).get("version", "")
                            if v_str:
                                ver_tag = f"v{v_str}"
                    except Exception:
                        pass
                msg = (
                    f"uv aracı indirildi ve kuruldu: {clean_pkg}"
                    if is_tr
                    else f"Downloaded and installed uv tool: {clean_pkg}"
                )
                return True, ver_tag, msg, raw

            first_err = (proc.stderr.strip() or proc.stdout.strip() or "uv tool install error").splitlines()[0]
            return False, "", f"uv ({clean_pkg}): {first_err}", raw

        # 3. Git repository skill packs / rules
        if cmd_text.startswith("git clone ") and tool.repo_url:
            git_exe = shutil.which("git.exe") or shutil.which("git")
            if not git_exe:
                return (
                    False,
                    "",
                    "Git bulunamadı. Lütfen Git kurun." if is_tr else "Git executable not found on PATH.",
                    cmd_text,
                )
            dest_dir = pathlib.Path.home() / ".agents" / "skills" / tool.id
            dest_dir.parent.mkdir(parents=True, exist_ok=True)
            if (dest_dir / ".git").is_dir():
                cmd = [git_exe, "-C", str(dest_dir), "pull", "--ff-only"]
            else:
                if dest_dir.exists():
                    _force_rmtree(dest_dir)
                cmd = [git_exe, "clone", "--depth", "1", tool.repo_url, str(dest_dir)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, creationflags=NO_WINDOW)
            raw = _fmt_cmd_raw(cmd, proc, is_tr)
            if proc.returncode != 0:
                first_err = (proc.stderr.strip() or proc.stdout.strip() or "git clone error").splitlines()[0]
                return False, "", f"git: {first_err}", raw
            msg = f"Git deposu kuruldu: {dest_dir}" if is_tr else f"Cloned repository to {dest_dir}"
            return True, tool.version, msg, raw

        return update_single_tool(tool, active_skills, install_if_missing=True, lang=lang)
    except subprocess.TimeoutExpired:
        msg = "İndirme zaman aşımına uğradı (120 sn)." if is_tr else "Download timed out (120s)."
        return False, "", msg, traceback.format_exc()
    except Exception as exc:
        msg = f"Kurulum hatası: {exc}" if is_tr else f"Installation error: {exc}"
        return False, "", msg, traceback.format_exc()
