"""Expanded Auto-Heal engine: classifies log errors/warnings and heals runtime, skill, config, and host issues."""
from __future__ import annotations

import dataclasses
import pathlib
import re
import time
from typing import Any

from .catalog import ToolSpec
from .host_apps import launch_host_app_for_tool
from .mcp_config import (
    sync_blender_skills_on_disk,
    sync_caveman_on_disk,
    sync_custom_skill_tools_on_disk,
    sync_mcp_json_clients,
)
from .oauth import supports_oauth
from .plugins import can_uninstall_tool_from_disk, install_library_tool, update_single_tool
from .processes import (
    enforce_tool_runtime_state,
    free_trellis_vram,
    kill_zombie_port_process,
    wait_for_started_ports,
)
from .storage import WindowsDpapiVault


@dataclasses.dataclass(frozen=True)
class HealPlan:
    """Actionable Auto-Heal remediation plan linked to a tool or log entry."""

    action_id: str
    tool_id: str
    tool_name: str
    label: str
    detail: str
    port: int = 0
    vault_key_name: str = ""
    host_kind: str = ""
    safe_auto: bool = False
    is_ui_action: bool = False


_KNOWN_PORT_TOOL_MAP: dict[int, str] = {
    9121: "serena",
    8080: "unity_mcp",
    9876: "blender_mcp",
    8790: "trellis",
}


def _match_tool_for_log(entry: dict[str, Any], tools: list[ToolSpec]) -> ToolSpec | None:
    tool_lbl = str(entry.get("tool") or "").strip().lower()
    raw_port = entry.get("port")
    port_num = int(raw_port) if isinstance(raw_port, int) and raw_port > 0 else 0

    if tool_lbl:
        for t in tools:
            if t.name.lower() == tool_lbl or t.id.lower() == tool_lbl:
                return t
        for t in tools:
            if t.name.lower() in tool_lbl or (len(tool_lbl) >= 4 and tool_lbl in t.name.lower()):
                return t
    if port_num:
        for t in tools:
            if t.port and int(t.port) == port_num:
                return t
        mapped_id = _KNOWN_PORT_TOOL_MAP.get(port_num)
        if mapped_id:
            return next((t for t in tools if t.id == mapped_id), None)

    blob = f"{entry.get('summary', '')} {entry.get('raw_detail', '')}".lower()
    for t in tools:
        if t.id in ("caveman", "blender_skills", "blender_mcp", "unity_mcp", "serena", "trellis"):
            if t.name.lower() in blob or t.id.replace("_", " ") in blob or t.id in blob:
                return t
    return None


def _extract_port_from_text(entry: dict[str, Any], tool: ToolSpec | None) -> int:
    raw_port = entry.get("port")
    if isinstance(raw_port, int) and raw_port > 0:
        return raw_port
    if tool is not None and tool.port:
        return int(tool.port)
    blob = f"{entry.get('tool', '')} {entry.get('summary', '')} {entry.get('raw_detail', '')}"
    m = re.search(r":(8080|9121|9876|8790)\b", blob)
    if m:
        return int(m.group(1))
    m2 = re.search(r"port\s*:?\s*(\d{4,5})", blob, re.IGNORECASE)
    if m2:
        return int(m2.group(1))
    return 0


