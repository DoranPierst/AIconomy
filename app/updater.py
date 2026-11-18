"""GitHub release checker and one-click self-updater for AIconomy (EN & TR, single version source)."""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import subprocess
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

DEFAULT_APP_REPO = "https://github.com/DoranPierst/AIconomy"


def get_source_root() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent.parent


def _iter_version_json_candidates() -> list[pathlib.Path]:
    out = [get_source_root() / "version.json"]
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            out.append(pathlib.Path(meipass) / "version.json")
    return out


def get_current_app_version() -> str:
    """Read application version from bundled/root version.json (single source of truth)."""
    for c in _iter_version_json_candidates():
        if c.is_file():
            try:
                v = str(json.loads(c.read_text(encoding="utf-8")).get("version", "")).strip()
                if v:
                    return v.lstrip("vV")
            except Exception:
                pass
    return "0.0.0"


def get_bundled_update_repo() -> str:
    for c in _iter_version_json_candidates():
        if c.is_file():
            try:
                r = str(json.loads(c.read_text(encoding="utf-8")).get("update_repo", "")).strip()
                if r:
                    return r
            except Exception:
                pass
    return ""


def resolve_effective_app_repo(saved_meta_repo: str = "") -> str:
    for candidate in (saved_meta_repo.strip(), get_bundled_update_repo(), DEFAULT_APP_REPO):
        if candidate:
            return candidate
    return DEFAULT_APP_REPO


def parse_semver(ver_str: str) -> tuple[int, ...]:
    cleaned = ver_str.strip().lstrip("vV").split("-")[0]
    parts: list[int] = []
    for p in cleaned.split("."):
        digits = re.sub(r"\D", "", p)
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def parse_github_owner_repo(repo_input: str, lang: str = "en") -> tuple[str, str]:
    s = repo_input.strip().removesuffix(".git").strip("/")
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", s)
    if m:
        return m.group(1), m.group(2)
    if "/" in s and " " not in s and not s.startswith("http"):
        parts = s.split("/")
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
    msg = (
        "Geçerli bir GitHub repo adresi girin (örn: https://github.com/DoranPierst/AIconomy)."
        if lang == "tr"
        else "Enter a valid GitHub repository URL (e.g. https://github.com/DoranPierst/AIconomy)."
    )
    raise ValueError(msg)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def resolve_github_latest_release_web(
    owner: str,
    repo: str,
    ua: str,
    timeout: float = 6.0,
) -> tuple[str, str, bool]:
    """Resolve the latest GitHub release tag via the public /releases/latest 302 redirect.

    Uses zero ``api.github.com`` rate-limit quota and requires no ``GITHUB_TOKEN``.
    Returns ``(raw_tag, html_url, github_reachable)``.
    """
    opener = urllib.request.build_opener(_NoRedirectHandler)
    url = f"https://github.com/{owner}/{repo}/releases/latest"
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": ua})
    try:
        with opener.open(req, timeout=timeout) as resp:
            final_url = resp.geturl() or url
            m = re.search(r"/releases/tag/([^/?#\s]+)", final_url)
            if m:
                raw_tag = urllib.parse.unquote(m.group(1)).strip()
                return raw_tag, final_url, True
            return "", f"https://github.com/{owner}/{repo}/releases", True
    except urllib.error.HTTPError as http_exc:
        if http_exc.code in (301, 302, 303, 307, 308):
            loc = str(http_exc.headers.get("Location", "") or "").strip()
            if loc.startswith("/"):
                loc = f"https://github.com{loc}"
            m = re.search(r"/releases/tag/([^/?#\s]+)", loc)
            if m:
                raw_tag = urllib.parse.unquote(m.group(1)).strip()
                return raw_tag, loc, True
            return "", loc or f"https://github.com/{owner}/{repo}/releases", True
        if http_exc.code == 404:
            return "", "", True
        return "", "", True
    except Exception:
        return "", "", False


def _probe_github_release_exe_url(owner: str, repo: str, raw_tag: str, ua: str, timeout: float = 5.0) -> str:
    """Check whether ``AIconomy.exe`` exists on ``raw_tag`` via a fast non-redirecting HEAD request."""
    cand = f"https://github.com/{owner}/{repo}/releases/download/{urllib.parse.quote(raw_tag)}/AIconomy.exe"
    opener = urllib.request.build_opener(_NoRedirectHandler)
    req = urllib.request.Request(cand, method="HEAD", headers={"User-Agent": ua})
    try:
        with opener.open(req, timeout=timeout):
            return cand
    except urllib.error.HTTPError as http_exc:
        if http_exc.code in (200, 301, 302, 303, 307, 308):
            return cand
    except Exception:
        pass
    return ""


