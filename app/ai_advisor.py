"""Two-way AI Advisor: prompt generator and structured response parser (emoji-free, EN & TR)."""
from __future__ import annotations

import platform
import re

from .catalog import BLENDER_SKILLS_94, ToolSpec, localized_option_text, localized_tool_modes, localized_tool_text, tool_kind_label


def build_skills_ai_prompt(
    active_skills: set[str],
    checked_skills: set[str],
    lang: str = "en",
) -> str:
    open_list = [s for s in BLENDER_SKILLS_94 if s in active_skills]
    closed_list = [s for s in BLENDER_SKILLS_94 if s not in active_skills]
    checked_list = [s for s in BLENDER_SKILLS_94 if s in checked_skills]

    if lang == "tr":
        lines = [
            "[AIconomy — Blender Skills Danışma Özeti]",
            f"- Toplam Skill: {len(BLENDER_SKILLS_94)} | Açık: {len(open_list)} | Kapalı: {len(closed_list)}",
        ]
        if checked_list:
            lines.append(f"- İşaretli skill'ler ({len(checked_list)}): {', '.join(checked_list)}")
        lines.extend(
            [
                "",
                f"AÇIK ({len(open_list)}):",
                ", ".join(open_list) if open_list else "(Yok)",
                "",
                f"KAPALI ({len(closed_list)}):",
                ", ".join(closed_list) if closed_list else "(Yok)",
                "",
                "SORU:",
                "Aşağıdaki görev için gereksiz bağlam (token) harcamadan en yüksek kaliteyi almak istiyorum. Hangi skill'ler açık kalmalı, hangileri kapatılmalı kısaca açıkla.",
                "Görevim / hedefim: [BURAYA HEDEFİNİZİ YAZIN]",
                "",
                "ZORUNLU ÇIKTI FORMATI (AIconomy bu satırı otomatik uygular):",
                "Cevabın EN SONUNA önerdiğin skill adlarını virgülle ayırarak tek satırda yaz:",
                "<<<ACIK: blender-director, blender-modeler, hard-surface, unity-export>>>",
            ]
        )
        return "\n".join(lines)

    lines = [
        "[AIconomy — Blender Skills Optimization Request]",
        f"- Total Skills: {len(BLENDER_SKILLS_94)} | Enabled: {len(open_list)} | Disabled: {len(closed_list)}",
    ]
    if checked_list:
        lines.append(f"- Checked skills ({len(checked_list)}): {', '.join(checked_list)}")
    lines.extend(
        [
            "",
            f"ENABLED ({len(open_list)}):",
            ", ".join(open_list) if open_list else "(None)",
            "",
            f"DISABLED ({len(closed_list)}):",
            ", ".join(closed_list) if closed_list else "(None)",
            "",
            "QUESTION:",
            "For the task below, recommend which Blender skills should stay enabled and which can be disabled to maximize quality while minimizing context token load.",
            "My task / goal: [DESCRIBE YOUR TASK HERE]",
            "",
            "REQUIRED OUTPUT FORMAT (AIconomy parses this automatically):",
            "At the VERY END of your reply, list the recommended skill names on a single line:",
            "<<<ENABLE: blender-director, blender-modeler, hard-surface, unity-export>>>",
        ]
    )
    return "\n".join(lines)


