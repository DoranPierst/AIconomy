"""Host desktop application discovery and launching (Blender, Unity Editor, RenderDoc, TRELLIS)."""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
from typing import Any

from .catalog import ToolSpec

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _find_blender_exe() -> pathlib.Path | None:
    base = pathlib.Path(r"C:\Program Files\Blender Foundation")
    if base.is_dir():
        cands = sorted(base.glob("Blender */blender.exe"), reverse=True)
        for cand in cands:
            if cand.is_file():
                return cand
    found = shutil.which("blender")
    return pathlib.Path(found) if found else None


def _find_unity_exe(project_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    hub_root = pathlib.Path(r"C:\Program Files\Unity\Hub\Editor")
    if project_dir and project_dir.is_dir():
        ver_file = project_dir / "ProjectSettings" / "ProjectVersion.txt"
        if ver_file.is_file():
            m = re.search(
                r"m_EditorVersion:\s*([^\s\r\n]+)",
                ver_file.read_text(encoding="utf-8", errors="ignore"),
            )
            if m:
                cand = hub_root / m.group(1).strip() / "Editor" / "Unity.exe"
                if cand.is_file():
                    return cand
    if hub_root.is_dir():
        editors = sorted(hub_root.glob("*/Editor/Unity.exe"), reverse=True)
        if editors:
            return editors[0]
    found = shutil.which("Unity")
    return pathlib.Path(found) if found else None


def _find_renderdoc_exe() -> pathlib.Path | None:
    for cand in (
        pathlib.Path(r"C:\Program Files\RenderDoc\qrenderdoc.exe"),
        pathlib.Path(r"C:\Program Files (x86)\RenderDoc\qrenderdoc.exe"),
    ):
        if cand.is_file():
            return cand
    found = shutil.which("qrenderdoc")
    return pathlib.Path(found) if found else None


def get_missing_host_dependencies(
    tools: list[ToolSpec],
    live_map: dict[str, str],
    projects_map: dict[str, str],
) -> list[dict[str, Any]]:
    """Return enabled tools whose host desktop application or local server is not running yet."""
    by_id = {t.id: t for t in tools}
    missing: list[dict[str, Any]] = []

    bm = by_id.get("blender_mcp")
    if bm and bm.enabled and live_map.get("blender_open") != "1":
        missing.append(
            {
                "host": "blender",
                "title": "Blender kapalı",
                "detail": "Blender MCP AÇIK; bağlanabilmesi için Blender'ın başlatılması gerekir (eklenti -b arkaplan modunu desteklemediği için simge durumunda açılır).",
                "btn_label": "🚀 Blender'ı Başlat (Simge + :9876)",
                "headless": False,
                "scope": bm.project_scope,
            }
        )

    um = by_id.get("unity_mcp")
    up = by_id.get("unity_pipeline")
    if ((um and um.enabled) or (up and up.enabled)) and live_map.get("unity_open") != "1":
        target_scope = (um.project_scope if um and um.enabled else up.project_scope) if (um or up) else "GLOBAL"
        missing.append(
            {
                "host": "unity",
                "title": "Unity Editor kapalı",
                "detail": "Unity MCP / Pipeline AÇIK; sahne/editor komutları için Unity Editor çalıştırılmalıdır (projeyi kilitlememesi için normal Editor odak çalmadan simge durumunda açılır).",
                "btn_label": "🚀 Unity Editor'ü Başlat (Simge)",
                "headless": False,
                "scope": target_scope,
            }
        )

    rd = by_id.get("renderdoc_mcp")
    if rd and rd.enabled and live_map.get("renderdoc_open") != "1" and _find_renderdoc_exe() is not None:
        missing.append(
            {
                "host": "renderdoc",
                "title": "RenderDoc kapalı",
                "detail": "RenderDoc MCP AÇIK; GPU kare analizi için RenderDoc başlatılabilir.",
                "btn_label": "🚀 RenderDoc Başlat (Simge)",
                "headless": False,
                "scope": rd.project_scope,
            }
        )

    tr = by_id.get("trellis")
    if tr and tr.enabled and "trellis" not in live_map:
        srv_exe = pathlib.Path(tr.param_value) / "runtime" / "trellis-server.exe"
        if srv_exe.is_file():
            missing.append(
                {
                    "host": "trellis",
                    "title": "Trellis GPU sunucusu uykuda",
                    "detail": "Trellis AÇIK; yerel 3D sunucu UI'sız olarak başlatılabilir.",
                    "btn_label": "🚀 Trellis Başlat (UI'sız)",
                    "headless": True,
                    "scope": tr.project_scope,
                }
            )

    return missing


def launch_host_app_for_tool(
    host_kind: str,
    projects_map: dict[str, str],
    target_scope: str = "GLOBAL",
    headless: bool = True,
    trellis_root: str = "",
) -> tuple[bool, str]:
    """Launch a required host app minimized (without stealing focus) or headless when supported."""
    si_minimized = None
    if os.name == "nt":
        si_minimized = subprocess.STARTUPINFO()
        si_minimized.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si_minimized.wShowWindow = 7  # SW_SHOWMINNOACTIVE

    if host_kind == "blender":
        b_exe = _find_blender_exe()
        if not b_exe:
            return False, "Blender.exe sistemde bulunamadı."
        py_expr = (
            "import bpy; "
            "bpy.app.timers.register(lambda: (bpy.ops.blendermcp.start_server() if hasattr(bpy.ops, 'blendermcp') else None), first_interval=1.2)"
        )
        subprocess.Popen([str(b_exe), "--python-expr", py_expr], startupinfo=si_minimized)
        return True, "Blender odak çalmadan simge durumunda başlatıldı ve :9876 MCP köprüsü tetiklendi."

    if host_kind == "unity":
        proj_path: pathlib.Path | None = None
        if target_scope != "GLOBAL" and target_scope in projects_map:
            proj_path = pathlib.Path(projects_map[target_scope])
        elif projects_map:
            proj_path = pathlib.Path(next(iter(projects_map.values())))
        u_exe = _find_unity_exe(proj_path)
        if not u_exe:
            return False, "Unity.exe kurulumu bulunamadı."
        cmd = [str(u_exe)]
        if proj_path and proj_path.is_dir():
            cmd.extend(["-projectPath", str(proj_path)])
        if headless:
            cmd.extend(["-batchmode", "-nographics"])
            subprocess.Popen(cmd, creationflags=NO_WINDOW)
            return True, f"Unity arka planda UI'sız (-batchmode -nographics) başlatıldı: {proj_path or u_exe.name}"
        subprocess.Popen(cmd, startupinfo=si_minimized)
        return True, f"Unity Editor simge durumunda başlatıldı: {proj_path or u_exe.name}"

    if host_kind == "renderdoc":
        r_exe = _find_renderdoc_exe()
        if not r_exe:
            return False, "qrenderdoc.exe bulunamadı."
        subprocess.Popen([str(r_exe)], startupinfo=si_minimized)
        return True, "RenderDoc simge durumunda başlatıldı."

    if host_kind == "trellis":
        srv_exe = pathlib.Path(trellis_root or str(pathlib.Path.home() / "Trellis")) / "runtime" / "trellis-server.exe"
        if not srv_exe.is_file():
            return False, f"Trellis sunucusu bulunamadı: {srv_exe}"
        subprocess.Popen([str(srv_exe)], creationflags=NO_WINDOW)
        return True, "Trellis GPU sunucusu UI'sız olarak arka planda başlatıldı."

    return False, f"Bilinmeyen hedef program: {host_kind}"
