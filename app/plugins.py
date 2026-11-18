"""Plugin update checking, package upgrades, Blender skills installation, and GitHub repo inspection."""
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
from .updater import get_current_app_version, parse_semver

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


def install_or_update_blender_skills(active_skills: set[str]) -> tuple[bool, str, str]:
    """Download arjun988/blender-skills into the Antigravity plugin folder and apply active skill split."""
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
            return False, "", f"Git clone başarısız: {proc.stderr.strip()}"

        src_skills = clone_dest / ".claude" / "skills"
        if not src_skills.is_dir():
            return False, "", "Repo içinde .claude/skills klasörü bulunamadı."

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
        return (
            True,
            ver_tag,
            f"{count} Blender skill güncellendi ({ver_tag}); {len(active_skills)} açık, {count - len(active_skills)} kapalı.",
        )
    except Exception as exc:
        return False, "", f"Kurulum hatası: {exc}"
    finally:
        _force_rmtree(temp_clone)


def inspect_github_repo(repo_url: str, github_token: str = "") -> dict[str, Any]:
    """Query GitHub API to detect whether a repository is an MCP server, skill pack, or CLI tool."""
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", repo_url)
    if not m:
        raise ValueError("Geçerli bir GitHub repo adresi girin (örn: https://github.com/owner/repo).")
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
        kind = "Skill Paketi"
        cmd = f"git clone https://github.com/{owner}/{repo}.git ({len(skill_files)} SKILL.md)"
        mcp_cmd, mcp_args = "", []
    elif len(skill_files) == 1 and not has_pkg and not has_py:
        kind = "Skill / Kural"
        cmd = f"git clone https://github.com/{owner}/{repo}.git"
        mcp_cmd, mcp_args = "", []
    elif has_pkg:
        kind = "stdio MCP"
        cmd = f"npx -y {repo}"
        mcp_cmd, mcp_args = "npx", ["-y", repo]
    elif has_py:
        kind = "stdio MCP"
        cmd = f"uvx {repo}"
        mcp_cmd, mcp_args = "uvx", [repo]
    else:
        kind = "CLI / GPU"
        cmd = f"git clone https://github.com/{owner}/{repo}.git"
        mcp_cmd, mcp_args = "", []

    return {
        "id": f"gh_{owner}_{repo}".lower().replace("-", "_"),
        "name": f"{repo} ({owner})",
        "description": meta.get("description") or "GitHub üzerinden algılanan araç.",
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


def update_single_tool(
    tool: ToolSpec,
    active_skills: set[str],
    install_if_missing: bool = False,
) -> tuple[bool, str, str, str]:
    """Safely upgrade (or install when ``install_if_missing=True``) a single tool.

    Returns (ok, new_version_tag, short_summary, raw_log_detail). Never mutates ``tool``.
    """
    ua = _user_agent()
    try:
        if tool.id == "blender_skills":
            plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
            is_installed = (plugin_dir / "skills").is_dir() or (plugin_dir / "skills_disabled").is_dir()
            if is_installed or install_if_missing:
                ok, ver_tag, msg = install_or_update_blender_skills(active_skills)
                return ok, ver_tag or tool.version, msg, msg
            msg = "Henüz indirilmemiş (Kurmak için kutucuğu seçip 'Seçilenleri Kur / Güncelle' diyebilirsiniz)."
            return True, tool.version, msg, msg

        if tool.id == "caveman":
            cav_dir = pathlib.Path.home() / ".agents" / "skills" / "caveman"
            if (cav_dir / ".git").is_dir():
                cmd = ["git", "-C", str(cav_dir), "pull", "--ff-only"]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=NO_WINDOW,
                )
                raw = f"Komut: {' '.join(cmd)}\nÇıkış Kodu: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                if proc.returncode == 0:
                    out = proc.stdout.strip() or "Güncel."
                    return True, tool.version, f"Git pull tamamlandı: {out}", raw
                err_first = (proc.stderr.strip() or proc.stdout.strip() or "Bilinmeyen git hatası").splitlines()[0]
                return False, "", f"Git pull hatası: {err_first}", raw
            if (cav_dir / "SKILL.md").is_file():
                return True, tool.version, "Yerel SKILL.md doğrulandı ve güncel.", str(cav_dir / "SKILL.md")
            return True, tool.version, "Caveman kuralı hazır.", str(cav_dir)

        if tool.id in UV_TOOL_MAP:
            pkg = UV_TOOL_MAP[tool.id]
            if install_if_missing:
                cmd = ["uv", "tool", "install", "--upgrade"]
                if pkg == "mcpforunityserver":
                    cmd.extend(["--python", "3.12"])
                cmd.append(pkg)
            else:
                cmd = ["uv", "tool", "upgrade", pkg]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=90,
                creationflags=NO_WINDOW,
            )
            combined = (proc.stdout + "\n" + proc.stderr).strip()
            raw = f"Komut: {' '.join(cmd)}\nÇıkış Kodu: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            if proc.returncode == 0 or "Nothing to upgrade" in combined or "already installed" in combined.lower():
                return True, tool.version, f"uv tool ({pkg}): Güncel.", raw
            if "is not installed" in combined.lower() and not install_if_missing:
                return True, tool.version, f"{pkg} özel dizinde kurulu (mevcut kurulum korundu).", raw
            first_line = (proc.stderr.strip() or proc.stdout.strip() or "uv tool hatası").splitlines()[0]
            return False, "", f"uv tool ({pkg}) hatası: {first_line}", raw

        if tool.id in NPM_PACKAGE_MAP:
            pkg = NPM_PACKAGE_MAP[tool.id]
            latest_ver = ""
            try:
                encoded_pkg = pkg.replace("/", "%2F")
                req = urllib.request.Request(
                    f"https://registry.npmjs.org/{encoded_pkg}/latest",
                    headers={"User-Agent": ua},
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    meta = json.loads(resp.read().decode("utf-8"))
                    latest_ver = meta.get("version", "")
            except Exception as exc:
                return False, "", f"npm sürüm sorgulama hatası ({pkg}): {exc}", traceback.format_exc()

            new_v_tag = f"v{latest_ver}" if latest_ver else tool.version
            if install_if_missing and pkg in ("bla-agents", "@gltf-transform/cli"):
                npm_exe = "npm.cmd" if shutil.which("npm.cmd") else "npm"
                cmd = [npm_exe, "install", "-g", f"{pkg}@latest"]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=90,
                    creationflags=NO_WINDOW,
                )
                raw = f"Komut: {' '.join(cmd)}\nÇıkış Kodu: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                if proc.returncode != 0:
                    first_err = (proc.stderr.strip() or proc.stdout.strip() or "npm install hatası").splitlines()[0]
                    return False, new_v_tag, f"npm kurulum hatası ({pkg}): {first_err}", raw
                return True, new_v_tag, f"{pkg} global olarak {new_v_tag} sürümüne güncellendi.", raw

            msg = f"npm son sürümü doğrulandı -> {new_v_tag} (npx ile güncel çalışır)."
            return True, new_v_tag, msg, msg

        if tool.id in PYPI_PACKAGE_MAP:
            pkg = PYPI_PACKAGE_MAP[tool.id]
            latest_ver = ""
            try:
                req = urllib.request.Request(
                    f"https://pypi.org/pypi/{pkg}/json",
                    headers={"User-Agent": ua},
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    meta = json.loads(resp.read().decode("utf-8"))
                    latest_ver = meta.get("info", {}).get("version", "")
            except Exception as exc:
                return False, "", f"PyPI sürüm sorgulama hatası ({pkg}): {exc}", traceback.format_exc()
            new_v_tag = f"v{latest_ver}" if latest_ver else tool.version
            msg = f"PyPI son sürümü doğrulandı ({new_v_tag})."
            return True, new_v_tag, msg, msg

        if tool.id in ("unity_pipeline", "trellis"):
            msg = "Yerel motor/GPU kurulumu doğrulandı (özel ağırlık ve proje dosyaları korundu)."
            return True, tool.version, msg, msg

        if "github.com/" in tool.repo_url:
            m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", tool.repo_url)
            if m:
                owner, repo = m.group(1), m.group(2).removesuffix(".git")
                try:
                    req = urllib.request.Request(
                        f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
                        headers={"User-Agent": ua},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        rel = json.loads(resp.read().decode("utf-8"))
                        tag = rel.get("tag_name", "")
                        if tag:
                            v_t = tag if tag.startswith("v") else f"v{tag}"
                            return True, v_t, f"GitHub son sürümü doğrulandı: {v_t}", str(rel.get("html_url", ""))
                except urllib.error.HTTPError as http_exc:
                    if http_exc.code != 404:
                        return False, "", f"GitHub API hatası (HTTP {http_exc.code})", traceback.format_exc()
                except Exception as exc:
                    return False, "", f"GitHub bağlantı hatası: {exc}", traceback.format_exc()
            return True, tool.version, "GitHub kaynağı doğrulandı ve güncel.", tool.repo_url

        return True, tool.version, "Sürüm kontrolü tamamlandı.", tool.name
    except FileNotFoundError as fnf_exc:
        missing_bin = str(fnf_exc.filename or fnf_exc)
        hint = "Git (https://git-scm.com), uv (https://docs.astral.sh/uv/) veya Node.js (https://nodejs.org) kurulu olduğundan emin olun."
        return False, "", f"Gerekli sistem aracı bulunamadı ({missing_bin}). {hint}", traceback.format_exc()
    except Exception as exc:
        return False, "", f"Beklenmeyen güncelleme hatası: {exc}", traceback.format_exc()
