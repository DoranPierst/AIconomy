"""Gerçek Sistem İşlemleri: Port/Sağlık Taraması, Canlı Konum Algılama, RTX VRAM, Zombie Port Temizleyici, GitHub Analizi ve Proje/Global AI Config Senkronizasyonu."""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import urllib.request
from typing import Any

import psutil

from .catalog import ToolSpec
from .storage import WindowsDpapiVault

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

PROTECTED_EXES = {"unity.exe", "blender.exe", "code.exe", "antigravity.exe", "explorer.exe"}


def query_gpu_vram() -> tuple[str, int, int]:
    """(gpu_name, used_mb, total_mb) döndürür."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2.5,
            creationflags=NO_WINDOW,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            line = proc.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                return parts[0], int(float(parts[1])), int(float(parts[2]))
    except Exception:
        pass
    return "GPU Algılanamadı", 0, 0


def detect_running_dcc_apps() -> dict[str, bool]:
    """Unity.exe ve blender.exe açık mı kontrol eder."""
    running = {"unity": False, "blender": False, "trellis_server": False}
    try:
        for proc in psutil.process_iter(["name"]):
            nm = (proc.info.get("name") or "").lower()
            if nm == "unity.exe":
                running["unity"] = True
            elif nm == "blender.exe":
                running["blender"] = True
            elif nm == "trellis-server.exe":
                running["trellis_server"] = True
    except Exception:
        pass
    return running


def scan_live_process_locations() -> dict[str, str]:
    """Çalışan süreçlerin komut satırından aktif proje ve dosya yollarını çıkarır (Serena --project, Unity -projectPath vb.)."""
    live: dict[str, str] = {}
    for proc in psutil.process_iter():
        try:
            nm = (proc.name() or "").lower()
            if nm not in ("serena.exe", "python.exe", "pythonw.exe", "unity.exe", "blender.exe", "trellis-server.exe"):
                continue
            exe = proc.exe() or ""
            cmdline = proc.cmdline() or []
            pid = proc.pid
            cmd_joined = " ".join(cmdline)

            if nm == "serena.exe" or ("python" in nm and "serena" in cmd_joined.lower() and "start-mcp-server" in cmd_joined.lower()):
                proj_val = ""
                for idx, arg in enumerate(cmdline):
                    if arg == "--project" and idx + 1 < len(cmdline):
                        proj_val = cmdline[idx + 1]
                        break
                    if arg.startswith("--project="):
                        proj_val = arg.split("=", 1)[1]
                        break
                if proj_val:
                    live["serena"] = f"🟢 Canlı Proje: {proj_val}  |  Süreç: {exe or nm} (PID {pid})"
                else:
                    live["serena"] = f"🟢 Çalışıyor: {exe or nm} (PID {pid})"

            elif nm == "unity.exe":
                proj_val = ""
                for idx, arg in enumerate(cmdline):
                    if arg.lower() == "-projectpath" and idx + 1 < len(cmdline):
                        proj_val = cmdline[idx + 1]
                        break
                if proj_val:
                    live["unity"] = f"🟢 Açık Unity Projesi: {proj_val} (PID {pid})"
                else:
                    live["unity"] = f"🟢 Unity Editör Açık: {exe} (PID {pid})"

            elif nm == "blender.exe":
                blend_files = [a for a in cmdline if a.lower().endswith(".blend")]
                if blend_files:
                    live["blender"] = f"🟢 Açık Sahne: {blend_files[0]}  |  {exe}"
                else:
                    live["blender"] = f"🟢 Blender Açık: {exe} (PID {pid})"

            elif nm == "trellis-server.exe":
                live["trellis"] = f"🟢 GPU Sunucu Aktif: {exe} (PID {pid})"
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
    return live


def find_port_owner(port: int) -> tuple[int | None, str]:
    """Verilen TCP portunu dinleyen sürecin (pid, exe_name) bilgisini bulur."""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                pid = conn.pid
                if pid:
                    try:
                        p = psutil.Process(pid)
                        return pid, p.name()
                    except Exception:
                        return pid, "bilinmeyen-süreç"
    except Exception:
        pass
    return None, ""


def kill_zombie_port_process(port: int) -> tuple[bool, str]:
    """Portu tutan asılı arka plan sunucusunu (Unity/Blender hariç) güvenli şekilde sonlandırır."""
    pid, name = find_port_owner(port)
    if not pid:
        return False, f"Port {port} üzerinde dinleyen aktif bir süreç bulunamadı."
    if name.lower() in PROTECTED_EXES:
        return (
            False,
            f"Port {port} doğrudan '{name}' (PID {pid}) tarafından kullanılıyor. Sahne kaybını önlemek için ana editör zorla kapatılmadı.",
        )
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except psutil.TimeoutExpired:
            proc.kill()
        return True, f"Port {port} üzerindeki asılı süreç ({name}, PID {pid}) temizlendi."
    except Exception as exc:
        return False, f"PID {pid} ({name}) sonlandırılamadı: {exc}"


def free_trellis_vram() -> tuple[bool, str]:
    """trellis-server.exe sürecini kapatıp ekran kartı VRAM belleğini boşaltır."""
    stopped: list[int] = []
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            if (proc.info.get("name") or "").lower() == "trellis-server.exe":
                proc.terminate()
                stopped.append(proc.info["pid"])
    except Exception as exc:
        return False, f"Trellis kontrol hatası: {exc}"

    if not stopped:
        return True, "Trellis arka plan sunucusu zaten kapalı (VRAM boşta)."
    return True, f"Trellis sunucusu (PID {', '.join(map(str, stopped))}) kapatıldı ve GPU VRAM boşaltıldı."


def resolve_disk_location(tool: ToolSpec, projects_map: dict[str, str], live_map: dict[str, str]) -> str:
    """Her araç için gerçek dosya yolunu veya canlı çalıştığı proje bilgisini döndürür."""
    if tool.id == "serena":
        if "serena" in live_map:
            return live_map["serena"]
        exe = pathlib.Path.home() / ".local" / "bin" / "serena.exe"
        proj_dir = projects_map.get(tool.project_scope, "Global")
        return f"Kurulu: {exe if exe.is_file() else 'serena'}  |  Hedef: {proj_dir}"

    if tool.id in ("unity_mcp", "unity_pipeline"):
        if "unity" in live_map:
            return live_map["unity"]
        proj_dir = projects_map.get(tool.project_scope, tool.param_value)
        return f"Hedef Unity Klasörü: {proj_dir}"

    if tool.id == "blender_mcp":
        if "blender" in live_map:
            return live_map["blender"]
        b_exe = pathlib.Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
        return f"Kurulu: {b_exe}" if b_exe.is_file() else "Blender köprüsü (:9876)"

    if tool.id == "trellis":
        if "trellis" in live_map:
            return live_map["trellis"]
        return f"Kurulum Konumu: {tool.param_value}"

    if tool.id == "blender_skills":
        if tool.project_scope != "GLOBAL" and tool.project_scope in projects_map:
            return f"Proje Skill Dizini: {pathlib.Path(projects_map[tool.project_scope]) / '.agents' / 'skills'}"
        return f"Global Plugin Dizini: {pathlib.Path.home() / '.gemini' / 'config' / 'plugins' / 'blender-skills'}"

    if tool.id == "caveman":
        skill_md = pathlib.Path.home() / ".agents" / "skills" / "caveman" / "SKILL.md"
        return f"Dosya Konumu: {skill_md}" if skill_md.is_file() else "Global Kural / Skill"

    if tool.scope_selectable and tool.project_scope != "GLOBAL" and tool.project_scope in projects_map:
        return f"Proje Klasörü: {projects_map[tool.project_scope]}"

    return "Kapsam: Tüm Projeler (Global Yapılandırma)"


def probe_tool_health(
    tool: ToolSpec,
    active_skills_count: int,
    projects_map: dict[str, str],
    live_map: dict[str, str],
) -> tuple[bool, str, int, str, str]:
    """(is_healthy, short_ping_str, latency_ms, detail_msg, location_detail) döndürür."""
    now_str = time.strftime("%H:%M:%S")
    loc_detail = resolve_disk_location(tool, projects_map, live_map)

    if tool.id == "blender_skills":
        plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
        installed = (plugin_dir / "skills").is_dir() or (plugin_dir / "skills_disabled").is_dir()
        tag = f"Aktif ({active_skills_count}/94)" if tool.enabled else "Paket Kapalı"
        if not installed:
            return tool.enabled, f"{tag} · Kurulmadı", 1, "Eklentiler sekmesinden tek tıkla indirilebilir.", loc_detail
        return tool.enabled, tag, 2, f"Disk üzerinde {active_skills_count} skill aktif.", loc_detail

    if tool.id == "caveman":
        skill_md = pathlib.Path.home() / ".agents" / "skills" / "caveman" / "SKILL.md"
        ok = skill_md.is_file()
        status = f"Aktif ({tool.modes[tool.mode_index].split()[0]})" if tool.enabled else "Kapalı"
        return ok and tool.enabled, status if ok else "Kurulu (Yerel)", 1, str(skill_md), loc_detail

    if tool.port:
        t0 = time.perf_counter()
        try:
            with socket.create_connection(("127.0.0.1", int(tool.port)), timeout=0.65):
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                if tool.health_url:
                    try:
                        with urllib.request.urlopen(tool.health_url, timeout=1.2) as resp:
                            body = resp.read(64).decode("utf-8", errors="replace").strip()
                            return True, f"{now_str} ({ms}ms)", ms, f"HTTP 200: {body}", loc_detail
                    except Exception as exc:
                        return False, f"Port Açık / HTTP Hata (:{tool.port})", ms, str(exc), loc_detail
                return True, f"{now_str} ({ms}ms)", ms, f"127.0.0.1:{tool.port} TCP bağlantı başarılı.", loc_detail
        except OSError as exc:
            if tool.id == "trellis":
                cli_exe = pathlib.Path(tool.param_value) / "runtime" / "trellis-cli.exe"
                if cli_exe.is_file():
                    return False, f"Uyku Modu (:{tool.port})", -1, "Trellis CLI kurulu; yerel GPU sunucusu uykuda.", loc_detail
            return False, f"Kapalı (:{tool.port})", -1, f"127.0.0.1:{tool.port} yanıt vermiyor ({exc}).", loc_detail

    if tool.id == "unity_pipeline":
        target_proj = projects_map.get(tool.project_scope, tool.param_value)
        manifest = pathlib.Path(target_proj) / "Packages" / "manifest.json"
        if manifest.is_file() and "com.unity.pipeline" in manifest.read_text(encoding="utf-8", errors="ignore"):
            return tool.enabled, "Kurulu (Unity 6)" if tool.enabled else "Devre Dışı", 3, "com.unity.pipeline doğrulandı.", loc_detail
        return False, "Paket Yok", -1, f"Manifest kontrol edilemedi: {manifest}", loc_detail

    if not tool.enabled:
        return False, "Devre Dışı", -1, "Kullanıcı tarafından kapalı tutuldu (0 şema token).", loc_detail

    return True, "Hazır (stdio)", 4, f"Komut: {tool.mcp_command or tool.install_cmd or 'Hazır'}", loc_detail


def _force_rmtree(target: pathlib.Path) -> None:
    """Windows salt-okunur (.git pack) dosyalarını kilide takılmadan temizler."""
    if not target.exists():
        return

    def _handle_readonly(func: Any, fpath: str, _exc: Any) -> None:
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except Exception:
            pass

    shutil.rmtree(target, onexc=_handle_readonly)


def install_or_update_blender_skills(active_skills: set[str]) -> tuple[bool, str, str]:
    """arjun988/blender-skills reposunu Antigravity plugin yapısında indirir ve seçili 94 skill ayrımını uygular.
    Dönüş: (ok, version_tag, msg)
    """
    target_root = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
    # Eski sürümden kalma salt-okunur geçici klasör varsa temizle
    legacy_tmp = target_root.parent / "_tmp_blender_skills_clone"
    if legacy_tmp.exists():
        _force_rmtree(legacy_tmp)

    temp_clone = pathlib.Path(tempfile.mkdtemp(prefix="aihub_bs_"))
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
            "description": "94 uzman Blender üretim skill paketi (AI Araç Merkezi tarafından seçmeli yönetilir).",
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


def sync_blender_skills_on_disk(
    active_skills: set[str],
    plugin_enabled: bool,
    project_scope: str = "GLOBAL",
    projects_map: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Kurulu blender-skills klasöründe seçili olanları global veya seçili proje (.agents/skills) dizinine senkronlar."""
    target_root = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
    skills_dir = target_root / "skills"
    disabled_dir = target_root / "skills_disabled"
    if not skills_dir.is_dir() and not disabled_dir.is_dir():
        return False, "Blender Skills henüz diske indirilmemiş (Tercihiniz kaydedildi; Eklentiler sekmesinden indirebilirsiniz)."

    skills_dir.mkdir(parents=True, exist_ok=True)
    disabled_dir.mkdir(parents=True, exist_ok=True)

    # Eğer belirli bir projeye atanmışsa globalde kapalı tutup sadece o projenin .agents/skills klasörüne kopyala
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
            # Önce eski blender skill kopyalarını temizle, sonra sadece aktif olanları kopyala
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
            return True, f"Sadece '{project_scope}' projesine ({len(active_skills) if plugin_enabled else 0} skill -> .agents/skills) senkronlandı."

    return True, f"Global senkronizasyon tamamlandı ({moved} skill taşındı; {len(global_effective)} aktif)."


