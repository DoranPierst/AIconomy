"""AI diagnostic prompt builder for selected log entries (emoji-free, EN & TR)."""
from __future__ import annotations

import platform
from typing import Iterable

from .catalog import ToolSpec, localized_tool_modes, tool_kind_label
from .security import redact_secrets


def build_logs_ai_prompt(
    selected_logs: list[dict],
    all_tools: list[ToolSpec],
    app_version: str,
    gpu_status: str = "",
    lang: str = "en",
    extra_secrets: Iterable[str] = (),
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
            mode_info = (
                modes[t.mode_index]
                if (len(modes) > 1 and 0 <= t.mode_index < len(modes))
                else ("Standart" if is_tr else "Standard")
            )
            clients_on = ", ".join(k for k, v in t.clients.items() if v) or ("Yok" if is_tr else "None")
            state_lbl = ("AÇIK" if t.enabled else "KAPALI") if is_tr else ("ON" if t.enabled else "OFF")
            lines.append(
                f"- {t.name} | {tool_kind_label(t.kind, lang)} | {ver_info} | {state_lbl}{port_info}"
            )
            if is_tr:
                lines.append(
                    f"  - Durum: {t.last_ping} | Mod: {mode_info} | İstemciler: {clients_on} | Kapsam: {t.project_scope}"
                )
                if t.install_cmd:
                    lines.append(f"  - Komut: {t.install_cmd}")
                if t.live_location_detail:
                    lines.append(f"  - Konum: {t.live_location_detail}")
            else:
                lines.append(
                    f"  - Status: {t.last_ping} | Mode: {mode_info} | Clients: {clients_on} | Scope: {t.project_scope}"
                )
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
    return redact_secrets("\n".join(lines), extra_secrets=extra_secrets)
