"""Locked official GitHub release checker and SHA-256 verified self-updater for AIconomy (EN & TR)."""
from __future__ import annotations

import dataclasses
import hashlib
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

OFFICIAL_OWNER = "DoranPierst"
OFFICIAL_REPO = "AIconomy"
DEFAULT_APP_REPO = f"https://github.com/{OFFICIAL_OWNER}/{OFFICIAL_REPO}"
_ALLOWED_DOWNLOAD_HOSTS = (
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)


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


def is_official_app_repo(repo_input: str) -> bool:
    """Return True only when ``repo_input`` points to the official HTTPS DoranPierst/AIconomy repository."""
    s = (repo_input or "").strip().removesuffix(".git").strip("/")
    if not s:
        return False
    m = re.fullmatch(r"https://github\.com/([^/\s]+)/([^/\s#?]+)", s, flags=re.IGNORECASE)
    if m:
        return m.group(1).lower() == OFFICIAL_OWNER.lower() and m.group(2).lower() == OFFICIAL_REPO.lower()
    if "/" in s and " " not in s and not s.startswith(("http://", "https://")):
        parts = s.split("/")
        if len(parts) == 2:
            return parts[0].lower() == OFFICIAL_OWNER.lower() and parts[1].lower() == OFFICIAL_REPO.lower()
    return False


def resolve_effective_app_repo(_saved_meta_repo: str = "") -> str:
    """Always return the pinned official AIconomy repository (prevents state-file update hijacking)."""
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
    """Resolve the latest GitHub release tag via the public /releases/latest 302 redirect."""
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


def _normalize_sha256_digest(raw_digest: str) -> str:
    val = (raw_digest or "").strip().lower()
    if val.startswith("sha256:"):
        val = val.split(":", 1)[1].strip()
    if re.fullmatch(r"[0-9a-f]{64}", val):
        return val
    return ""


def _fetch_release_exe_metadata_api(
    owner: str,
    repo: str,
    headers: dict[str, str],
    tag_name: str = "",
) -> tuple[str, str, str, str, str]:
    """Return (clean_ver, changelog, html_url, exe_download_url, exe_sha256) from GitHub Releases API."""
    endpoint = (
        f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{urllib.parse.quote(tag_name)}"
        if tag_name
        else f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    )
    req = urllib.request.Request(endpoint, headers=headers)
    with urllib.request.urlopen(req, timeout=7) as resp:
        rel = json.loads(resp.read().decode("utf-8"))
    ver = str(rel.get("tag_name", "")).strip().lstrip("vV")
    body = str(rel.get("body", "")).strip()
    html_url = str(rel.get("html_url", ""))
    exe_url = ""
    exe_sha = ""
    for asset in rel.get("assets", []):
        name = str(asset.get("name", ""))
        if name.lower().endswith(".exe"):
            exe_url = str(asset.get("browser_download_url", ""))
            exe_sha = _normalize_sha256_digest(str(asset.get("digest", "")))
            break
    if not exe_sha and body:
        m = re.search(r"\b([0-9a-fA-F]{64})\b", body)
        if m:
            exe_sha = m.group(1).lower()
    return ver, body, html_url, exe_url, exe_sha