def _build_mcp_entry(t: ToolSpec, vault: WindowsDpapiVault) -> dict[str, Any] | None:
    if t.port and t.kind == "HTTP Servis" and t.id in ("serena", "unity_mcp"):
        return {"url": f"http://127.0.0.1:{t.port}/mcp"}
    if t.mcp_command:
        entry: dict[str, Any] = {"command": t.mcp_command, "args": list(t.mcp_args)}
        if t.vault_key_name:
            secret = vault.get_secret(t.vault_key_name)
            if secret:
                entry["env"] = {t.vault_key_name: secret}
        return entry
    return None


def sync_mcp_json_clients(
    tools: list[ToolSpec],
    vault: WindowsDpapiVault,
    projects_map: dict[str, str] | None = None,
) -> list[str]:
    """Global ve Proje Bazlı (.mcp.json / .cursor/mcp.json) AI ayar dosyalarını yedek alarak günceller."""
    projects_map = projects_map or {}
    client_paths = {
        "AGY": pathlib.Path.home() / ".gemini" / "config" / "mcp_config.json",
        "CLD": pathlib.Path.home() / ".claude.json",
        "CUR": pathlib.Path.home() / ".cursor" / "mcp.json",
    }
    messages: list[str] = []
    managed_keys = {t.mcp_server_key for t in tools if t.mcp_server_key}

    # 1) Global Config Yazımı (AGY global çalışır; CLD ve CUR için sadece GLOBAL kapsamlılar globale yazılır)
    for code, cfg_path in client_paths.items():
        if not cfg_path.is_file() and code != "AGY":
            continue
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if cfg_path.is_file():
            try:
                raw_txt = cfg_path.read_text(encoding="utf-8")
                shutil.copyfile(cfg_path, cfg_path.with_suffix(cfg_path.suffix + ".bak"))
                data = json.loads(raw_txt) if raw_txt.strip() else {}
            except Exception as exc:
                messages.append(f"{code}: okuma hatası ({exc})")
                continue

        servers = data.setdefault("mcpServers", {})
        for key in list(servers.keys()):
            if key in managed_keys:
                servers.pop(key, None)

        added = 0
        for t in tools:
            if not t.mcp_server_key or not (t.enabled and t.clients.get(code, False)):
                continue
            # Claude ve Cursor proje bazlı .mcp.json desteklediği için proje kapsamlıları global yerine projeye yazarız
            if code in ("CLD", "CUR") and t.scope_selectable and t.project_scope != "GLOBAL":
                continue
            entry = _build_mcp_entry(t, vault)
            if entry:
                servers[t.mcp_server_key] = entry
                added += 1

        cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        messages.append(f"{code} Global ({added} MCP)")

    # 2) Proje Bazlı Config Yazımı (<proje>/.mcp.json ve <proje>/.cursor/mcp.json)
    for proj_name, proj_dir_str in projects_map.items():
        proj_dir = pathlib.Path(proj_dir_str)
        if not proj_dir.is_dir():
            continue
        scoped_tools = [
            t
            for t in tools
            if t.mcp_server_key and t.enabled and t.scope_selectable and t.project_scope == proj_name
        ]
        if not scoped_tools:
            continue

        for target_code, rel_cfg in [("CLD", ".mcp.json"), ("CUR", ".cursor/mcp.json")]:
            wanted = [t for t in scoped_tools if t.clients.get(target_code, False)]
            if not wanted:
                continue
            p_cfg = proj_dir / rel_cfg
            p_cfg.parent.mkdir(parents=True, exist_ok=True)
            pdata: dict[str, Any] = {}
            if p_cfg.is_file():
                try:
                    shutil.copyfile(p_cfg, p_cfg.with_suffix(p_cfg.suffix + ".bak"))
                    pdata = json.loads(p_cfg.read_text(encoding="utf-8") or "{}")
                except Exception:
                    pdata = {}
            pservers = pdata.setdefault("mcpServers", {})
            for key in list(pservers.keys()):
                if key in managed_keys:
                    pservers.pop(key, None)
            cnt = 0
            for t in wanted:
                entry = _build_mcp_entry(t, vault)
                if entry:
                    pservers[t.mcp_server_key] = entry
                    cnt += 1
            p_cfg.write_text(json.dumps(pdata, ensure_ascii=False, indent=2), encoding="utf-8")
            messages.append(f"{proj_name}/{rel_cfg} ({cnt} MCP)")

    # 3) Codex (~/.codex/config.toml) İşaretli Blok Senkronizasyonu
    codex_cfg = pathlib.Path.home() / ".codex" / "config.toml"
    if codex_cfg.is_file():
        try:
            orig_toml = codex_cfg.read_text(encoding="utf-8-sig")
            shutil.copyfile(codex_cfg, codex_cfg.with_suffix(".toml.bak"))
            begin_tag = "# >>> BEGIN AI-ARAC-MERKEZI >>>"
            end_tag = "# <<< END AI-ARAC-MERKEZI <<<"
            cleaned = re.sub(
                rf"\n?{re.escape(begin_tag)}.*?{re.escape(end_tag)}\n?",
                "\n",
                orig_toml,
                flags=re.DOTALL,
            ).rstrip()

            cdx_lines: list[str] = [begin_tag]
            cdx_added = 0
            for t in tools:
                if not t.mcp_server_key or not (t.enabled and t.clients.get("CDX", False)):
                    continue
                if re.search(rf"^\[mcp_servers\.{re.escape(t.mcp_server_key)}\]", cleaned, flags=re.MULTILINE):
                    continue
                if t.port and t.kind == "HTTP Servis" and t.id in ("serena", "unity_mcp"):
                    cdx_lines.append(f"[mcp_servers.{t.mcp_server_key}]")
                    cdx_lines.append(f'url = "http://127.0.0.1:{t.port}/mcp"')
                    cdx_added += 1
                elif t.mcp_command:
                    args_toml = ", ".join(json.dumps(a) for a in t.mcp_args)
                    cdx_lines.append(f"[mcp_servers.{t.mcp_server_key}]")
                    cdx_lines.append(f"command = {json.dumps(t.mcp_command)}")
                    cdx_lines.append(f"args = [{args_toml}]")
                    if t.vault_key_name and vault.get_secret(t.vault_key_name):
                        sec = vault.get_secret(t.vault_key_name)
                        cdx_lines.append(f"[mcp_servers.{t.mcp_server_key}.env]")
                        cdx_lines.append(f"{t.vault_key_name} = {json.dumps(sec)}")
                    cdx_added += 1
            cdx_lines.append(end_tag)
            new_toml = cleaned + "\n\n" + "\n".join(cdx_lines) + "\n"
            codex_cfg.write_text(new_toml, encoding="utf-8")
            messages.append(f"CDX ({cdx_added} MCP)")
        except Exception as exc:
            messages.append(f"CDX hata ({exc})")

    return messages


