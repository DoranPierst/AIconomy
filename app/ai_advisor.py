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


def build_logs_ai_prompt(
    selected_logs: list[dict],
    all_tools: list[ToolSpec],
    app_version: str,
    gpu_status: str = "",
) -> str:
    """Seçilen debug/hata loglarını, ilgili araçların sürümlerini ve ortam bilgisini birleştirerek hazır AI çözüm promptu üretir."""
    import platform

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
        "[AI Araç & Token Ekonomisi Kontrol Merkezi — Hata Teşhis & Çözüm İsteği]",
        f"• Program Sürümü: {app_version}v | Sistem: Windows ({platform.release()}) / Python {platform.python_version()}",
    ]
    if gpu_status:
        lines.append(f"• GPU / VRAM Durumu: {gpu_status}")

    # 1) Loglarda adı geçen araçların detaylı sürüm ve yapılandırma bilgisi
    if affected_tools:
        lines.extend(["", "=== 1. ETKİLENEN ARAÇLARIN SÜRÜM VE AYAR BİLGİLERİ ==="])
        for t in affected_tools:
            cur_v = t.version.strip().lstrip("vV")
            lat_v = (t.latest_version or "").strip().lstrip("vV")
            ver_info = f"{cur_v}v (Son sürüm: {lat_v}v)" if (lat_v and lat_v != cur_v) else f"{cur_v}v"
            port_info = f" | Port: :{t.port}" if t.port else ""
            mode_info = t.modes[t.mode_index] if (len(t.modes) > 1 and 0 <= t.mode_index < len(t.modes)) else "Standart"
            clients_on = ", ".join(k for k, v in t.clients.items() if v) or "Kapalı"
            lines.append(
                f"- {t.name} | Tür: {t.kind} | Sürüm: {ver_info} | Durum: {'AÇIK' if t.enabled else 'KAPALI'}{port_info}"
            )
            lines.append(f"  • Son Yanıt: {t.last_ping} | Mod: {mode_info} | AI İstemcileri: {clients_on} | Kapsam: {t.project_scope}")
            if t.install_cmd:
                lines.append(f"  • Kurulum / Çalıştırma Komutu: {t.install_cmd}")
            if t.live_location_detail:
                lines.append(f"  • Konum Detayı: {t.live_location_detail}")
            if t.options:
                on_opts = [f"{o.key}=Açık" if o.enabled else f"{o.key}=Kapalı" for o in t.options]
                lines.append(f"  • Alt Seçenekler: {', '.join(on_opts)}")

    # 2) Tüm kurulu/kayıtlı araçların sürüm özeti (çakışma/uyumluluk kontrolü için)
    lines.extend(["", "=== 2. TÜM ARAÇLAR VE SÜRÜM ÖZETİ ==="])
    compact_tools = [
        f"{t.name} ({t.version.lstrip('vV')}v, {'AÇIK' if t.enabled else 'KAPALI'}{f', :{t.port}' if t.port else ''})"
        for t in all_tools
    ]
    lines.append(", ".join(compact_tools))

    # 3) Seçilen hata / debug logları ve ham çıktılar
    lines.extend(["", f"=== 3. SEÇİLEN LOG VE HATA KAYITLARI ({len(selected_logs)} Adet) ==="])
    for idx, entry in enumerate(selected_logs, start=1):
        port_tag = f" | Port: {entry['port']}" if entry.get("port") else ""
        lines.append(f"\n--- Kayıt #{idx} [{entry.get('ts', '')}] [{entry.get('level', '')}] Araç: {entry.get('tool', '')}{port_tag} ---")
        lines.append(f"Özet: {entry.get('summary', '')}")
        raw_det = str(entry.get("raw_detail", "")).strip()
        if raw_det and raw_det != str(entry.get("summary", "")).strip():
            lines.append("Ham Teknik Çıktı (stdout / stderr / detay):")
            lines.append("```text")
            lines.append(raw_det)
            lines.append("```")

    lines.extend(
        [
            "",
            "=== BEKLENEN ÇÖZÜM ===",
            "Yukarıdaki hata kayıtlarını, araç sürümlerini, portları ve ham teknik çıktıları inceleyerek:",
            "1) Sorunun kök nedenini (root cause) kısaca açıkla.",
            "2) Sorunu kesin olarak çözmek için çalıştırmam gereken komutları veya değiştirmem gereken ayarları adım adım yaz.",
        ]
    )
    return "\n".join(lines)