def parse_skills_ai_response(text: str, lang: str = "en") -> tuple[set[str], str]:
    """Parse recommended Blender skills from an AI response (supports both <<<ENABLE:>>> and <<<ACIK:>>>)."""
    is_tr = lang == "tr"
    valid = set(BLENDER_SKILLS_94)
    block_match = re.search(r"<<<\s*(?:ENABLE|ACIK)\s*:\s*(.*?)\s*>>>", text, flags=re.IGNORECASE | re.DOTALL)
    if block_match:
        body = block_match.group(1).strip()
        if not body or body.lower() in {"yok", "none", "hiçbiri", "-"}:
            return set(), ("Blok okundu (tümü kapalı önerildi)" if is_tr else "Parsed block (none enabled)")
        tokens = [tok.strip(" `'\"\n\r\t*-") for tok in re.split(r"[,;\n]+", body)]
        matched = {tok.lower() for tok in tokens if tok.lower() in valid}
        msg = (
            f"Öneri bloğundan {len(matched)} skill eşleşti"
            if is_tr
            else f"Matched {len(matched)} skill(s) from structured block"
        )
        return matched, msg

    found = {sk for sk in BLENDER_SKILLS_94 if re.search(rf"(?<![a-z0-9-]){re.escape(sk)}(?![a-z0-9-])", text.lower())}
    if found:
        msg = (
            f"Metinden {len(found)} skill adı yakalandı"
            if is_tr
            else f"Extracted {len(found)} skill name(s) from text"
        )
        return found, msg
    return set(), ("Eşleşen skill adı bulunamadı" if is_tr else "No matching skill names found")


def build_tool_ai_prompt(
    tool: ToolSpec,
    current_param: str,
    option_states: dict[str, bool],
    has_vault_key: bool,
    recent_issue: str,
    scope_display: str = "",
    lang: str = "en",
) -> str:
    open_opts = []
    closed_opts = []
    for o in tool.options:
        o_lbl, _ = localized_option_text(tool.id, o, lang)
        entry = f"{o.key} ({o_lbl})"
        if option_states.get(o.key, False):
            open_opts.append(entry)
        else:
            closed_opts.append(entry)

    modes = localized_tool_modes(tool, lang)
    mode_str = modes[min(tool.mode_index, len(modes) - 1)] if len(modes) > 1 else ("Standart" if lang == "tr" else "Standard")
    param_lbl = localized_tool_text(tool, "param_label", lang)
    q_hint = localized_tool_text(tool, "ai_question_hint", lang)
    ver = f"v{tool.version.strip().lstrip('vV')}"

    if lang == "tr":
        lines = [
            f"[AIconomy — {tool.name} ({ver}) Ayar Özeti]",
            f"- Durum: {'AÇIK' if tool.enabled else 'KAPALI'} | Son Yanıt: {tool.last_ping} | Mod: {mode_str}",
        ]
        if scope_display:
            lines.append(f"- Kapsam: {scope_display}")
        if tool.live_location_detail:
            lines.append(f"- Konum: {tool.live_location_detail}")
        if param_lbl:
            lines.append(f"- {param_lbl}: {current_param}")
        if tool.vault_key_name:
            lines.append(f"- API Anahtarı ({tool.vault_key_name}): {'Tanımlı [Gizlendi]' if has_vault_key else 'Girilmedi'}")
        if recent_issue:
            lines.append(f"- Son Sistem Logu: {recent_issue}")
        lines.extend(
            [
                f"- Seçenekler: {len(tool.options)} toplam | {len(open_opts)} açık | {len(closed_opts)} kapalı",
                "",
                f"AÇIK SEÇENEKLER ({len(open_opts)}): {', '.join(open_opts) if open_opts else '(Yok)'}",
                f"KAPALI SEÇENEKLER ({len(closed_opts)}): {', '.join(closed_opts) if closed_opts else '(Yok)'}",
                "",
                f"SORU: {q_hint or 'Bu aracın ayarlarını projem için nasıl optimize etmeliyim?'}",
                "Ek bağlam: [İSTERSENİZ BURAYA EKLEYİN]",
                "",
                "ZORUNLU ÇIKTI FORMATI (AIconomy otomatik uygular):",
                f"Cevabın EN SONUNA açık kalmasını önerdiğin seçenek anahtarlarını ({', '.join(o.key for o in tool.options)}) şu formatta yaz:",
                f"<<<ACIK: {', '.join(o.key for o in tool.options[:2]) if tool.options else 'yok'}>>>",
            ]
        )
        return "\n".join(lines)

    lines = [
        f"[AIconomy — {tool.name} ({ver}) Settings Summary]",
        f"- State: {'ON' if tool.enabled else 'OFF'} | Status: {tool.last_ping} | Mode: {mode_str}",
    ]
    if scope_display:
        lines.append(f"- Scope: {scope_display}")
    if tool.live_location_detail:
        lines.append(f"- Location: {tool.live_location_detail}")
    if param_lbl:
        lines.append(f"- {param_lbl}: {current_param}")
    if tool.vault_key_name:
        lines.append(f"- API Key ({tool.vault_key_name}): {'Configured [Hidden]' if has_vault_key else 'Not set'}")
    if recent_issue:
        lines.append(f"- Latest Log Issue: {recent_issue}")
    lines.extend(
        [
            f"- Options: {len(tool.options)} total | {len(open_opts)} enabled | {len(closed_opts)} disabled",
            "",
            f"ENABLED OPTIONS ({len(open_opts)}): {', '.join(open_opts) if open_opts else '(None)'}",
            f"DISABLED OPTIONS ({len(closed_opts)}): {', '.join(closed_opts) if closed_opts else '(None)'}",
            "",
            f"QUESTION: {q_hint or 'How should I optimize this tool for my workflow?'}",
            "Additional context: [OPTIONAL]",
            "",
            "REQUIRED OUTPUT FORMAT (AIconomy parses this automatically):",
            f"At the VERY END of your reply, list the recommended option keys ({', '.join(o.key for o in tool.options)}) like this:",
            f"<<<ENABLE: {', '.join(o.key for o in tool.options[:2]) if tool.options else 'none'}>>>",
        ]
    )
    return "\n".join(lines)