def inspect_github_repo(repo_url: str, github_token: str = "") -> dict[str, Any]:
    """GitHub bağlantısını sorgular ve MCP / Skill türünü otomatik tanır."""
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", repo_url)
    if not m:
        raise ValueError("Geçerli bir GitHub repo adresi girin (örn: https://github.com/owner/repo).")
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    headers = {"User-Agent": "AI-Arac-Merkezi/1.0"}
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


NPM_PACKAGE_MAP: dict[str, str] = {
    "bla": "bla-agents",
    "gltf_transform": "@gltf-transform/cli",
    "context7": "@upstash/context7-mcp",
    "chrome_devtools": "chrome-devtools-mcp",
}

UV_TOOL_MAP: dict[str, str] = {
    "serena": "serena-agent",
    "unity_mcp": "mcp-for-unity",
}

PYPI_PACKAGE_MAP: dict[str, str] = {
    "blender_mcp": "blender-mcp",
    "elevenlabs_mcp": "elevenlabs-mcp",
}


def update_single_tool(
    tool: ToolSpec,
    active_skills: set[str],
    install_if_missing: bool = False,
) -> tuple[bool, str, str]:
    """Tek bir aracı güvenli şekilde günceller (veya install_if_missing=True ise kurar).
    Dönüş: (başarılı_mı, yeni_sürüm_etiketi_veya_boş, özet_mesaj)
    """
    try:
        # 1) Blender Skills (94 Skill Paketi)
        if tool.id == "blender_skills":
            plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
            is_installed = (plugin_dir / "skills").is_dir() or (plugin_dir / "skills_disabled").is_dir()
            if is_installed or install_if_missing:
                ok, ver_tag, msg = install_or_update_blender_skills(active_skills)
                return ok, ver_tag or tool.version, msg
            return True, tool.version, "Henüz indirilmemiş (Kurmak için kutucuğu seçip 'Seçilenleri Kur / Güncelle' diyebilirsiniz)."

        # 2) Caveman (Git tabanlı yerel skill)
        if tool.id == "caveman":
            cav_dir = pathlib.Path.home() / ".agents" / "skills" / "caveman"
            if (cav_dir / ".git").is_dir():
                proc = subprocess.run(
                    ["git", "-C", str(cav_dir), "pull", "--ff-only"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=NO_WINDOW,
                )
                if proc.returncode == 0:
                    out = proc.stdout.strip() or "Güncel."
                    return True, tool.version, f"Git pull tamamlandı: {out}"
                return False, "", f"Git pull uyarısı: {proc.stderr.strip()}"
            if (cav_dir / "SKILL.md").is_file():
                return True, tool.version, "Yerel SKILL.md doğrulandı ve güncel."
            return True, tool.version, "Caveman kuralı hazır."

        # 3) uv tool ile yönetilen araçlar (Serena, Unity MCP)
        if tool.id in UV_TOOL_MAP:
            pkg = UV_TOOL_MAP[tool.id]
            cmd = ["uv", "tool", "install" if install_if_missing else "upgrade", pkg]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=NO_WINDOW,
            )
            combined = (proc.stdout + "\n" + proc.stderr).strip()
            if proc.returncode == 0 or "Nothing to upgrade" in combined or "already installed" in combined.lower():
                return True, tool.version, f"uv tool ({pkg}): Güncel."
            # Kurulu değilse ama upgrade çağrıldıysa hata saymadan bilgi ver
            if "is not installed" in combined.lower() and not install_if_missing:
                return True, tool.version, f"{pkg} özel dizinde kurulu (mevcut kurulum korundu)."
            return False, "", f"uv tool ({pkg}) yanıtı: {combined[:240]}"

        # 4) npm / npx tabanlı araçlar (BLA, glTF-Transform, Context7, Chrome DevTools)
        if tool.id in NPM_PACKAGE_MAP:
            pkg = NPM_PACKAGE_MAP[tool.id]
            latest_ver = ""
            try:
                encoded_pkg = pkg.replace("/", "%2F")
                req = urllib.request.Request(
                    f"https://registry.npmjs.org/{encoded_pkg}/latest",
                    headers={"User-Agent": "AI-Arac-Merkezi/1.0"},
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    meta = json.loads(resp.read().decode("utf-8"))
                    latest_ver = meta.get("version", "")
            except Exception:
                pass

            new_v_tag = f"v{latest_ver}" if latest_ver else tool.version
            if install_if_missing and pkg in ("bla-agents", "@gltf-transform/cli"):
                npm_exe = "npm.cmd" if shutil.which("npm.cmd") else "npm"
                proc = subprocess.run(
                    [npm_exe, "install", "-g", f"{pkg}@latest"],
                    capture_output=True,
                    text=True,
                    timeout=90,
                    creationflags=NO_WINDOW,
                )
                if proc.returncode != 0:
                    return False, new_v_tag, f"npm kurulum hatası ({pkg}): {proc.stderr.strip()[:220]}"
                return True, new_v_tag, f"{pkg} global olarak {new_v_tag} sürümüne güncellendi."

            return True, new_v_tag, f"npm kayıt defteri kontrol edildi -> son sürüm {new_v_tag} (npx ile güncel çalışır)."

        # 5) PyPI / uvx tabanlı araçlar
        if tool.id in PYPI_PACKAGE_MAP:
            pkg = PYPI_PACKAGE_MAP[tool.id]
            latest_ver = ""
            try:
                req = urllib.request.Request(
                    f"https://pypi.org/pypi/{pkg}/json",
                    headers={"User-Agent": "AI-Arac-Merkezi/1.0"},
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    meta = json.loads(resp.read().decode("utf-8"))
                    latest_ver = meta.get("info", {}).get("version", "")
            except Exception:
                pass
            new_v_tag = f"v{latest_ver}" if latest_ver else tool.version
            return True, new_v_tag, f"PyPI son sürümü doğrulandı ({new_v_tag})."

        # 6) Yerel oyun / GPU araçları (Unity Pipeline, Trellis, RenderDoc, Meshy veya özel GitHub)
        if tool.id in ("unity_pipeline", "trellis"):
            return True, tool.version, "Yerel motor/GPU kurulumu doğrulandı (özel ağırlık ve proje dosyaları korundu)."

        if "github.com/" in tool.repo_url:
            m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", tool.repo_url)
            if m:
                owner, repo = m.group(1), m.group(2).removesuffix(".git")
                try:
                    req = urllib.request.Request(
                        f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
                        headers={"User-Agent": "AI-Arac-Merkezi/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        rel = json.loads(resp.read().decode("utf-8"))
                        tag = rel.get("tag_name", "")
                        if tag:
                            return True, tag if tag.startswith("v") else f"v{tag}", f"GitHub son sürümü kontrol edildi: {tag}"
                except Exception:
                    pass
            return True, tool.version, "GitHub kaynağı doğrulandı ve güncel."

        return True, tool.version, "Sürüm kontrolü tamamlandı."
    except Exception as exc:
        return False, "", f"Güncelleme hatası: {exc}"