def classify_log_for_auto_heal(
    entry: dict[str, Any],
    tools: list[ToolSpec],
    vault: WindowsDpapiVault | None = None,
    lang: str = "en",
) -> HealPlan | None:
    """Inspect a log row and return a HealPlan if Auto-Heal can resolve it, else None."""
    lvl = str(entry.get("level") or "").upper()
    if lvl not in ("ERR", "WARN"):
        return None

    is_tr = lang == "tr"
    summary = str(entry.get("summary") or "")
    raw = str(entry.get("raw_detail") or "")
    tool_col = str(entry.get("tool") or "")
    blob = f"{tool_col}\n{summary}\n{raw}".lower()

    tool = _match_tool_for_log(entry, tools)
    t_id = tool.id if tool else ""
    t_name = tool.name if tool else (tool_col or "AIconomy")
    port = _extract_port_from_text(entry, tool)

    # 1. Vault Master Passphrase locked
    if (
        "kasa kilitli" in blob
        or "vault is locked" in blob
        or "vault locked" in blob
        or "exit code 3" in blob
        or "çıkış kodu 3" in blob
        or (vault is not None and vault.is_locked() and ("passphrase" in blob or "parola" in blob))
    ):
        return HealPlan(
            action_id="unlock_vault_pin",
            tool_id=t_id,
            tool_name=t_name,
            label="Kasa Kilidini Aç" if is_tr else "Unlock Vault",
            detail=(
                "Kasa kilidini açmak için Ayarlar > API Anahtarları penceresini açar."
                if is_tr
                else "Opens Settings > API Keys to unlock the DPAPI vault."
            ),
            is_ui_action=True,
        )

    # 2. Missing required API key (or OAuth setup)
    key_match = re.search(r"\b([A-Z][A-Z0-9_]{2,}_(?:API_KEY|KEY|TOKEN|SECRET))\b", f"{summary} {raw}")
    missing_key_hint = (
        "anahtar eksik" in blob
        or "api anahtarı eksik" in blob
        or "missing key" in blob
        or "api key missing" in blob
        or ("missing " in blob and key_match is not None)
    )
    if missing_key_hint:
        key_name = (tool.vault_key_name if tool and tool.vault_key_name else "") or (
            key_match.group(1) if key_match else ""
        )
        can_oauth = bool(tool and supports_oauth(tool.id))
        return HealPlan(
            action_id="configure_vault_key",
            tool_id=t_id,
            tool_name=t_name,
            label=(
                ("OAuth / Anahtar Ayarla" if can_oauth else "API Anahtarı Gir")
                if is_tr
                else ("Setup OAuth / Key" if can_oauth else "Configure API Key")
            ),
            detail=(
                f"{t_name} için eksik kimlik bilgisini ({key_name or 'OAuth'}) yapılandırır."
                if is_tr
                else f"Opens credential setup ({key_name or 'OAuth'}) for {t_name}."
            ),
            vault_key_name=key_name,
            is_ui_action=True,
        )

    # 3. Skill / Rule / Antigravity mirror missing or out of sync
    is_skill_tool = bool(
        tool
        and (
            tool.id in ("caveman", "blender_skills")
            or (
                not tool.mcp_server_key
                and (tool.kind in ("skill_pack", "rule") or (tool.install_cmd or "").strip().startswith("git clone "))
            )
        )
    )
    skill_err_hint = (
        "agy skill" in blob
        or "skill.md eksik" in blob
        or "skill.md missing" in blob
        or "kurulu değil" in blob
        or "not installed" in blob
        or "senkronu eksik" in blob
        or "mirror missing" in blob
    )
    if is_skill_tool and (skill_err_hint or "skill" in blob or "caveman" in blob):
        return HealPlan(
            action_id="sync_skills_mirror",
            tool_id=t_id,
            tool_name=t_name,
            label="Skill Kur ve Senkronla" if is_tr else "Install & Sync Skills",
            detail=(
                f"{t_name} dosyalarını kurar ve Antigravity (~/.gemini/config/skills) ile eşitler."
                if is_tr
                else f"Installs {t_name} if missing and syncs disk + Antigravity skill mirrors."
            ),
            safe_auto=True,
        )

    # 4. Zombie / stuck port process
    zombie_hint = (
        "zombie" in blob
        or "asılı" in blob
        or "stuck" in blob
        or "eaddrinuse" in blob
        or "address already in use" in blob
        or "kapalı ama port" in blob
        or "still open" in blob
    )
    if zombie_hint and port > 0:
        return HealPlan(
            action_id="clean_zombie_port",
            tool_id=t_id,
            tool_name=t_name,
            label=f"Port :{port} Temizle" if is_tr else f"Clean Port :{port}",
            detail=(
                f"Port :{port} üzerindeki asılı arka plan sürecini temizler (açık editörler korunur)."
                if is_tr
                else f"Releases stuck background process on port :{port} (protects visible editors)."
            ),
            port=port,
            safe_auto=(port == 9876 and "zombie" in blob),
        )

    # 5. Local HTTP MCP server offline / HTTP error (Serena, Unity MCP)
    http_err_hint = (
        "çevrimdışı" in blob
        or "offline" in blob
        or "yanıt vermiyor" in blob
        or "no response" in blob
        or "http hatası" in blob
        or "http err" in blob
        or "connection refused" in blob
        or "bağlantı reddedildi" in blob
        or "sunucu yanıt" in blob
    )
    if (t_id in ("serena", "unity_mcp") or port in (9121, 8080)) and http_err_hint:
        target_id = t_id or _KNOWN_PORT_TOOL_MAP.get(port, "")
        target_port = port or (9121 if target_id == "serena" else 8080)
        return HealPlan(
            action_id="restart_http_server",
            tool_id=target_id,
            tool_name=t_name,
            label="Sunucuyu Yeniden Başlat" if is_tr else "Restart Server",
            detail=(
                f"{t_name} yerel HTTP sunucusunu (:{target_port}) yeniden başlatıp configleri yeniler."
                if is_tr
                else f"Restarts local HTTP server for {t_name} (:{target_port}) and resyncs configs."
            ),
            port=target_port,
            safe_auto=True,
        )

    # 6. Host app closed / Blender socket missing
    if t_id == "blender_mcp" or ("blender" in blob and ("kapalı" in blob or "closed" in blob or "soket" in blob or "socket" in blob or "9876" in blob)):
        return HealPlan(
            action_id="launch_host_app",
            tool_id="blender_mcp",
            tool_name="Blender MCP",
            label="Blender'ı Başlat" if is_tr else "Launch Blender",
            detail=(
                "Blender uygulamasını başlatır ve :9876 MCP soketini yeniden tarar."
                if is_tr
                else "Launches Blender and re-scans the :9876 MCP socket."
            ),
            port=9876,
            host_kind="blender",
        )

    # 7. TRELLIS / GPU VRAM OOM
    if t_id == "trellis" or port == 8790 or "cuda out of memory" in blob or ("vram" in blob and ("dolu" in blob or "oom" in blob or "error" in blob or "hata" in blob)):
        return HealPlan(
            action_id="free_gpu_vram",
            tool_id="trellis",
            tool_name="TRELLIS",
            label="GPU VRAM Boşalt" if is_tr else "Free GPU VRAM",
            detail=(
                "Arka plandaki TRELLIS GPU sunucusunu durdurup VRAM belleğini boşaltır."
                if is_tr
                else "Stops background TRELLIS GPU server to release VRAM."
            ),
            port=8790,
        )

    # 8. AI client config write/read/sync error
    cfg_hint = (
        "mcp_config.json" in blob
        or "config.toml" in blob
        or ".claude.json" in blob
        or ".cursor/mcp.json" in blob
        or "cdx hatası" in blob
        or "cdx error" in blob
        or "yazma hatası" in blob
        or "write error" in blob
        or "config senkron" in blob
        or "config sync" in blob
    )
    if cfg_hint:
        return HealPlan(
            action_id="resync_client_configs",
            tool_id=t_id,
            tool_name=t_name,
            label="Configleri Yeniden Yaz" if is_tr else "Resync Configs",
            detail=(
                "Tüm AI istemci config dosyalarını ve skill aynalarını güvenli biçimde yeniden yazar."
                if is_tr
                else "Atomically resyncs all AI client config files and skill mirrors."
            ),
            safe_auto=True,
        )

    # 9. Missing binary / broken npm or uv package / install failure
    install_err_hint = (
        "kurulum hatası" in blob
        or "installation error" in blob
        or "kurulu değil" in blob
        or "not installed" in blob
        or "komut bulunamadı" in blob
        or "command not found" in blob
        or "cannot find module" in blob
        or "exit code" in blob
        or "çıkış kodu" in blob
        or "güncelleme hatası" in blob
        or "update failed" in blob
    )
    if tool is not None and install_err_hint and can_uninstall_tool_from_disk(tool):
        return HealPlan(
            action_id="install_missing_tool",
            tool_id=tool.id,
            tool_name=tool.name,
            label="Aracı Onar / Yeniden Kur" if is_tr else "Repair / Reinstall Tool",
            detail=(
                f"{tool.name} paketini yeniden indirip kurar ve istemci configlerini günceller."
                if is_tr
                else f"Re-downloads and reinstalls {tool.name}, then resyncs client configs."
            ),
        )

    # 10. Plugin update check failure
    if "güncelleme kontrol" in blob or "update check" in blob:
        return HealPlan(
            action_id="refresh_plugin_updates",
            tool_id=t_id,
            tool_name=t_name,
            label="Kontrolü Tekrarla" if is_tr else "Retry Update Check",
            detail=(
                "Eklenti sürüm kontrolünü yeniden çalıştırır."
                if is_tr
                else "Retries the plugin update check."
            ),
            is_ui_action=True,
        )

    return None


