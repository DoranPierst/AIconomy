"""Çift Yönlü AI Danışma: Prompt Üretici ve AI Yanıt Ayrıştırıcı (<<<ACIK: ...>>>)."""
from __future__ import annotations

import re

from .catalog import BLENDER_SKILLS_94, ToolSpec


def build_skills_ai_prompt(active_skills: set[str], checked_skills: set[str]) -> str:
    open_list = [s for s in BLENDER_SKILLS_94 if s in active_skills]
    closed_list = [s for s in BLENDER_SKILLS_94 if s not in active_skills]
    checked_list = [s for s in BLENDER_SKILLS_94 if s in checked_skills]

    lines: list[str] = [
        "[AI Araç Merkezi — Blender Skills (arjun988) Danışma Özeti]",
        f"• Toplam Skill: {len(BLENDER_SKILLS_94)} | Açık: {len(open_list)} | Kapalı: {len(closed_list)}",
    ]
    if checked_list:
        lines.append(f"• Üzerinde kararsız kaldığım (tikli) skill'ler ({len(checked_list)}): {', '.join(checked_list)}")
    lines.extend(
        [
            "",
            f"✅ AÇIK OLANLAR ({len(open_list)}):",
            ", ".join(open_list) if open_list else "(Hiçbiri açık değil)",
            "",
            f"⛔ KAPALI OLANLAR ({len(closed_list)}):",
            ", ".join(closed_list) if closed_list else "(Hiçbiri kapalı değil)",
            "",
            "SORUM:",
            "Aşağıda yazacağım proje/görev için gereksiz bağlam (token) harcamadan en yüksek kaliteyi almak istiyorum. Hangi skill'ler açık kalmalı, hangileri kapatılmalı kısaca açıkla.",
            "Yapacağım iş / hedefim: [BURAYA HEDEFİNİ YAZ]",
            "",
            "ZORUNLU ÇIKTI FORMATI (Programım bu satırı otomatik okuyup uygulayacak):",
            "Cevabının EN SONUNA mutlaka aşağıdaki kalıpla, açık kalmasını önerdiğin skill'lerin tam adlarını virgülle ayırarak tek satır halinde yaz:",
            "<<<ACIK: blender-director, blender-modeler, hard-surface, unity-export>>>",
        ]
    )
    return "\n".join(lines)


def parse_skills_ai_response(text: str) -> tuple[set[str], str]:
    """AI yanıtından açık kalacak Blender skill listesini çıkarır."""
    valid = set(BLENDER_SKILLS_94)
    block_match = re.search(r"<<<\s*ACIK\s*:\s*(.*?)\s*>>>", text, flags=re.IGNORECASE | re.DOTALL)
    if block_match:
        body = block_match.group(1).strip()
        if not body or body.lower() in {"yok", "none", "hiçbiri", "-"}:
            return set(), "<<<ACIK>>> bloğu okundu (tümü kapalı önerildi)"
        tokens = [tok.strip(" `'\"\n\r\t*•-") for tok in re.split(r"[,;\n]+", body)]
        matched = {tok.lower() for tok in tokens if tok.lower() in valid}
        return matched, f"<<<ACIK>>> bloğundan {len(matched)} skill tam eşleşti"

    # Yedek akıllı yakalayıcı: AI köşeli bloğu unutsa bile metin içindeki tam skill adlarını yakalar
    found = {sk for sk in BLENDER_SKILLS_94 if re.search(rf"(?<![a-z0-9-]){re.escape(sk)}(?![a-z0-9-])", text.lower())}
    if found:
        return found, f"Metin taramasıyla {len(found)} skill adı yakalandı (<<<ACIK>>> bloğu bulunamadı)"
    return set(), "Eşleşen skill adı bulunamadı"


def build_tool_ai_prompt(
    tool: ToolSpec,
    current_param: str,
    option_states: dict[str, bool],
    has_vault_key: bool,
    recent_issue: str,
    scope_display: str = "",
) -> str:
    open_opts = [f"{o.key} ({o.label})" for o in tool.options if option_states.get(o.key, False)]
    closed_opts = [f"{o.key} ({o.label})" for o in tool.options if not option_states.get(o.key, False)]
    mode_str = tool.modes[tool.mode_index] if len(tool.modes) > 1 else "Standart"

    lines: list[str] = [
        f"[AI Araç Merkezi — {tool.name} ({tool.version}) Ayar Özeti]",
        f"• Genel Durum: {'AÇIK' if tool.enabled else 'KAPALI'} | Son Yanıt: {tool.last_ping} | Çalışma Modu: {mode_str}",
    ]
    if scope_display:
        lines.append(f"• Proje / Konum Kapsamı: {scope_display}")
    if tool.live_location_detail:
        lines.append(f"• Algılanan Canlı Konum: {tool.live_location_detail}")
    if tool.param_label:
        lines.append(f"• {tool.param_label}: {current_param}")
    if tool.vault_key_name:
        lines.append(f"• Şifreli Kasa ({tool.vault_key_name}): {'Tanımlı [Gizlendi]' if has_vault_key else 'Henüz Girilmedi'}")
    if recent_issue:
        lines.append(f"• Son Sistem Logu: {recent_issue}")

    lines.extend(
        [
            f"• Toplam Seçenek: {len(tool.options)} | Açık: {len(open_opts)} | Kapalı: {len(closed_opts)}",
            "",
            f"✅ AÇIK ÖZELLİKLER ({len(open_opts)}): {', '.join(open_opts) if open_opts else '(Yok)'}",
            f"⛔ KAPALI ÖZELLİKLER ({len(closed_opts)}): {', '.join(closed_opts) if closed_opts else '(Yok)'}",
            "",
            f"SORUM: {tool.ai_question_hint}",
            "Ek bağlam / hedefim: [İSTERSEN BURAYA EKLE]",
            "",
            "ZORUNLU ÇIKTI FORMATI (Programım otomatik okuyacak):",
            f"Cevabının EN SONUNA açık kalmasını önerdiğin seçenek anahtarlarını ({', '.join(o.key for o in tool.options)}) şu formatta yaz:",
            f"<<<ACIK: {', '.join(o.key for o in tool.options[:2]) if tool.options else 'yok'}>>>",
        ]
    )
    return "\n".join(lines)


def parse_tool_ai_response(tool: ToolSpec, text: str) -> tuple[set[str], str]:
    valid_keys = {o.key for o in tool.options}
    block_match = re.search(r"<<<\s*ACIK\s*:\s*(.*?)\s*>>>", text, flags=re.IGNORECASE | re.DOTALL)
    if block_match:
        body = block_match.group(1).strip()
        if not body or body.lower() in {"yok", "none", "hiçbiri", "-"}:
            return set(), "<<<ACIK>>> bloğu okundu (tüm alt seçenekler kapalı)"
        tokens = [tok.strip(" `'\"\n\r\t*•-") for tok in re.split(r"[,;\n]+", body)]
        matched = {tok for tok in tokens if tok in valid_keys}
        return matched, f"<<<ACIK>>> bloğundan {len(matched)} seçenek uygulandı"

    found = {k for k in valid_keys if re.search(rf"(?<![a-z0-9_]){re.escape(k)}(?![a-z0-9_])", text)}
    if found:
        return found, f"Metinden {len(found)} seçenek anahtarı yakalandı"
    return set(), "Eşleşen seçenek anahtarı bulunamadı"