@dataclasses.dataclass
class UpdateCheckResult:
    ok: bool
    has_update: bool
    local_version: str
    remote_version: str
    changelog: str
    release_notes_url: str
    exe_download_url: str
    repo_url: str
    can_git_pull: bool
    message: str


def check_for_app_updates(repo_input: str, github_token: str = "", lang: str = "en") -> UpdateCheckResult:
    is_tr = lang == "tr"
    local_ver = get_current_app_version()
    if not repo_input.strip():
        repo_input = resolve_effective_app_repo("")

    try:
        owner, repo = parse_github_owner_repo(repo_input, lang=lang)
    except ValueError as exc:
        return UpdateCheckResult(False, False, local_ver, local_ver, "", "", "", repo_input, False, str(exc))

    clean_repo_url = f"https://github.com/{owner}/{repo}"
    ua = f"AIconomy/{local_ver}"
    headers = {"User-Agent": ua}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    remote_ver = ""
    changelog = ""
    notes_url = f"{clean_repo_url}/releases"
    exe_url = ""
    github_reachable = False

    if github_token:
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{owner}/{repo}/releases/latest", headers=headers)
            with urllib.request.urlopen(req, timeout=7) as resp:
                github_reachable = True
                rel = json.loads(resp.read().decode("utf-8"))
                tag = str(rel.get("tag_name", "")).lstrip("vV")
                if tag:
                    remote_ver = tag
                    changelog = str(rel.get("body", "")).strip()
                if rel.get("html_url"):
                    notes_url = str(rel["html_url"])
                for asset in rel.get("assets", []):
                    name = str(asset.get("name", ""))
                    if name.lower().endswith(".exe"):
                        exe_url = str(asset.get("browser_download_url", ""))
                        break
        except urllib.error.HTTPError:
            github_reachable = True
        except Exception:
            pass

    if not remote_ver:
        raw_tag, tag_url, web_ok = resolve_github_latest_release_web(owner, repo, ua)
        if web_ok:
            github_reachable = True
        if raw_tag:
            remote_ver = raw_tag.lstrip("vV")
            if tag_url:
                notes_url = tag_url
            exe_url = _probe_github_release_exe_url(owner, repo, raw_tag, ua)

    for branch in ("main", "master"):
        try:
            v_req = urllib.request.Request(
                f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/version.json",
                headers={"User-Agent": ua},
            )
            with urllib.request.urlopen(v_req, timeout=6) as resp:
                github_reachable = True
                v_data = json.loads(resp.read().decode("utf-8"))
                v_str = str(v_data.get("version", "")).lstrip("vV").strip()
                v_chg = str(v_data.get("changelog", "")).strip()
                if v_str and (not remote_ver or parse_semver(v_str) > parse_semver(remote_ver)):
                    remote_ver = v_str
                    if v_chg:
                        changelog = v_chg
                    if notes_url == f"{clean_repo_url}/releases":
                        notes_url = f"{clean_repo_url}/commits/{branch}"
                elif v_str and parse_semver(v_str) == parse_semver(remote_ver) and not changelog and v_chg:
                    changelog = v_chg
                break
        except urllib.error.HTTPError:
            github_reachable = True
            continue
        except Exception:
            continue

    if not remote_ver:
        if github_reachable:
            msg = (
                f"AIconomy güncel (v{local_ver}) — daha yeni bir sürüm bulunmuyor."
                if is_tr
                else f"AIconomy is up to date (v{local_ver})."
            )
            return UpdateCheckResult(True, False, local_ver, local_ver, "", notes_url, "", clean_repo_url, False, msg)
        msg = (
            "GitHub sunucusuna ulaşılamadı (internet bağlantınızı kontrol edin)."
            if is_tr
            else "Could not reach GitHub (check your internet connection)."
        )
        return UpdateCheckResult(False, False, local_ver, local_ver, "", "", "", clean_repo_url, False, msg)

    has_upd = parse_semver(remote_ver) > parse_semver(local_ver)
    src_root = get_source_root()
    git_dir_exists = (src_root / ".git").is_dir() or (src_root.parent / ".git").is_dir()

    if has_upd:
        msg = f"Güncelleme mevcut: v{local_ver} -> v{remote_ver}" if is_tr else f"Update available: v{local_ver} -> v{remote_ver}"
    else:
        msg = f"AIconomy güncel (v{local_ver})" if is_tr else f"AIconomy is up to date (v{local_ver})"

    return UpdateCheckResult(
        ok=True,
        has_update=has_upd,
        local_version=local_ver,
        remote_version=remote_ver,
        changelog=changelog,
        release_notes_url=notes_url,
        exe_download_url=exe_url,
        repo_url=clean_repo_url,
        can_git_pull=git_dir_exists,
        message=msg,
    )