def detect_background_heal_plans(
    tools: list[ToolSpec],
    live_map: dict[str, str],
    health_results: list[tuple[str, bool, str, str, int, str, str]],
    runtime_running: bool,
    lang: str = "en",
) -> list[HealPlan]:
    """Identify safe issues that can be repaired automatically in the background."""
    is_tr = lang == "tr"
    by_id = {t.id: t for t in tools}
    plans: list[HealPlan] = []
    seen_keys: set[str] = set()

    def _add(p: HealPlan) -> None:
        k = f"{p.action_id}:{p.tool_id}:{p.port}"
        if k not in seen_keys:
            seen_keys.add(k)
            plans.append(p)

    home = pathlib.Path.home()

    for tid, ok, h_state, _ping_str, _ms, _detail, _loc in health_results:
        t = by_id.get(tid)
        if t is None or not getattr(t, "in_workspace", True) or not t.enabled:
            continue

        # A. Local HTTP MCP server offline while runtime is running
        if tid in ("serena", "unity_mcp") and t.port and not ok and runtime_running:
            _add(
                HealPlan(
                    action_id="restart_http_server",
                    tool_id=t.id,
                    tool_name=t.name,
                    label="Sunucuyu Yeniden Başlat" if is_tr else "Restart Server",
                    detail=f"Auto-heal HTTP server {t.name} (:{int(t.port)})",
                    port=int(t.port),
                    safe_auto=True,
                )
            )

        # B. Windowless zombie blender.exe holding port 9876 (never touches visible GUI Blender)
        if tid == "blender_mcp" and live_map.get("blender_zombie_pid") and live_map.get("blender_open") != "1":
            b_port = int(t.port or 9876)
            _add(
                HealPlan(
                    action_id="clean_zombie_port",
                    tool_id=t.id,
                    tool_name=t.name,
                    label=f"Port :{b_port} Temizle" if is_tr else f"Clean Port :{b_port}",
                    detail="Clean windowless stuck blender.exe zombie process",
                    port=b_port,
                    safe_auto=True,
                )
            )

        # C. Caveman or Antigravity skill mirror drift while enabled
        if tid == "caveman":
            active_md = home / ".agents" / "skills" / "caveman" / "SKILL.md"
            disabled_md = home / ".agents" / "skills_disabled" / "caveman" / "SKILL.md"
            agy_md = home / ".gemini" / "config" / "skills" / "caveman" / "SKILL.md"
            needs_mirror = bool(t.clients.get("AGY", True) and not agy_md.is_file())
            if (not active_md.is_file() and disabled_md.is_file()) or (active_md.is_file() and needs_mirror):
                _add(
                    HealPlan(
                        action_id="sync_skills_mirror",
                        tool_id=t.id,
                        tool_name=t.name,
                        label="Skill Senkronla" if is_tr else "Sync Skills",
                        detail="Reconcile Caveman skill and Antigravity mirror",
                        safe_auto=True,
                    )
                )

        # D. Custom Git skill pack / rule drift while enabled
        elif (
            tid != "blender_skills"
            and not t.mcp_server_key
            and (t.kind in ("skill_pack", "rule") or (t.install_cmd or "").strip().startswith("git clone "))
        ):
            act_dir = home / ".agents" / "skills" / t.id
            dis_dir = home / ".agents" / "skills_disabled" / t.id
            agy_root = home / ".gemini" / "config" / "skills"
            has_agy_mirror = (agy_root / t.id).is_dir() or (
                agy_root.is_dir() and any(c.name.startswith(f"{t.id}__") for c in agy_root.iterdir() if c.is_dir())
            )
            if (not act_dir.is_dir() and dis_dir.is_dir()) or (act_dir.is_dir() and t.clients.get("AGY", False) and not has_agy_mirror):
                _add(
                    HealPlan(
                        action_id="sync_skills_mirror",
                        tool_id=t.id,
                        tool_name=t.name,
                        label="Skill Senkronla" if is_tr else "Sync Skills",
                        detail=f"Reconcile {t.name} skill and Antigravity mirror",
                        safe_auto=True,
                    )
                )

    return plans