def parse_tool_ai_response(tool: ToolSpec, text: str, lang: str = "en") -> tuple[set[str], str]:
    is_tr = lang == "tr"
    valid_keys = {o.key for o in tool.options}
    block_match = re.search(r"<<<\s*(?:ENABLE|ACIK)\s*:\s*(.*?)\s*>>>", text, flags=re.IGNORECASE | re.DOTALL)
    if block_match:
        body = block_match.group(1).strip()
        if not body or body.lower() in {"yok", "none", "hiçbiri", "-"}:
            return set(), ("Blok okundu (tüm seçenekler kapalı)" if is_tr else "Parsed block (all options disabled)")
        tokens = [tok.strip(" `'\"\n\r\t*-") for tok in re.split(r"[,;\n]+", body)]
        matched = {tok for tok in tokens if tok in valid_keys}
        msg = (
            f"Öneri bloğundan {len(matched)} seçenek uygulandı"
            if is_tr
            else f"Applied {len(matched)} option(s) from structured block"
        )
        return matched, msg

    found = {k for k in valid_keys if re.search(rf"(?<![a-z0-9_]){re.escape(k)}(?![a-z0-9_])", text)}
    if found:
        msg = (
            f"Metinden {len(found)} seçenek anahtarı yakalandı"
            if is_tr
            else f"Extracted {len(found)} option key(s) from text"
        )
        return found, msg
    return set(), ("Eşleşen seçenek anahtarı bulunamadı" if is_tr else "No matching option keys found")