def apply_self_update(
    check_res: UpdateCheckResult,
    github_token: str = "",
    progress_cb: Callable[[int, int], None] | None = None,
    lang: str = "en",
) -> tuple[bool, str, str]:
    """Download/pull update and return (ok, action_kind ['swap_exe' | 'restart_py' | 'none'], message)."""
    is_tr = lang == "tr"
    is_frozen = getattr(sys, "frozen", False)
    local_ver = get_current_app_version()

    if is_frozen and check_res.exe_download_url:
        current_exe = pathlib.Path(sys.executable).resolve()
        new_exe = current_exe.with_suffix(".exe.new")
        headers = {"User-Agent": f"AIconomy/{local_ver}"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        try:
            req = urllib.request.Request(check_res.exe_download_url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(new_exe, "wb") as out_f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb and total > 0:
                            progress_cb(downloaded, total)

            if not new_exe.is_file() or new_exe.stat().st_size < 1_000_000:
                new_exe.unlink(missing_ok=True)
                msg = (
                    "İndirilen dosya eksik görünüyor; mevcut sürüm korundu."
                    if is_tr
                    else "Downloaded update file looks incomplete; keeping current version."
                )
                return False, "none", msg
            with open(new_exe, "rb") as chk:
                if chk.read(2) != b"MZ":
                    new_exe.unlink(missing_ok=True)
                    msg = (
                        "İndirilen dosya geçerli bir Windows .exe değil; mevcut sürüm korundu."
                        if is_tr
                        else "Downloaded file is not a valid Windows executable; keeping current version."
                    )
                    return False, "none", msg

            bat_path = current_exe.parent / "_apply_update.bat"
            bat_content = (
                "@echo off\r\n"
                "chcp 65001 >nul\r\n"
                "set /a tries=0\r\n"
                ":retry\r\n"
                "timeout /t 1 /nobreak >nul\r\n"
                f'move /y "{new_exe}" "{current_exe}" >nul 2>&1\r\n'
                f'if exist "{new_exe}" (\r\n'
                "  set /a tries+=1\r\n"
                "  if %tries% lss 15 goto retry\r\n"
                ")\r\n"
                f'start "" "{current_exe}"\r\n'
                'del "%~f0"\r\n'
            )
            bat_path.write_text(bat_content, encoding="utf-8")
            subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=NO_WINDOW)
            msg = (
                f"v{check_res.remote_version} indirildi; uygulama şimdi yeniden başlatılacak."
                if is_tr
                else f"Downloaded v{check_res.remote_version}; restarting AIconomy now."
            )
            return True, "swap_exe", msg
        except Exception as exc:
            new_exe.unlink(missing_ok=True)
            prefix = ".exe indirme hatası" if is_tr else "Executable download failed"
            return False, "none", f"{prefix}: {exc}\n\n{traceback.format_exc()}"

    src_root = get_source_root()
    git_dir = src_root if (src_root / ".git").is_dir() else (src_root.parent if (src_root.parent / ".git").is_dir() else None)
    if git_dir is not None:
        try:
            cmd = ["git", "-C", str(git_dir), "pull", "--ff-only"]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45,
                creationflags=NO_WINDOW,
            )
            if proc.returncode != 0:
                raw = f"Command: {' '.join(cmd)}\nExit code: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                err_txt = proc.stderr.strip() or proc.stdout.strip()
                prefix = "git pull başarısız" if is_tr else "git pull failed"
                return False, "none", f"{prefix}: {err_txt}\n\n{raw}"
            if not is_frozen:
                msg = (
                    f"Kaynak kodlar v{check_res.remote_version} sürümüne güncellendi; yeniden başlatılıyor..."
                    if is_tr
                    else f"Updated source to v{check_res.remote_version}; restarting..."
                )
                return True, "restart_py", msg
            msg = (
                f"Kaynak kodlar çekildi ({proc.stdout.strip()}). .exe güncellemek için build_exe.bat çalıştırabilirsiniz."
                if is_tr
                else f"Source updated ({proc.stdout.strip()}). Run build_exe.bat to rebuild AIconomy.exe."
            )
            return True, "none", msg
        except Exception as exc:
            prefix = "Git güncelleme hatası" if is_tr else "Git update failed"
            return False, "none", f"{prefix}: {exc}\n\n{traceback.format_exc()}"

    msg = (
        "Bu sürüm için GitHub Releases altında derlenmiş AIconomy.exe bulunamadı."
        if is_tr
        else "No compiled AIconomy.exe asset was found on this GitHub release."
    )
    return False, "none", msg


def restart_running_python_app() -> None:
    os.execl(sys.executable, sys.executable, *sys.argv)
