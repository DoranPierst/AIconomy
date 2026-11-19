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
from .mcp_config import _dedupe_yaml_frontmatter_keys, _force_rmtree, _remove_agy_skill_mirrors
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


def _repo_url_matches_github(raw_meta_text: str, owner: str, repo: str) -> bool:
    """Return True when a registry repository/homepage string references github.com/<owner>/<repo>."""
    if not raw_meta_text:
        return False
    pat = re.compile(rf"github\.com[:/]{re.escape(owner)}/{re.escape(repo)}(?:\.git|/|$|\"|\s|#)", re.IGNORECASE)
    return bool(pat.search(raw_meta_text))


def _verify_npm_package_ownership(
    owner: str,
    repo: str,
    branch: str,
    headers: dict[str, str],
) -> tuple[bool, str, str]:
    """Read package.json from GitHub and verify npm registry repository.url points back to owner/repo."""
    try:
        raw_req = urllib.request.Request(
            f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/package.json",
            headers={"User-Agent": headers.get("User-Agent", _user_agent())},
        )
        with urllib.request.urlopen(raw_req, timeout=6) as resp:
            pkg_json = json.loads(resp.read().decode("utf-8"))
        pkg_name = str(pkg_json.get("name") or "").strip()
        if not pkg_name or pkg_json.get("private") is True:
            return False, "", ""

        enc = pkg_name.replace("/", "%2F")
        npm_req = urllib.request.Request(
            f"https://registry.npmjs.org/{enc}/latest",
            headers={"User-Agent": headers.get("User-Agent", _user_agent())},
        )
        with urllib.request.urlopen(npm_req, timeout=6) as resp:
            npm_meta = json.loads(resp.read().decode("utf-8"))

        ver = str(npm_meta.get("version") or "").strip()
        repo_blob = json.dumps(
            {"repository": npm_meta.get("repository"), "homepage": npm_meta.get("homepage")},
            ensure_ascii=False,
        )
        if ver and _repo_url_matches_github(repo_blob, owner, repo):
            return True, pkg_name, ver
        return False, pkg_name, ver
    except Exception:
        return False, "", ""


def _verify_pypi_package_ownership(
    owner: str,
    repo: str,
    branch: str,
    headers: dict[str, str],
) -> tuple[bool, str, str]:
    """Read pyproject.toml from GitHub and verify PyPI project_urls/home_page points back to owner/repo."""
    try:
        raw_req = urllib.request.Request(
            f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/pyproject.toml",
            headers={"User-Agent": headers.get("User-Agent", _user_agent())},
        )
        with urllib.request.urlopen(raw_req, timeout=6) as resp:
            toml_txt = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r'(?m)^\s*name\s*=\s*["\']([A-Za-z0-9._-]+)["\']', toml_txt)
        if not m:
            return False, "", ""
        pkg_name = m.group(1).strip()

        pypi_req = urllib.request.Request(
            f"https://pypi.org/pypi/{pkg_name}/json",
            headers={"User-Agent": headers.get("User-Agent", _user_agent())},
        )
        with urllib.request.urlopen(pypi_req, timeout=6) as resp:
            pypi_meta = json.loads(resp.read().decode("utf-8"))

        info = pypi_meta.get("info") or {}
        ver = str(info.get("version") or "").strip()
        urls_blob = json.dumps(
            {"project_urls": info.get("project_urls"), "home_page": info.get("home_page")},
            ensure_ascii=False,
        )
        if ver and _repo_url_matches_github(urls_blob, owner, repo):
            return True, pkg_name, ver
        return False, pkg_name, ver
    except Exception:
        return False, "", ""