def _is_trusted_download_url(exe_url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(exe_url)
    except Exception:
        return False
    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_DOWNLOAD_HOSTS:
        return False
    if host == "github.com":
        expected_prefix = f"/{OFFICIAL_OWNER.lower()}/{OFFICIAL_REPO.lower()}/releases/download/"
        return parsed.path.lower().startswith(expected_prefix)
    return True


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
    exe_sha256: str = ""


def check_for_app_updates(repo_input: str = "", github_token: str = "", lang: str = "en") -> UpdateCheckResult:
    is_tr = lang == "tr"
    local_ver = get_current_app_version()
    candidate = repo_input.strip() or DEFAULT_APP_REPO

    if not is_official_app_repo(candidate):
        sec_msg = (
            f"Güvenlik engeli: Yalnızca resmi {DEFAULT_APP_REPO} güncelleme kaynağına izin verilir."
            if is_tr
            else f"Security block: Only the official {DEFAULT_APP_REPO} update repository is permitted."
        )
        return UpdateCheckResult(False, False, local_ver, local_ver, "", "", "", DEFAULT_APP_REPO, False, sec_msg)

    owner, repo = OFFICIAL_OWNER, OFFICIAL_REPO
    clean_repo_url = DEFAULT_APP_REPO
    ua = f"AIconomy/{local_ver}"
    headers = {"User-Agent": ua, "Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    remote_ver = ""
    changelog = ""
    notes_url = f"{clean_repo_url}/releases"
    exe_url = ""
    exe_sha256 = ""
    github_reachable = False

    try:
        api_ver, api_body, api_html, api_exe, api_sha = _fetch_release_exe_metadata_api(owner, repo, headers)
        github_reachable = True
        if api_ver:
            remote_ver = api_ver
            changelog = api_body
        if api_html:
            notes_url = api_html
        if api_exe:
            exe_url = api_exe
        if api_sha:
            exe_sha256 = api_sha
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
                    if exe_url and parse_semver(v_str) > parse_semver(remote_ver):
                        # Newer commit on main without a compiled release yet -> don't reuse older tag's .exe!
                        exe_url = ""
                        exe_sha256 = ""
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
        exe_sha256=exe_sha256,
    )


def verify_file_sha256(file_path: pathlib.Path, expected_sha256: str) -> tuple[bool, str]:
    """Compute SHA-256 of ``file_path`` and verify exact match against ``expected_sha256``."""
    norm_exp = _normalize_sha256_digest(expected_sha256)
    if not norm_exp:
        return False, ""
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    actual = h.hexdigest().lower()
    return actual == norm_exp, actual


def apply_self_update(
    check_res: UpdateCheckResult,
    github_token: str = "",
    progress_cb: Callable[[int, int], None] | None = None,
    lang: str = "en",
) -> tuple[bool, str, str]:
    """Download/pull update with mandatory official repo & SHA-256 verification."""
    is_tr = lang == "tr"
    is_frozen = getattr(sys, "frozen", False)
    local_ver = get_current_app_version()

    if not is_official_app_repo(check_res.repo_url or DEFAULT_APP_REPO):
        msg = (
            "Güvenlik engeli: Resmi olmayan güncelleme kaynağı reddedildi."
            if is_tr
            else "Security block: Untrusted update repository rejected."
        )
        return False, "none", msg

    if is_frozen and check_res.exe_download_url:
        if not _is_trusted_download_url(check_res.exe_download_url):
            msg = (
                "Güvenlik engeli: İndirme adresi resmi GitHub kaynağına ait değil."
                if is_tr
                else "Security block: Download URL does not belong to official GitHub releases."
            )
            return False, "none", msg

        current_exe = pathlib.Path(sys.executable).resolve()
        new_exe = current_exe.with_suffix(".exe.new")
        headers = {"User-Agent": f"AIconomy/{local_ver}", "Accept": "application/vnd.github+json"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        expected_sha = _normalize_sha256_digest(check_res.exe_sha256)
        if not expected_sha and check_res.remote_version:
            try:
                _v, _b, _h, _u, fetched_sha = _fetch_release_exe_metadata_api(
                    OFFICIAL_OWNER,
                    OFFICIAL_REPO,
                    headers,
                    tag_name=f"v{check_res.remote_version.lstrip('vV')}",
                )
                expected_sha = _normalize_sha256_digest(fetched_sha)
            except Exception:
                pass

        if not expected_sha:
            msg = (
                "Güvenlik engeli: Resmi SHA-256 bütünlük özeti doğrulanamadığı için güncelleme durduruldu."
                if is_tr
                else "Security block: Could not retrieve official SHA-256 digest; update aborted."
            )
            return False, "none", msg

        try:
            dl_headers = {"User-Agent": f"AIconomy/{local_ver}"}
            if github_token:
                dl_headers["Authorization"] = f"Bearer {github_token}"
            req = urllib.request.Request(check_res.exe_download_url, headers=dl_headers)
            hasher = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(new_exe, "wb") as out_f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        if progress_cb and total > 0:
                            progress_cb(downloaded, total)

            actual_sha = hasher.hexdigest().lower()
            if actual_sha != expected_sha:
                new_exe.unlink(missing_ok=True)
                msg = (
                    f"SHA-256 bütünlük doğrulaması başarısız oldu! Dosya silindi.\nBeklenen: {expected_sha}\nHesaplanan: {actual_sha}"
                    if is_tr
                    else f"SHA-256 integrity check failed! File deleted.\nExpected: {expected_sha}\nActual: {actual_sha}"
                )
                return False, "none", msg

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
                f"v{check_res.remote_version} indirildi (SHA-256 doğrulandı); uygulama şimdi yeniden başlatılacak."
                if is_tr
                else f"Downloaded v{check_res.remote_version} (SHA-256 verified); restarting AIconomy now."
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
