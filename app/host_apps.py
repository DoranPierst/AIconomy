"""Host desktop application discovery and launching (emoji-free, EN & TR)."""
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
    lang: str = "en",
) -> list[dict[str, Any]]:
    """Return enabled tools whose host desktop application or local server is not running yet."""
    is_tr = lang == "tr"
    by_id = {t.id: t for t in tools}
    missing: list[dict[str, Any]] = []

    bm = by_id.get("blender_mcp")
    if bm and bm.enabled and live_map.get("blender_open") != "1":
        missing.append(
            {
                "host": "blender",
                "title": "Blender kapalı" if is_tr else "Blender closed",
                "detail": (
                    "Blender MCP açık; bağlanabilmek için Blender simge durumunda başlatılıp :9876 köprüsü açılır."
                    if is_tr
                    else "Blender MCP is enabled; launches Blender minimized and starts the :9876 socket bridge."
                ),
                "btn_label": "Blender'ı Başlat" if is_tr else "Launch Blender",
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
                "title": "Unity Editor kapalı" if is_tr else "Unity Editor closed",
                "detail": (
                    "Unity MCP / Pipeline açık; projeyi kilitlememesi için normal Unity Editor simge durumunda açılır."
                    if is_tr
                    else "Unity MCP / Pipeline is enabled; launches Unity Editor minimized without stealing focus."
                ),
                "btn_label": "Unity'yi Başlat" if is_tr else "Launch Unity",
                "headless": False,
                "scope": target_scope,
            }
        )

    rd = by_id.get("renderdoc_mcp")
    if rd and rd.enabled and live_map.get("renderdoc_open") != "1" and _find_renderdoc_exe() is not None:
        missing.append(
            {
                "host": "renderdoc",
                "title": "RenderDoc kapalı" if is_tr else "RenderDoc closed",
                "detail": (
                    "RenderDoc MCP açık; GPU kare analizi için RenderDoc simge durumunda başlatılabilir."
                    if is_tr
                    else "RenderDoc MCP is enabled; launches RenderDoc minimized."
                ),
                "btn_label": "RenderDoc Başlat" if is_tr else "Launch RenderDoc",
                "headless": False,
                "scope": rd.project_scope,
            }
        )

    tr_tool = by_id.get("trellis")
    if tr_tool and tr_tool.enabled and "trellis" not in live_map:
        srv_exe = pathlib.Path(tr_tool.param_value) / "runtime" / "trellis-server.exe"
        if srv_exe.is_file():
            missing.append(
                {
                    "host": "trellis",
                    "title": "TRELLIS uykuda" if is_tr else "TRELLIS standby",
                    "detail": (
                        "TRELLIS açık; yerel GPU sunucusu arka planda başlatılabilir."
                        if is_tr
                        else "TRELLIS is enabled; starts the local GPU server in the background."
                    ),
                    "btn_label": "TRELLIS Başlat" if is_tr else "Start TRELLIS",
                    "headless": True,
                    "scope": tr_tool.project_scope,
                }
            )

    return missing


def launch_host_app_for_tool(
    host_kind: str,
    projects_map: dict[str, str],
    target_scope: str = "GLOBAL",
    headless: bool = False,
    trellis_root: str = "",
    lang: str = "en",
) -> tuple[bool, str]:
    """Launch a required host app minimized (without stealing focus) or headless when supported."""
    is_tr = lang == "tr"
    si_minimized = None
    if os.name == "nt":
        si_minimized = subprocess.STARTUPINFO()
        si_minimized.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si_minimized.wShowWindow = 7  # SW_SHOWMINNOACTIVE

    if host_kind == "blender":
        b_exe = _find_blender_exe()
        if not b_exe:
            return False, ("blender.exe sistemde bulunamadı." if is_tr else "blender.exe was not found on this machine.")
        py_expr = (
            "import bpy; "
            "bpy.app.timers.register(lambda: ((bpy.ops.blendermcp.start_server() and None) if hasattr(bpy.ops, 'blendermcp') else None), first_interval=1.2)"
        )
        subprocess.Popen([str(b_exe), "--python-expr", py_expr], startupinfo=si_minimized)
        return True, (
            "Blender simge durumunda başlatıldı ve :9876 MCP köprüsü tetiklendi."
            if is_tr
            else "Launched Blender minimized and triggered the :9876 MCP bridge."
        )

    if host_kind == "unity":
        proj_path: pathlib.Path | None = None
        if target_scope != "GLOBAL" and target_scope in projects_map:
            proj_path = pathlib.Path(projects_map[target_scope])
        elif projects_map:
            proj_path = pathlib.Path(next(iter(projects_map.values())))
        u_exe = _find_unity_exe(proj_path)
        if not u_exe:
            return False, ("Unity.exe kurulumu bulunamadı." if is_tr else "Unity.exe installation was not found.")
        cmd = [str(u_exe)]
        if proj_path and proj_path.is_dir():
            cmd.extend(["-projectPath", str(proj_path)])
        if headless:
            cmd.extend(["-batchmode", "-nographics"])
            subprocess.Popen(cmd, creationflags=NO_WINDOW)
            return True, (
                f"Unity arka planda başlatıldı: {proj_path or u_exe.name}"
                if is_tr
                else f"Started Unity in batchmode: {proj_path or u_exe.name}"
            )
        subprocess.Popen(cmd, startupinfo=si_minimized)
        return True, (
            f"Unity Editor simge durumunda başlatıldı: {proj_path or u_exe.name}"
            if is_tr
            else f"Launched Unity Editor minimized: {proj_path or u_exe.name}"
        )

    if host_kind == "renderdoc":
        r_exe = _find_renderdoc_exe()
        if not r_exe:
            return False, ("qrenderdoc.exe bulunamadı." if is_tr else "qrenderdoc.exe was not found.")
        subprocess.Popen([str(r_exe)], startupinfo=si_minimized)
        return True, ("RenderDoc simge durumunda başlatıldı." if is_tr else "Launched RenderDoc minimized.")

    if host_kind == "trellis":
        srv_exe = pathlib.Path(trellis_root or str(pathlib.Path.home() / "Trellis")) / "runtime" / "trellis-server.exe"
        if not srv_exe.is_file():
            return False, (
                f"TRELLIS sunucusu bulunamadı: {srv_exe}"
                if is_tr
                else f"TRELLIS server not found: {srv_exe}"
            )
        subprocess.Popen([str(srv_exe)], creationflags=NO_WINDOW)
        return True, (
            "TRELLIS GPU sunucusu arka planda başlatıldı."
            if is_tr
            else "Started TRELLIS GPU server in the background."
        )

    return False, (f"Bilinmeyen hedef program: {host_kind}" if is_tr else f"Unknown host application: {host_kind}")