def build_logs_ai_prompt(
    selected_logs: list[dict],
    all_tools: list[ToolSpec],
    app_version: str,
    gpu_status: str = "",
    lang: str = "en",
) -> str:
    """Combine selected logs, affected tool versions, and system metadata into an AI troubleshooting prompt."""
    is_tr = lang == "tr"
    by_name = {t.name.lower(): t for t in all_tools}
    affected_tools: list[ToolSpec] = []
    seen_ids: set[str] = set()

    for entry in selected_logs:
        t_nm = str(entry.get("tool", "")).strip().lower()
        matched_t = by_name.get(t_nm)
        if matched_t is None:
            for cand in all_tools:
                if cand.name.lower() in t_nm or t_nm in cand.name.lower():
                    matched_t = cand
                    break
        if matched_t is not None and matched_t.id not in seen_ids:
            seen_ids.add(matched_t.id)
            affected_tools.append(matched_t)

    lines: list[str] = [
        "[AIconomy — Hata Teşhis & Çözüm İsteği]" if is_tr else "[AIconomy — Troubleshooting & Diagnostic Request]",
        (
            f"- Uygulama: v{app_version} | Sistem: Windows ({platform.release()}) / Python {platform.python_version()}"
            if is_tr
            else f"- App: v{app_version} | OS: Windows ({platform.release()}) / Python {platform.python_version()}"
        ),
    ]
    if gpu_status:
        lines.append(f"- GPU / VRAM: {gpu_status}")

    if affected_tools:
        lines.extend(["", "=== 1. ETKİLENEN ARAÇLAR ===" if is_tr else "=== 1. AFFECTED TOOLS ==="])
        for t in affected_tools:
            cur_v = t.version.strip().lstrip("vV")
            lat_v = (t.latest_version or "").strip().lstrip("vV")
            latest_word = "son sürüm" if is_tr else "latest"
            ver_info = f"v{cur_v} ({latest_word}: v{lat_v})" if (lat_v and lat_v != cur_v) else f"v{cur_v}"
            port_info = f" | Port: :{t.port}" if t.port else ""
            modes = localized_tool_modes(t, lang)
            mode_info = modes[t.mode_index] if (len(modes) > 1 and 0 <= t.mode_index < len(modes)) else ("Standart" if is_tr else "Standard")
            clients_on = ", ".join(k for k, v in t.clients.items() if v) or ("Yok" if is_tr else "None")
            state_lbl = ("AÇIK" if t.enabled else "KAPALI") if is_tr else ("ON" if t.enabled else "OFF")
            lines.append(
                f"- {t.name} | {tool_kind_label(t.kind, lang)} | {ver_info} | {state_lbl}{port_info}"
            )
            if is_tr:
                lines.append(f"  - Durum: {t.last_ping} | Mod: {mode_info} | İstemciler: {clients_on} | Kapsam: {t.project_scope}")
                if t.install_cmd:
                    lines.append(f"  - Komut: {t.install_cmd}")
                if t.live_location_detail:
                    lines.append(f"  - Konum: {t.live_location_detail}")
            else:
                lines.append(f"  - Status: {t.last_ping} | Mode: {mode_info} | Clients: {clients_on} | Scope: {t.project_scope}")
                if t.install_cmd:
                    lines.append(f"  - Command: {t.install_cmd}")
                if t.live_location_detail:
                    lines.append(f"  - Location: {t.live_location_detail}")

    lines.extend(["", "=== 2. TÜM ARAÇLAR ===" if is_tr else "=== 2. ALL TOOLS ==="])
    compact_tools = [
        f"{t.name} (v{t.version.lstrip('vV')}, {('AÇIK' if t.enabled else 'KAPALI') if is_tr else ('ON' if t.enabled else 'OFF')}{f', :{t.port}' if t.port else ''})"
        for t in all_tools
    ]
    lines.append(", ".join(compact_tools))

    lines.extend(
        [
            "",
            f"=== 3. SEÇİLEN LOGLAR ({len(selected_logs)}) ==="
            if is_tr
            else f"=== 3. SELECTED LOGS ({len(selected_logs)}) ===",
        ]
    )
    sum_lbl = "Özet" if is_tr else "Summary"
    for idx, entry in enumerate(selected_logs, start=1):
        port_tag = f" | Port: :{entry['port']}" if entry.get("port") else ""
        lines.append(f"\n--- #{idx} [{entry.get('ts', '')}] [{entry.get('level', '')}] {entry.get('tool', '')}{port_tag} ---")
        lines.append(f"{sum_lbl}: {entry.get('summary', '')}")
        raw_det = str(entry.get("raw_detail", "")).strip()
        if raw_det and raw_det != str(entry.get("summary", "")).strip():
            lines.append("```text")
            lines.append(raw_det)
            lines.append("```")

    if is_tr:
        lines.extend(
            [
                "",
                "=== İSTENEN ÇÖZÜM ===",
                "1) Kök nedeni (root cause) kısaca açıkla.",
                "2) Sorunu çözmek için gereken komutları veya ayar değişikliklerini adım adım yaz.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "=== REQUESTED OUTPUT ===",
                "1) Briefly explain the root cause.",
                "2) Provide step-by-step commands or config fixes to resolve it.",
            ]
        )
    return "\n".join(lines)