def execute_background_heal_plan(
    plan: HealPlan,
    tools: list[ToolSpec],
    active_skills: set[str],
    projects_map: dict[str, str],
    vault: WindowsDpapiVault,
    lang: str = "en",
) -> tuple[bool, str, str]:
    """Execute a non-UI HealPlan on a worker thread. Returns (ok, short_summary, raw_detail)."""
    is_tr = lang == "tr"
    by_id = {t.id: t for t in tools}
    tool = by_id.get(plan.tool_id) if plan.tool_id else None

    try:
        if plan.action_id == "restart_http_server":
            if tool is None:
                return False, ("Hedef araç bulunamadı." if is_tr else "Target tool not found."), plan.tool_id
            note = enforce_tool_runtime_state(
                tool,
                projects_map,
                allow_stop=False,
                allow_start=True,
                restart_if_running=True,
                lang=lang,
            )
            if tool.port:
                wait_for_started_ports([int(tool.port)], timeout=3.0)
            cfg_msgs = sync_mcp_json_clients(tools, vault, projects_map, lang=lang)
            if note:
                msg = f"{tool.name}: {note.strip()}"
                return True, msg, "\n".join([msg, *cfg_msgs])
            msg = (
                f"{tool.name} zaten çalışıyor veya ikili dosya bulunamadı."
                if is_tr
                else f"{tool.name} is already running or its executable was not found."
            )
            return False, msg, "\n".join([msg, *cfg_msgs])

        if plan.action_id == "clean_zombie_port":
            if plan.port <= 0:
                return False, ("Geçersiz port." if is_tr else "Invalid port."), ""
            ok, msg = kill_zombie_port_process(plan.port, lang=lang)
            extra = ""
            if ok and tool is not None and tool.enabled and tool.id in ("serena", "unity_mcp"):
                time.sleep(0.4)
                extra = enforce_tool_runtime_state(tool, projects_map, allow_stop=False, allow_start=True, lang=lang)
            full_msg = f"{msg}{extra}"
            return ok, full_msg, full_msg

        if plan.action_id == "sync_skills_mirror":
            if tool is None:
                return False, ("Skill aracı bulunamadı." if is_tr else "Skill tool not found."), plan.tool_id
            raw_parts: list[str] = []
            if tool.id == "caveman":
                home = pathlib.Path.home()
                has_disk = (home / ".agents" / "skills" / "caveman" / "SKILL.md").is_file() or (
                    home / ".agents" / "skills_disabled" / "caveman" / "SKILL.md"
                ).is_file()
                if not has_disk:
                    ok_i, _ver, i_msg, i_raw = update_single_tool(tool, active_skills, install_if_missing=True, lang=lang)
                    raw_parts.append(i_raw or i_msg)
                    if not ok_i:
                        return False, i_msg, "\n".join(raw_parts)
                ok_s, s_msg = sync_caveman_on_disk(tool, lang=lang)
                raw_parts.append(s_msg)
                return ok_s, s_msg, "\n".join(raw_parts)

            if tool.id == "blender_skills":
                plugin_dir = pathlib.Path.home() / ".gemini" / "config" / "plugins" / "blender-skills"
                if not (plugin_dir / "skills").is_dir() and not (plugin_dir / "skills_disabled").is_dir():
                    ok_i, _ver, i_msg, i_raw = update_single_tool(tool, active_skills, install_if_missing=True, lang=lang)
                    raw_parts.append(i_raw or i_msg)
                    if not ok_i:
                        return False, i_msg, "\n".join(raw_parts)
                ok_s, s_msg = sync_blender_skills_on_disk(
                    active_skills,
                    bool(getattr(tool, "in_workspace", True) and tool.enabled),
                    tool.project_scope,
                    projects_map,
                    lang=lang,
                )
                raw_parts.append(s_msg)
                return ok_s, s_msg, "\n".join(raw_parts)

            # Custom Git skill pack / rule
            home = pathlib.Path.home()
            has_custom = (home / ".agents" / "skills" / tool.id).is_dir() or (
                home / ".agents" / "skills_disabled" / tool.id
            ).is_dir()
            if not has_custom and (tool.install_cmd or "").strip().startswith("git clone "):
                ok_i, _ver, i_msg, i_raw = install_library_tool(tool, active_skills, lang=lang)
                raw_parts.append(i_raw or i_msg)
                if not ok_i:
                    return False, i_msg, "\n".join(raw_parts)
            s_msgs = sync_custom_skill_tools_on_disk([tool], lang=lang)
            summary = " | ".join(s_msgs) if s_msgs else (
                f"{tool.name} skill senkronizasyonu tamamlandı." if is_tr else f"Synced {tool.name} skill mirror."
            )
            raw_parts.append(summary)
            return True, summary, "\n".join(raw_parts)

        if plan.action_id == "resync_client_configs":
            raw_parts = []
            bs_tool = by_id.get("blender_skills")
            if bs_tool:
                _ok, b_msg = sync_blender_skills_on_disk(
                    active_skills,
                    bool(getattr(bs_tool, "in_workspace", True) and bs_tool.enabled),
                    bs_tool.project_scope,
                    projects_map,
                    lang=lang,
                )
                raw_parts.append(b_msg)
            cv_tool = by_id.get("caveman")
            if cv_tool:
                _ok, c_msg = sync_caveman_on_disk(cv_tool, lang=lang)
                raw_parts.append(c_msg)
            raw_parts.extend(sync_custom_skill_tools_on_disk(tools, lang=lang))
            cfg_msgs = sync_mcp_json_clients(tools, vault, projects_map, lang=lang)
            raw_parts.extend(cfg_msgs)
            summary = " | ".join(cfg_msgs) if cfg_msgs else (
                "İstemci config dosyaları yenilendi." if is_tr else "AI client configs resynced."
            )
            return True, summary, "\n".join(raw_parts)

        if plan.action_id == "install_missing_tool":
            if tool is None:
                return False, ("Kurulacak araç bulunamadı." if is_tr else "Tool to install not found."), plan.tool_id
            ok_i, _ver, i_msg, i_raw = install_library_tool(tool, active_skills, lang=lang)
            if ok_i:
                sync_mcp_json_clients(tools, vault, projects_map, lang=lang)
                sync_custom_skill_tools_on_disk([tool], lang=lang)
            return ok_i, i_msg, i_raw or i_msg

        if plan.action_id == "launch_host_app":
            tr_tool = by_id.get("trellis")
            ok_h, h_msg = launch_host_app_for_tool(
                host_kind=plan.host_kind or "blender",
                projects_map=projects_map,
                target_scope=tool.project_scope if tool else "GLOBAL",
                headless=False,
                trellis_root=tr_tool.param_value if tr_tool else "",
                lang=lang,
            )
            return ok_h, h_msg, h_msg

        if plan.action_id == "free_gpu_vram":
            ok_v, v_msg = free_trellis_vram(lang=lang)
            return ok_v, v_msg, v_msg

        return False, ("Desteklenmeyen onarım eylemi." if is_tr else "Unsupported heal action."), plan.action_id
    except Exception as exc:
        msg = f"Oto-Onarım hatası: {exc}" if is_tr else f"Auto-Heal error: {exc}"
        return False, msg, repr(exc)
