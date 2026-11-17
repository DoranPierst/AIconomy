"""GitHub Üzerinden Program Sürüm Kontrolü ve Tek Tıkla Otomatik Kendi Kendini Güncelleme (Self-Updater)."""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import subprocess
import sys
import traceback
import urllib.request
from typing import Callable

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

FALLBACK_VERSION = "1.1.0"
DEFAULT_APP_REPO = ""  # GitHub'a bağlandığında origin URL otomatik okunur veya kullanıcı ayarlardan kaydeder


def get_source_root() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent.parent


def get_current_app_version() -> str:
    candidates = [
        get_source_root() / "version.json",
        pathlib.Path(getattr(sys, "_MEIPASS", "")) / "version.json" if getattr(sys, "frozen", False) else None,
    ]
    for c in candidates:
        if c and c.is_file():
            try:
                v = str(json.loads(c.read_text(encoding="utf-8")).get("version", "")).strip()
                if v:
                    return v.lstrip("v")
            except Exception:
                pass
    return FALLBACK_VERSION


def detect_git_origin_url() -> str:
    for candidate_dir in (get_source_root(), get_source_root().parent):
        if (candidate_dir / ".git").is_dir():
            try:
                proc = subprocess.run(
                    ["git", "-C", str(candidate_dir), "remote", "get-url", "origin"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=NO_WINDOW,
                )
                if proc.returncode == 0 and "github.com" in proc.stdout:
                    url = proc.stdout.strip().removesuffix(".git")
                    return url
            except Exception:
                pass
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


def parse_github_owner_repo(repo_input: str) -> tuple[str, str]:
    s = repo_input.strip().removesuffix(".git").strip("/")
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", s)
    if m:
        return m.group(1), m.group(2)
    if "/" in s and " " not in s and not s.startswith("http"):
        parts = s.split("/")
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
    raise ValueError("Geçerli bir GitHub repo adresi girin (örn: https://github.com/kullanici/ai-arac-merkezi).")


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


def check_for_app_updates(repo_input: str, github_token: str = "") -> UpdateCheckResult:
    local_ver = get_current_app_version()
    if not repo_input.strip():
        detected = detect_git_origin_url()
        if not detected:
            return UpdateCheckResult(
                ok=False,
                has_update=False,
                local_version=local_ver,
                remote_version=local_ver,
                changelog="",
                release_notes_url="",
                exe_download_url="",
                repo_url="",
                can_git_pull=False,
                message="Henüz bir GitHub güncelleme reposu tanımlanmadı.",
            )
        repo_input = detected

    try:
        owner, repo = parse_github_owner_repo(repo_input)
    except ValueError as exc:
        return UpdateCheckResult(False, False, local_ver, local_ver, "", "", "", repo_input, False, str(exc))

    clean_repo_url = f"https://github.com/{owner}/{repo}"
    headers = {"User-Agent": "AI-Arac-Merkezi-Updater/1.1"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    remote_ver = ""
    changelog = ""
    notes_url = f"{clean_repo_url}/releases"
    exe_url = ""

    # 1) GitHub Releases (Hazır .exe ve sürüm notu linki var mı?)
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{owner}/{repo}/releases/latest", headers=headers)
        with urllib.request.urlopen(req, timeout=7) as resp:
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
    except Exception:
        pass

    # 2) main dalındaki version.json
    for branch in ("main", "master"):
        try:
            v_req = urllib.request.Request(
                f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/version.json",
                headers=headers,
            )
            with urllib.request.urlopen(v_req, timeout=6) as resp:
                v_data = json.loads(resp.read().decode("utf-8"))
                v_str = str(v_data.get("version", "")).lstrip("vV").strip()
                if v_str and (not remote_ver or parse_semver(v_str) > parse_semver(remote_ver)):
                    remote_ver = v_str
                    changelog = str(v_data.get("changelog", changelog)).strip()
                    if notes_url == f"{clean_repo_url}/releases":
                        notes_url = f"{clean_repo_url}/commits/{branch}"
                break
        except Exception:
            continue

    if not remote_ver:
        return UpdateCheckResult(
            ok=False,
            has_update=False,
            local_version=local_ver,
            remote_version=local_ver,
            changelog="",
            release_notes_url="",
            exe_download_url="",
            repo_url=clean_repo_url,
            can_git_pull=False,
            message=f"{clean_repo_url} üzerinde henüz yayınlanmış bir sürüm bulunamadı.",
        )

    has_upd = parse_semver(remote_ver) > parse_semver(local_ver)
    src_root = get_source_root()
    git_dir_exists = (src_root / ".git").is_dir() or (src_root.parent / ".git").is_dir()

    if has_upd:
        msg = f"Güncelleme Mevcut: {local_ver}v > {remote_ver}v"
    else:
        msg = f"Program güncel ({local_ver}v)"

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
) -> tuple[bool, str, str]:
    """Güncellemeyi indirir/çeker ve yeniden başlatma kipini döndürür:
    Dönüş: (ok, action_kind ['swap_exe' | 'restart_py' | 'none'], message)
    """
    is_frozen = getattr(sys, "frozen", False)

    # Durum A: .exe modunda çalışıyor ve GitHub Release üzerinde hazır .exe var -> Atomik Sıcak Değişim (Hot-Swap)
    if is_frozen and check_res.exe_download_url:
        current_exe = pathlib.Path(sys.executable).resolve()
        new_exe = current_exe.with_suffix(".exe.new")
        headers = {"User-Agent": "AI-Arac-Merkezi-Updater/1.1"}
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

            # Bozuk indirmeye karşı PE (MZ) başlık ve boyut doğrulaması
            if not new_exe.is_file() or new_exe.stat().st_size < 1_000_000:
                new_exe.unlink(missing_ok=True)
                return False, "none", "İndirilen güncelleme dosyası eksik görünüyor; mevcut sürüm korundu."
            with open(new_exe, "rb") as chk:
                if chk.read(2) != b"MZ":
                    new_exe.unlink(missing_ok=True)
                    return False, "none", "İndirilen dosya geçerli bir Windows .exe dosyası değil; mevcut sürüm korundu."

            bat_path = current_exe.parent / "_apply_update.bat"
            bat_content = (
                "@echo off\r\n"
                "chcp 65001 >nul\r\n"
                "timeout /t 2 /nobreak >nul\r\n"
                f'move /y "{new_exe}" "{current_exe}" >nul\r\n'
                f'start "" "{current_exe}"\r\n'
                'del "%~f0"\r\n'
            )
            bat_path.write_text(bat_content, encoding="utf-8")
            subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=NO_WINDOW)
            return True, "swap_exe", f"v{check_res.remote_version} indirildi! Program şimdi otomatik yenilenip açılacak."
        except Exception as exc:
            new_exe.unlink(missing_ok=True)
            return False, "none", f".exe indirme hatası: {exc}\n\n{traceback.format_exc()}"

    # Durum B: Kaynak koddan (veya üst klasöründe .git olan dizinden) çalışıyor -> git pull --ff-only
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
                raw = f"Komut: {' '.join(cmd)}\nÇıkış Kodu: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                return False, "none", f"git pull başarısız: {proc.stderr.strip() or proc.stdout.strip()}\n\n{raw}"
            if not is_frozen:
                return True, "restart_py", f"Kaynak kodlar v{check_res.remote_version} sürümüne çekildi! Yeniden başlatılıyor..."
            return (
                True,
                "none",
                f"Kaynak kodlar çekildi ({proc.stdout.strip()}). .exe olarak kullandığınız için build_exe.bat çalıştırabilir veya GitHub Release .exe yayınlandığında doğrudan tek tıkla güncelleyebilirsiniz.",
            )
        except Exception as exc:
            return False, "none", f"Git güncelleme hatası: {exc}\n\n{traceback.format_exc()}"

    return (
        False,
        "none",
        "Bu sürüm için GitHub Releases altında henüz derlenmiş bir 'AI-Arac-Merkezi.exe' dosyası eklenmemiş.",
    )


def restart_running_python_app() -> None:
    os.execl(sys.executable, sys.executable, *sys.argv)