def inspect_github_repo(repo_url: str, github_token: str = "", lang: str = "en") -> dict[str, Any]:
    """Query GitHub API and verify npm/PyPI repository ownership to prevent typosquatting."""
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

    detected_ver = "v1.0.0"
    registry_verified = True
    security_warning = ""

    if len(skill_files) > 1:
        kind = "skill_pack"
        cmd = f"git clone https://github.com/{owner}/{repo}.git"
        mcp_cmd, mcp_args = "", []
    elif len(skill_files) == 1 and not has_pkg and not has_py:
        kind = "rule"
        cmd = f"git clone https://github.com/{owner}/{repo}.git"
        mcp_cmd, mcp_args = "", []
    elif has_pkg:
        ok_npm, pkg_name, pkg_ver = _verify_npm_package_ownership(owner, repo, branch, headers)
        if ok_npm and pkg_name and pkg_ver:
            kind = "stdio"
            detected_ver = f"v{pkg_ver.lstrip('vV')}"
            pinned = f"{pkg_name}@{pkg_ver}"
            cmd = f"npx -y {pinned}"
            mcp_cmd, mcp_args = "npx", ["-y", pinned]
        else:
            kind = "cli"
            cmd = f"git clone https://github.com/{owner}/{repo}.git"
            mcp_cmd, mcp_args = "", []
            registry_verified = False
            cand_lbl = pkg_name or repo
            security_warning = (
                f"Güvenlik uyarısı: npm üzerindeki '{cand_lbl}' paketinin bu GitHub deposuna ({owner}/{repo}) ait olduğu doğrulanamadı. "
                "Olası sahte paket (typosquatting) riskine karşı otomatik npx komutu engellendi; güvenli git clone moduna alındı."
                if is_tr
                else f"Security warning: Could not verify that npm package '{cand_lbl}' is owned by {owner}/{repo}. "
                "Automatic npx execution was blocked to prevent typosquatting; switched to safe git clone."
            )
    elif has_py:
        ok_pypi, pkg_name, pkg_ver = _verify_pypi_package_ownership(owner, repo, branch, headers)
        if ok_pypi and pkg_name and pkg_ver:
            kind = "stdio"
            detected_ver = f"v{pkg_ver.lstrip('vV')}"
            pinned = f"{pkg_name}=={pkg_ver}"
            cmd = f"uvx {pinned}"
            mcp_cmd, mcp_args = "uvx", [pinned]
        else:
            kind = "cli"
            cmd = f"git clone https://github.com/{owner}/{repo}.git"
            mcp_cmd, mcp_args = "", []
            registry_verified = False
            cand_lbl = pkg_name or repo
            security_warning = (
                f"Güvenlik uyarısı: PyPI üzerindeki '{cand_lbl}' paketinin bu GitHub deposuna ({owner}/{repo}) ait olduğu doğrulanamadı. "
                "Olası sahte paket riskine karşı otomatik uvx komutu engellendi; güvenli git clone moduna alındı."
                if is_tr
                else f"Security warning: Could not verify that PyPI package '{cand_lbl}' is owned by {owner}/{repo}. "
                "Automatic uvx execution was blocked to prevent typosquatting; switched to safe git clone."
            )
    else:
        kind = "cli"
        cmd = f"git clone https://github.com/{owner}/{repo}.git"
        mcp_cmd, mcp_args = "", []

    return {
        "id": f"gh_{owner}_{repo}".lower().replace("-", "_"),
        "name": f"{repo} ({owner})",
        "version": detected_ver,
        "description": meta.get("description") or ("GitHub üzerinden algılanan araç." if is_tr else "Tool detected from GitHub."),
        "stars": meta.get("stargazers_count", 0),
        "kind": kind,
        "install_cmd": cmd,
        "mcp_command": mcp_cmd,
        "mcp_args": mcp_args,
        "skill_count": len(skill_files),
        "needs_api_key": needs_key,
        "repo_url": f"https://github.com/{owner}/{repo}",
        "registry_verified": registry_verified,
        "security_warning": security_warning,
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
            active_dir = pathlib.Path.home() / ".agents" / "skills" / "caveman"
            disabled_dir = pathlib.Path.home() / ".agents" / "skills_disabled" / "caveman"
            cav_dir = active_dir if active_dir.is_dir() else (disabled_dir if disabled_dir.is_dir() else active_dir)
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
            if not install_if_missing:
                msg = (
                    "Caveman henüz indirilmedi."
                    if is_tr
                    else "Caveman is not installed on disk yet."
                )
                return True, tool.version, msg, str(cav_dir)

            # Brand-new PC install: fetch official SKILL.md via HTTPS (no Git required), fallback to git clone
            raw_url = "https://raw.githubusercontent.com/JuliusBrussee/caveman/main/skills/caveman/SKILL.md"
            try:
                req = urllib.request.Request(raw_url, headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    skill_txt = resp.read().decode("utf-8", errors="replace")
                if "name:" in skill_txt and len(skill_txt.strip()) > 60:
                    active_dir.mkdir(parents=True, exist_ok=True)
                    clean_md = _dedupe_yaml_frontmatter_keys(skill_txt)
                    (active_dir / "SKILL.md").write_text(clean_md, encoding="utf-8")
                    msg = (
                        f"Caveman kuralı indirildi ve kuruldu: {active_dir}"
                        if is_tr
                        else f"Downloaded and installed Caveman rule: {active_dir}"
                    )
                    return True, tool.version, msg, raw_url
            except Exception as dl_exc:
                dl_err = str(dl_exc)
            else:
                dl_err = "Unexpected SKILL.md payload"

            git_exe = shutil.which("git.exe") or shutil.which("git")
            if not git_exe:
                err_msg = (
                    f"Caveman indirilemedi ({dl_err}) ve Git bulunamadı."
                    if is_tr
                    else f"Failed to download Caveman ({dl_err}) and Git was not found."
                )
                return False, "", err_msg, raw_url

            tmp_cav = pathlib.Path(tempfile.mkdtemp(prefix="aiconomy_cav_"))
            try:
                clone_dst = tmp_cav / "repo"
                cmd = [git_exe, "clone", "--depth", "1", "https://github.com/JuliusBrussee/caveman.git", str(clone_dst)]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
                raw = _fmt_cmd_raw(cmd, proc, is_tr)
                if proc.returncode != 0:
                    err_first = (proc.stderr.strip() or proc.stdout.strip() or "git clone error").splitlines()[0]
                    return False, "", f"git clone: {err_first}", raw
                src_md = clone_dst / "skills" / "caveman" / "SKILL.md"
                if not src_md.is_file():
                    src_md = clone_dst / "SKILL.md"
                if not src_md.is_file():
                    return (
                        False,
                        "",
                        "Caveman deposunda SKILL.md bulunamadı." if is_tr else "SKILL.md not found in Caveman repository.",
                        raw,
                    )
                active_dir.mkdir(parents=True, exist_ok=True)
                clean_md = _dedupe_yaml_frontmatter_keys(src_md.read_text(encoding="utf-8", errors="replace"))
                (active_dir / "SKILL.md").write_text(clean_md, encoding="utf-8")
                msg = (
                    f"Caveman kuralı Git üzerinden kuruldu: {active_dir}"
                    if is_tr
                    else f"Installed Caveman rule via Git: {active_dir}"
                )
                return True, tool.version, msg, raw
            finally:
                _force_rmtree(tmp_cav)

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
            target_spec = f"{pkg}@{latest_ver}" if latest_ver else pkg
            if install_if_missing and pkg in ("bla-agents", "@gltf-transform/cli"):
                npm_exe = "npm.cmd" if shutil.which("npm.cmd") else "npm"
                cmd = [npm_exe, "install", "-g", "--ignore-scripts", "--no-fund", "--no-audit", target_spec]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, creationflags=NO_WINDOW)
                raw = _fmt_cmd_raw(cmd, proc, is_tr)
                if proc.returncode != 0:
                    first_err = (proc.stderr.strip() or proc.stdout.strip() or "npm install error").splitlines()[0]
                    return False, new_v_tag, f"npm install ({pkg}): {first_err}", raw
                msg = (
                    f"{pkg} global olarak {new_v_tag} sürümüne güncellendi (--ignore-scripts)."
                    if is_tr
                    else f"Updated {pkg} globally to {new_v_tag} (--ignore-scripts)."
                )
                return True, new_v_tag, msg, raw

            msg = (
                f"npm son sürümü doğrulandı -> {new_v_tag}."
                if is_tr
                else f"Verified latest npm version -> {new_v_tag}."
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
            cmd = [npm_exe, "install", "-g", "--ignore-scripts", "--no-fund", "--no-audit", pkg_spec]
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

            clean_pkg = re.split(r"==|@", pkg_spec, maxsplit=1)[0] if not pkg_spec.startswith("@") else pkg_spec.removesuffix("@latest")
            if from_spec:
                cmd = [uv_exe, "tool", "install", "--upgrade", "--from", from_spec, clean_pkg]
            else:
                cmd = [uv_exe, "tool", "install", "--upgrade", pkg_spec.removesuffix("@latest")]

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
            disabled_dir = pathlib.Path.home() / ".agents" / "skills_disabled" / tool.id
            dest_dir.parent.mkdir(parents=True, exist_ok=True)
            if not dest_dir.exists() and disabled_dir.is_dir():
                shutil.move(str(disabled_dir), str(dest_dir))
            elif disabled_dir.exists():
                _force_rmtree(disabled_dir)
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


def sync_pinned_version_on_tool(tool: ToolSpec, new_ver: str) -> None:
    """Update pinned @X.Y.Z / ==X.Y.Z version specifiers in tool.mcp_args and tool.install_cmd."""
    clean_v = (new_ver or "").strip().lstrip("vV")
    if not clean_v:
        return
    if tool.mcp_command == "npx" and tool.mcp_args:
        updated_args: list[str] = []
        changed_from_to: tuple[str, str] | None = None
        for a in tool.mcp_args:
            if not a.startswith("-") and changed_from_to is None:
                base = _strip_npm_dist_tag(a)
                if base and base != a:
                    new_spec = f"{base}@{clean_v}"
                    changed_from_to = (a, new_spec)
                    updated_args.append(new_spec)
                    continue
            updated_args.append(a)
        tool.mcp_args = updated_args
        if changed_from_to and changed_from_to[0] in tool.install_cmd:
            tool.install_cmd = tool.install_cmd.replace(changed_from_to[0], changed_from_to[1])
    elif tool.mcp_command == "uvx" and tool.mcp_args:
        updated_uv: list[str] = []
        changed_uv: tuple[str, str] | None = None
        for a in tool.mcp_args:
            if not a.startswith("-") and "==" in a and changed_uv is None:
                base = a.split("==", 1)[0]
                new_spec = f"{base}=={clean_v}"
                changed_uv = (a, new_spec)
                updated_uv.append(new_spec)
                continue
            updated_uv.append(a)
        tool.mcp_args = updated_uv
        if changed_uv and changed_uv[0] in tool.install_cmd:
            tool.install_cmd = tool.install_cmd.replace(changed_uv[0], changed_uv[1])


def can_uninstall_tool_from_disk(tool: ToolSpec) -> bool:
    """Return True when AIconomy can cleanly uninstall this tool's package/files from disk."""
    if tool.id in ("unity_pipeline", "trellis"):
        return False
    if tool.id in ("blender_skills", "caveman") or tool.id in UV_TOOL_MAP or tool.id in NPM_PACKAGE_MAP:
        return True
    cmd_text = (tool.install_cmd or "").strip()
    if tool.mcp_command in ("npx", "uvx") or cmd_text.startswith(("npx ", "npm ", "uvx ", "uv ", "git clone ")):
        return True
    return False


def uninstall_library_tool(tool: ToolSpec, lang: str = "en") -> tuple[bool, str, str]:
    """Remove an installed plugin package or skill directory from the user's PC.

    Returns (ok, short_summary, raw_log_detail). Never mutates ``tool``.
    """
    is_tr = lang == "tr"
    try:
        if tool.id == "blender_skills":
            target_root = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
            if target_root.exists():
                _force_rmtree(target_root)
            msg = "Blender Skills diskten kaldırıldı." if is_tr else "Uninstalled Blender Skills from disk."
            return True, msg, str(target_root)

        if tool.id == "caveman":
            for sub in ("skills", "skills_disabled"):
                p = pathlib.Path.home() / ".agents" / sub / "caveman"
                if p.exists():
                    _force_rmtree(p)
            _remove_agy_skill_mirrors(pathlib.Path.home() / ".gemini" / "config" / "skills", "caveman")
            msg = "Caveman kuralı diskten kaldırıldı." if is_tr else "Uninstalled Caveman rule from disk."
            return True, msg, str(pathlib.Path.home() / ".agents")

        if tool.id in UV_TOOL_MAP:
            pkg = UV_TOOL_MAP[tool.id]
            uv_exe = shutil.which("uv.exe") or shutil.which("uv")
            if not uv_exe:
                return False, ("uv bulunamadı." if is_tr else "uv not found on PATH."), pkg
            cmd = [uv_exe, "tool", "uninstall", pkg]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
            raw = _fmt_cmd_raw(cmd, proc, is_tr)
            comb = (proc.stdout + "\n" + proc.stderr).lower()
            if proc.returncode == 0 or "is not installed" in comb or "nothing to uninstall" in comb:
                msg = f"uv aracı kaldırıldı: {pkg}" if is_tr else f"Uninstalled uv tool: {pkg}"
                return True, msg, raw
            err_line = (proc.stderr.strip() or proc.stdout.strip() or "uv uninstall error").splitlines()[0]
            return False, f"uv ({pkg}): {err_line}", raw

        cmd_text = (tool.install_cmd or "").strip()
        if tool.id in NPM_PACKAGE_MAP or tool.mcp_command == "npx" or cmd_text.startswith(("npx ", "npm ")):
            pkg_raw = NPM_PACKAGE_MAP.get(tool.id) or _extract_npm_package_spec(tool)
            base_pkg = _strip_npm_dist_tag(pkg_raw)
            if not base_pkg:
                return False, ("npm paket adı bulunamadı." if is_tr else "Could not determine npm package."), cmd_text
            npm_exe = shutil.which("npm.cmd") or shutil.which("npm")
            if not npm_exe:
                return False, ("npm bulunamadı." if is_tr else "npm not found on PATH."), base_pkg
            cmd = [npm_exe, "uninstall", "-g", base_pkg]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, creationflags=NO_WINDOW)
            raw = _fmt_cmd_raw(cmd, proc, is_tr)
            if proc.returncode == 0:
                msg = f"npm paketi bilgisayardan kaldırıldı: {base_pkg}" if is_tr else f"Uninstalled npm package: {base_pkg}"
                return True, msg, raw
            err_line = (proc.stderr.strip() or proc.stdout.strip() or "npm uninstall error").splitlines()[0]
            return False, f"npm ({base_pkg}): {err_line}", raw

        if tool.mcp_command == "uvx" or cmd_text.startswith(("uvx ", "uv ")):
            uv_exe = shutil.which("uv.exe") or shutil.which("uv")
            if not uv_exe:
                return False, ("uv bulunamadı." if is_tr else "uv not found on PATH."), cmd_text
            args_src = list(tool.mcp_args) if tool.mcp_command == "uvx" and tool.mcp_args else cmd_text.split()[1:]
            pkg_spec = ""
            idx = 0
            while idx < len(args_src):
                tok = args_src[idx]
                if tok == "--from" and idx + 1 < len(args_src):
                    idx += 2
                    continue
                if tok.startswith("-"):
                    idx += 1
                    continue
                pkg_spec = tok
                break
            clean_pkg = re.split(r"==|@", pkg_spec, maxsplit=1)[0]
            if not clean_pkg:
                return False, ("uv paket adı bulunamadı." if is_tr else "Could not determine uv package."), cmd_text
            cmd = [uv_exe, "tool", "uninstall", clean_pkg]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
            raw = _fmt_cmd_raw(cmd, proc, is_tr)
            comb = (proc.stdout + "\n" + proc.stderr).lower()
            if proc.returncode == 0 or "is not installed" in comb or "nothing to uninstall" in comb:
                msg = f"uv aracı bilgisayardan kaldırıldı: {clean_pkg}" if is_tr else f"Uninstalled uv tool: {clean_pkg}"
                return True, msg, raw
            err_line = (proc.stderr.strip() or proc.stdout.strip() or "uv uninstall error").splitlines()[0]
            return False, f"uv ({clean_pkg}): {err_line}", raw

        if cmd_text.startswith("git clone "):
            for sub in ("skills", "skills_disabled"):
                p = pathlib.Path.home() / ".agents" / sub / tool.id
                if p.exists():
                    _force_rmtree(p)
            _remove_agy_skill_mirrors(pathlib.Path.home() / ".gemini" / "config" / "skills", tool.id)
            dest_dir = pathlib.Path.home() / ".agents" / "skills" / tool.id
            msg = f"Skill klasörü silindi: {dest_dir}" if is_tr else f"Removed skill folder: {dest_dir}"
            return True, msg, str(dest_dir)

        msg = "Panelden çıkarıldı." if is_tr else "Removed from workspace."
        return True, msg, cmd_text
    except Exception as exc:
        msg = f"Kaldırma hatası: {exc}" if is_tr else f"Uninstall error: {exc}"
        return False, msg, traceback.format_exc()
