"""Built-in tool catalog, 94 Blender skills, project scopes, and starter profiles (100% EN & TR, emoji-free)."""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any

from .i18n import tr
from .library_catalog import _TR_LIBRARY_TEXT, build_library_catalog

BLENDER_SKILLS_94: list[str] = [
    "analog-found-footage-horror", "animation", "anime-style", "apocalypse-worlds", "archviz", "asset-optimization",
    "biome-worlds", "blender-director", "blender-modeler", "body-horror-style", "brutalist-mood", "camera-cinematography",
    "cartoon-style", "character-archetypes", "character-artist", "chibi-style", "cloth-sim", "collision-proxy",
    "comic-book-style", "compositing", "cosmic-eldritch-horror", "cozy-wholesome-mood", "creature-artist", "dark-gritty-mood",
    "dream-surreal-mood", "dream-weirdcore-style", "environment-artist", "export-pipeline", "fantasy-worlds", "folk-horror-style",
    "frutiger-aero-style", "genre-action-combat", "genre-card-party-idle", "genre-metroidvania-roguelike", "genre-narrative-vn", "genre-open-world-sandbox",
    "genre-puzzle-platformer", "genre-racing-sports", "genre-rpg", "genre-shooter", "genre-soulslike", "genre-stealth",
    "genre-strategy-sim", "genre-survival", "geometry-nodes", "godot-export", "hair-groom", "hand-painted-style",
    "hard-surface", "hd-2d-style", "historical-worlds", "horror-style", "indie-horror-aesthetics", "isometric-style",
    "lighting", "liminal-space-style", "lod-pipeline", "lookdev", "lowpoly-style", "manga-style",
    "mascot-puppet-horror", "materials", "minimalist-style", "neon-retrofuturism", "noir-style", "painterly-style",
    "physics-sim", "pixel-art-style", "procedural-modeling", "prop-artist", "psx-horror-style", "qa-review",
    "realistic-style", "rendering", "retopology", "retro-16bit-style", "retro-8bit-style", "rigging",
    "scene-assembly", "sci-fi-punk-worlds", "sculpting", "set-dressing", "stop-motion-craft-style", "stylized-style",
    "texture-workflow", "unity-export", "unreal-export", "uv-workflow", "vector-style", "vegetation-artist",
    "vehicle-artist", "vfx-fx", "visual-console-eras", "voxel-style",
]

# Neutral general-purpose default 3D skills (no genre bias for public releases)
BLENDER_SKILL_INDEX_TOKENS: int = 60

DEFAULT_ACTIVE_BLENDER_SKILLS: list[str] = [
    "blender-director",
    "blender-modeler",
    "hard-surface",
    "prop-artist",
    "uv-workflow",
    "materials",
    "lighting",
    "asset-optimization",
    "export-pipeline",
    "unity-export",
]

AI_CLIENTS: list[tuple[str, str]] = [
    ("AGY", "Google Antigravity"),
    ("CDX", "OpenAI Codex"),
    ("CLD", "Claude Code"),
    ("CUR", "Cursor"),
]

TOOL_KINDS: tuple[str, ...] = ("http", "stdio", "skill_pack", "rule", "cli")

BENEFIT_TAG_IDS: tuple[str, ...] = ("token_saver", "free_local")

DOMAIN_TAG_IDS: tuple[str, ...] = (
    "coding_lsp",
    "desktop_ui",
    "git_repo",
    "unity",
    "modeling_3d",
    "style_3d",
    "shader_gpu",
    "audio_sfx",
    "web_browser",
    "database",
    "cloud_devops",
    "docs_search",
    "design_ui",
    "security",
    "testing_qa",
    "automation",
)

ALL_TAG_IDS: tuple[str, ...] = BENEFIT_TAG_IDS + DOMAIN_TAG_IDS

LIBRARY_CATEGORY_IDS: tuple[str, ...] = (
    "coding_dev",
    "git_vcs",
    "web_browser",
    "database_data",
    "cloud_devops",
    "game_3d",
    "design_ui",
    "productivity_docs",
    "security_qa",
    "ai_memory",
)

BLENDER_SKILL_GROUP_IDS: tuple[str, ...] = (
    "modeling",
    "uv_material",
    "lighting_render",
    "rig_anim_sim",
    "horror_mood",
    "engine_export",
)

_MODELING_SKILLS = frozenset(
    {
        "blender-director",
        "blender-modeler",
        "hard-surface",
        "prop-artist",
        "character-artist",
        "character-archetypes",
        "creature-artist",
        "environment-artist",
        "vegetation-artist",
        "vehicle-artist",
        "sculpting",
        "retopology",
        "geometry-nodes",
        "procedural-modeling",
        "archviz",
        "scene-assembly",
        "set-dressing",
    }
)
_LIGHTING_RENDER_SKILLS = frozenset({"lighting", "camera-cinematography", "rendering", "compositing"})
_RIG_ANIM_SIM_SKILLS = frozenset({"rigging", "animation", "cloth-sim", "hair-groom", "physics-sim", "vfx-fx"})
_HORROR_MOOD_SKILLS = frozenset(
    {
        "analog-found-footage-horror",
        "body-horror-style",
        "cosmic-eldritch-horror",
        "folk-horror-style",
        "horror-style",
        "indie-horror-aesthetics",
        "liminal-space-style",
        "mascot-puppet-horror",
        "psx-horror-style",
        "brutalist-mood",
        "cozy-wholesome-mood",
        "dark-gritty-mood",
        "dream-surreal-mood",
        "dream-weirdcore-style",
        "apocalypse-worlds",
        "biome-worlds",
        "fantasy-worlds",
        "historical-worlds",
        "sci-fi-punk-worlds",
    }
)
_ENGINE_EXPORT_SKILLS = frozenset(
    {
        "asset-optimization",
        "collision-proxy",
        "export-pipeline",
        "godot-export",
        "lod-pipeline",
        "qa-review",
        "unity-export",
        "unreal-export",
    }
)


def is_benefit_tag(tag_id: str) -> bool:
    return tag_id in BENEFIT_TAG_IDS


def tag_label(tag_id: str, lang: str = "en") -> str:
    return tr(lang, f"tag_{tag_id}")


def category_label(cat_id: str, lang: str = "en") -> str:
    return tr(lang, f"cat_{cat_id}")


def blender_skill_group(skill_name: str) -> str:
    if skill_name in _MODELING_SKILLS:
        return "modeling"
    if skill_name in _LIGHTING_RENDER_SKILLS:
        return "lighting_render"
    if skill_name in _RIG_ANIM_SIM_SKILLS:
        return "rig_anim_sim"
    if skill_name in _HORROR_MOOD_SKILLS:
        return "horror_mood"
    if skill_name in _ENGINE_EXPORT_SKILLS or skill_name.startswith("genre-"):
        return "engine_export"
    return "uv_material"


def blender_group_label(group_id: str, lang: str = "en") -> str:
    return tr(lang, f"skgrp_{group_id}")


def recommended_blender_skills_for_tags(selected_tags: set[str]) -> set[str]:
    """Build a focused subset of Blender skills matching the user's selected task tags."""
    chosen: set[str] = set()
    if "modeling_3d" in selected_tags:
        chosen.update(DEFAULT_ACTIVE_BLENDER_SKILLS)
    if "style_3d" in selected_tags:
        chosen.update(
            {
                "blender-director",
                "uv-workflow",
                "materials",
                "texture-workflow",
                "lookdev",
                "lighting",
                "stylized-style",
                "lowpoly-style",
            }
        )
    if "unity" in selected_tags and ("modeling_3d" in selected_tags or "style_3d" in selected_tags):
        chosen.update({"unity-export", "export-pipeline", "asset-optimization", "collision-proxy", "lod-pipeline"})
    if "shader_gpu" in selected_tags and ("modeling_3d" in selected_tags or "style_3d" in selected_tags):
        chosen.update({"materials", "lighting", "rendering", "lookdev"})
    return chosen if chosen else set(DEFAULT_ACTIVE_BLENDER_SKILLS)

_LEGACY_KIND_MAP: dict[str, str] = {
    "http": "http",
    "http servis": "http",
    "stdio": "stdio",
    "stdio mcp": "stdio",
    "skill_pack": "skill_pack",
    "skill paketi": "skill_pack",
    "skill pack": "skill_pack",
    "rule": "rule",
    "skill / kural": "rule",
    "cli": "cli",
    "cli / gpu": "cli",
}


def normalize_tool_kind(raw_kind: str) -> str:
    return _LEGACY_KIND_MAP.get((raw_kind or "").strip().lower(), "stdio")


def tool_kind_label(kind: str, lang: str = "en") -> str:
    code = normalize_tool_kind(kind)
    return tr(lang, f"kind_{code}")


def _detect_local_unity_project() -> pathlib.Path | None:
    for base_dir in [
        pathlib.Path.home() / "Desktop",
        pathlib.Path.home() / "Documents",
        pathlib.Path.home() / "Projects",
        pathlib.Path.home() / "Unity",
    ]:
        if base_dir.is_dir():
            for child in base_dir.iterdir():
                if not child.is_dir():
                    continue
                nested = child / child.name
                if (nested / "Packages" / "manifest.json").is_file():
                    return nested
                if (child / "Packages" / "manifest.json").is_file():
                    return child
    return None


def _detect_local_trellis_dir() -> str:
    candidates = [
        pathlib.Path.home() / "Trellis",
        pathlib.Path("C:/Trellis"),
        pathlib.Path("D:/Trellis"),
    ]
    for c in candidates:
        if c.is_dir():
            return str(c)
    return str(pathlib.Path.home() / "Trellis")


def default_projects_map() -> dict[str, str]:
    projs: dict[str, str] = {}
    detected = _detect_local_unity_project()
    if detected is not None:
        projs[detected.name] = str(detected)
    return projs


@dataclass
class CheckOption:
    key: str
    label: str
    enabled: bool = False
    help_text: str = ""


@dataclass
class ToolSpec:
    id: str
    name: str
    kind: str  # http | stdio | skill_pack | rule | cli
    version: str
    repo_url: str
    schema_tokens: int
    summary: str = ""
    details: str = ""
    when_to_use: str = ""
    latest_version: str = ""
    has_update: bool = False
    release_notes_url: str = ""
    enabled: bool = False
    clients: dict[str, bool] = field(default_factory=lambda: {"AGY": True, "CDX": True, "CLD": False, "CUR": False})
    scope_selectable: bool = True
    project_scope: str = "GLOBAL"
    fixed_location_label: str = ""
    live_location_detail: str = ""
    modes: list[str] = field(default_factory=list)
    mode_index: int = 0
    has_gear: bool = False
    gear_kind: str = "standard"  # standard | skills94
    port: int | None = None
    health_url: str | None = None
    param_label: str = ""
    param_value: str = ""
    param_help: str = ""
    param_arg_flag: str = ""
    param_env_var: str = ""
    vault_key_name: str = ""
    vault_key_required: bool = False
    vault_key_desc: str = ""
    in_workspace: bool = True
    category: str = "coding_dev"
    install_cmd: str = ""
    mcp_server_key: str = ""
    mcp_command: str = ""
    mcp_args: list[str] = field(default_factory=list)
    ai_question_hint: str = ""
    tags: list[str] = field(default_factory=list)
    options: list[CheckOption] = field(default_factory=list)
    last_ping: str = "Disabled"
    last_latency_ms: int = -1
    health_state: str = "off"  # ok | warn | error | idle | off


def build_default_catalog() -> list[ToolSpec]:
    u_proj = _detect_local_unity_project()
    u_path = str(u_proj) if u_proj else ""
    u_parent = str(u_proj.parent) if u_proj else ""
    u_audio = str(u_proj / "Assets" / "Audio") if u_proj else ""
    t_dir = _detect_local_trellis_dir()

    starter_tools = [
        ToolSpec(
            id="blender_skills",
            name="Blender Skills",
            category="game_3d",
            kind="skill_pack",
            version="v1.3.0",
            repo_url="https://github.com/arjun988/blender-skills",
            schema_tokens=len(BLENDER_SKILLS_94) * BLENDER_SKILL_INDEX_TOKENS,
            summary="Library of 94 specialist Blender SKILL.md guides (modeling, UV, materials, lighting, engine export).",
            details="Teaches AI coding agents clean topology, hard-surface rules, PBR shading, lighting, and Unity/Unreal/Godot export standards. Use Configure to enable only the skills needed right now and save context tokens.",
            when_to_use="Enable while creating 3D assets, scenes, or materials in Blender; disable for pure software or web projects.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=True,
            gear_kind="skills94",
            install_cmd="git clone https://github.com/arjun988/blender-skills.git",
            tags=["modeling_3d", "style_3d", "free_local"],
        ),
        ToolSpec(
            id="bla",
            name="BLA (Blind LLM Agents)",
            category="security_qa",
            kind="stdio",
            version="v3.4.3",
            repo_url="https://github.com/qybaihe/bla",
            schema_tokens=3800,
            summary="Protects shipped web apps and bundles against automated AI reverse engineering.",
            details="Adds honey source maps, SHA-256 sibling file sealing, and agent-resistant directives to compiled bundles without slowing down runtime performance.",
            when_to_use="Enable when hardening a production web build; keep disabled during normal local development.",
            enabled=False,
            clients={"AGY": True, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=False,
            install_cmd="npm install -g bla-agents",
            mcp_server_key="bla-agents",
            mcp_command="npx",
            mcp_args=["-y", "bla-agents", "mcp"],
            tags=["security", "web_browser", "free_local"],
        ),
        ToolSpec(
            id="caveman",
            name="Caveman",
            category="ai_memory",
            kind="rule",
            version="v1.4.1",
            repo_url="https://github.com/JuliusBrussee/caveman",
            schema_tokens=200,
            summary="Output-token reduction rule cutting verbose filler by 35% to 75% without reducing code quality.",
            details="Keeps AI responses concise and technical while preserving full code accuracy. Toggling off moves the skill out of active skills; changing mode updates the active compression directive on disk.",
            when_to_use="Safe to keep enabled most of the time. Switch to Lite or disable when writing long-form documentation.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": True, "CUR": True},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=["Lite (-35%)", "Full (-65%)", "Ultra (-75%)"],
            mode_index=1,
            has_gear=True,
            install_cmd="git clone https://github.com/JuliusBrussee/caveman.git",
            tags=["token_saver", "coding_lsp", "free_local"],
        ),
        ToolSpec(
            id="serena",
            name="Serena",
            category="coding_dev",
            kind="http",
            version="v0.9.2",
            repo_url="https://github.com/oraios/serena",
            schema_tokens=4200,
            summary="LSP-powered semantic code navigation and symbol search for large codebases.",
            details="Finds symbol definitions, references, and classes via Language Server Protocol instead of loading entire source files into context, saving tokens and speeding up refactoring.",
            when_to_use="Enable on medium or large codebases (Unity C#, Python, TypeScript); disable for single-file scripts.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=["Read-only (Planning)", "Editing enabled"],
            mode_index=0,
            has_gear=True,
            port=9121,
            param_label="LSP Server Port",
            param_value="9121",
            param_help="Local HTTP port for Serena MCP server (default: 9121).",
            install_cmd="uv tool install serena-agent",
            mcp_server_key="serena",
            tags=["coding_lsp", "token_saver", "desktop_ui"],
            options=[
                CheckOption(
                    "no_dashboard",
                    "Keep web dashboard closed (--open-web-dashboard false)",
                    True,
                    "ON: Passes --open-web-dashboard False and --enable-gui-log-window False when launching Serena.\nOFF: Allows Serena to open its local browser dashboard on launch.",
                ),
            ],
        ),
        ToolSpec(
            id="unity_mcp",
            name="Unity MCP",
            category="game_3d",
            kind="http",
            version="v2.2.0",
            repo_url="https://github.com/CoplayDev/unity-mcp",
            schema_tokens=4600,
            summary="Connects AI agents to a running Unity Editor to inspect and edit scenes, prefabs, materials, and components.",
            details="Communicates over a local HTTP bridge (:8080) with the MCP for Unity Editor package so agents can inspect hierarchies, edit GameObjects, read console errors, and automate scene setup.",
            when_to_use="Enable when Unity Editor is open and you want scene/editor automation; disable when Unity is closed to save ~4.6K schema tokens.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=True,
            port=8080,
            param_label="Unity HTTP Port",
            param_value="8080",
            param_help="Local HTTP port matching the MCP for Unity window inside Unity Editor (default: 8080).",
            install_cmd="uv tool install --python 3.12 mcpforunityserver",
            mcp_server_key="unity-mcp",
            tags=["unity", "automation", "free_local"],
        ),
        ToolSpec(
            id="unity_pipeline",
            name="Unity Pipeline",
            category="game_3d",
            kind="cli",
            version="v0.8.0-exp.1",
            repo_url="https://docs.unity3d.com/",
            schema_tokens=900,
            summary="Fast background C# method-reload, compilation, test execution, and Play verification for Unity 6.",
            details="Uses Unity's pipeline automation CLI to reload modified C# methods without full Domain Reload stalls and capture background camera screenshots.",
            when_to_use="Enable during active C# iteration in Unity 6 projects; disable for non-Unity work.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=True,
            param_label="Unity Project Path",
            param_value=u_path,
            param_help="Root directory of your Unity project (containing Assets and Packages).",
            tags=["unity", "testing_qa", "free_local"],
        ),
        ToolSpec(
            id="renderdoc_mcp",
            name="RenderDoc MCP",
            category="game_3d",
            kind="stdio",
            version="v0.3.2",
            repo_url="https://github.com/Linkingooo/renderdoc-mcp",
            schema_tokens=2900,
            summary="Inspects RenderDoc frame captures (.rdc) for draw calls, HLSL shaders, CBuffers, and SRP Batcher issues.",
            details="Allows AI agents to read real GPU pipeline state, constant buffer values, depth/normal passes, and draw-call bottlenecks directly from .rdc captures.",
            when_to_use="Enable only when debugging graphics, custom shaders (HLSL/URP/HDRP), or draw-call performance.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=True,
            param_label="Default .rdc Folder",
            param_value=u_parent,
            param_help="Default directory where your RenderDoc frame capture (.rdc) files are saved.",
            param_env_var="RENDERDOC_CAPTURE_DIR",
            install_cmd="uvx renderdoc-mcp",
            mcp_server_key="renderdoc-mcp",
            mcp_command="uvx",
            mcp_args=["renderdoc-mcp"],
            tags=["shader_gpu", "unity", "free_local"],
        ),
        ToolSpec(
            id="blender_mcp",
            name="Blender MCP",
            category="game_3d",
            kind="http",
            version="v1.2.4",
            repo_url="https://github.com/ahujasid/blender-mcp",
            schema_tokens=2800,
            summary="Connects AI agents directly to a running Blender session over socket (:9876) for live 3D modeling.",
            details="Runs bpy commands inside an open Blender scene for modeling, UV unwrapping, material assignment, camera/light setup, and optional PolyHaven asset import.",
            when_to_use="Enable while Blender is open and you want live scene manipulation; disable when Blender is closed.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=False,
            fixed_location_label="fixed_blender",
            has_gear=True,
            port=9876,
            param_label="Blender Socket Port",
            param_value="9876",
            param_help="Local TCP port configured in the BlenderMCP add-on panel (default: 9876; passed via BLENDER_PORT when customized).",
            install_cmd="uvx blender-mcp",
            mcp_server_key="blender",
            mcp_command="uvx",
            mcp_args=["blender-mcp"],
            tags=["modeling_3d", "free_local"],
        ),
        ToolSpec(
            id="trellis",
            name="TRELLIS (local GPU)",
            category="game_3d",
            kind="cli",
            version="v1.1.0",
            repo_url="https://github.com/microsoft/TRELLIS",
            schema_tokens=1100,
            summary="Generates 3D .glb meshes locally on your NVIDIA GPU from images or text with zero cloud cost.",
            details="Runs Microsoft TRELLIS locally on GPU. Because model weights use significant VRAM, use Free VRAM in the status bar when you finish generating assets.",
            when_to_use="Enable when generating local 3D meshes; disable and free VRAM when running heavy game engines.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=False,
            fixed_location_label="fixed_local_gpu",
            has_gear=True,
            port=8790,
            health_url="http://127.0.0.1:8790/health",
            param_label="TRELLIS Install Folder",
            param_value=t_dir,
            param_help="Local installation directory containing TRELLIS runtime and model weights.",
            tags=["modeling_3d", "shader_gpu", "free_local"],
        ),
        ToolSpec(
            id="gltf_transform",
            name="glTF-Transform MCP",
            category="game_3d",
            kind="stdio",
            version="v4.0.2",
            repo_url="https://github.com/GeoLibra/3d-asset-processing-mcp",
            schema_tokens=2100,
            summary="Optimizes .glb/.gltf 3D models (decimation, vertex welding, texture resize) without opening Blender.",
            details="Processes high-poly generated or exported meshes to fit game-engine budgets using weld, prune, simplify, and texture downscaling.",
            when_to_use="Enable when preparing 3D assets for import into a game engine; keep disabled otherwise.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=False,
            install_cmd="npm install -g @gltf-transform/cli",
            mcp_server_key="3d-asset-processing",
            mcp_command="npx",
            mcp_args=["-y", "3d-asset-processing-mcp"],
            tags=["modeling_3d", "unity", "free_local"],
        ),
        ToolSpec(
            id="elevenlabs_mcp",
            name="ElevenLabs MCP",
            category="game_3d",
            kind="stdio",
            version="v0.9.1",
            repo_url="https://github.com/elevenlabs/elevenlabs-mcp",
            schema_tokens=2600,
            summary="Generates sound effects (SFX), ambient audio, and voice lines from text prompts.",
            details="Creates game audio, footsteps, UI feedback sounds, ambience, and dialogue via ElevenLabs API. Requires ELEVENLABS_API_KEY in Settings > API Keys.",
            when_to_use="Enable when producing SFX or voice assets; disable afterward to save schema tokens and API credits.",
            enabled=False,
            clients={"AGY": True, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=True,
            param_label="Audio Output Folder",
            param_value=u_audio,
            param_help="Directory passed via ELEVENLABS_MCP_OUTPUT_PATH where generated audio files are saved.",
            param_env_var="ELEVENLABS_MCP_OUTPUT_PATH",
            vault_key_name="ELEVENLABS_API_KEY",
            vault_key_required=True,
            vault_key_desc="ElevenLabs Voice & SFX API key",
            install_cmd="uvx elevenlabs-mcp",
            mcp_server_key="elevenlabs",
            mcp_command="uvx",
            mcp_args=["elevenlabs-mcp"],
            tags=["audio_sfx"],
        ),
        ToolSpec(
            id="meshy",
            name="Meshy MCP",
            category="game_3d",
            kind="stdio",
            version="v0.4.1",
            repo_url="https://github.com/meshyai/meshy-mcp-server",
            schema_tokens=2300,
            summary="Cloud text/image-to-3D generation, PBR retexturing, and clean Quad remeshing.",
            details="Uses the Meshy cloud API for 3D generation, automated PBR texturing, and animation-friendly quad topology. Requires MESHY_API_KEY in Settings > API Keys.",
            when_to_use="Enable only when intentionally spending Meshy cloud credits; keep disabled otherwise.",
            enabled=False,
            clients={"AGY": False, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=False,
            fixed_location_label="fixed_cloud",
            has_gear=True,
            vault_key_name="MESHY_API_KEY",
            vault_key_required=True,
            vault_key_desc="Meshy 3D Cloud API key",
            install_cmd="uvx meshy-mcp",
            mcp_server_key="meshy",
            mcp_command="uvx",
            mcp_args=["meshy-mcp"],
            tags=["modeling_3d", "style_3d"],
        ),
        ToolSpec(
            id="context7",
            name="Context7 Docs MCP",
            category="productivity_docs",
            kind="stdio",
            version="v1.0.8",
            repo_url="https://github.com/upstash/context7",
            schema_tokens=1600,
            summary="Fetches up-to-date official documentation and working API snippets for modern libraries.",
            details="Prevents outdated API hallucinations by pulling live version-specific docs for frameworks like Unity, PySide6, React, Next.js, Tailwind, and Vite. Works without an API key (optional CONTEXT7_API_KEY raises rate limits).",
            when_to_use="Useful across almost any active software project (~1.6K modest schema cost).",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": True, "CUR": True},
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=True,
            vault_key_name="CONTEXT7_API_KEY",
            vault_key_required=False,
            vault_key_desc="Context7 Docs API key (optional)",
            install_cmd="npx -y @upstash/context7-mcp",
            mcp_server_key="context7",
            mcp_command="npx",
            mcp_args=["-y", "@upstash/context7-mcp"],
            tags=["docs_search", "token_saver", "desktop_ui"],
        ),
        ToolSpec(
            id="chrome_devtools",
            name="Chrome DevTools MCP",
            category="web_browser",
            kind="stdio",
            version="v0.18.0",
            repo_url="https://github.com/ChromeDevTools/chrome-devtools-mcp",
            schema_tokens=3400,
            summary="Automates Chrome to inspect console errors, DOM layout, network requests, and Lighthouse performance.",
            details="Drives a live browser instance to verify responsive mobile layouts, Core Web Vitals, SEO metadata, broken links, and interactive UI flows.",
            when_to_use="Enable during web frontend debugging or pre-release Lighthouse/SEO audits; disable for desktop/game work.",
            enabled=False,
            clients={"AGY": True, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            has_gear=True,
            install_cmd="npx -y chrome-devtools-mcp@latest",
            mcp_server_key="chrome-devtools",
            mcp_command="npx",
            mcp_args=["-y", "chrome-devtools-mcp@latest"],
            tags=["web_browser", "testing_qa", "free_local"],
            options=[
                CheckOption(
                    "headless_mode",
                    "Run Chrome headless (--headless)",
                    False,
                    "ON: Appends --headless to chrome-devtools-mcp so checks run without opening a visible window.\nOFF: Opens a visible Chrome window during automation.",
                ),
                CheckOption(
                    "isolated_profile",
                    "Use isolated temporary profile (--isolated)",
                    False,
                    "ON: Appends --isolated so each browser session runs in a clean temporary user profile.\nOFF: Uses Chrome's persistent automation profile.",
                ),
            ],
        ),
    ]
    return starter_tools + build_library_catalog()


def get_default_tool_spec(tool_id: str) -> ToolSpec | None:
    """Return a fresh factory-default ToolSpec for ``tool_id`` (or None for custom repos)."""
    for spec in build_default_catalog():
        if spec.id == tool_id:
            return spec
    return None


# Turkish translations for built-in catalog entries (100% parity with English defaults above)
_TR_TOOL_TEXT: dict[str, dict[str, Any]] = {
    "blender_skills": {
        "summary": "Blender için 94 uzman SKILL.md rehberi kütüphanesi (modelleme, UV, materyal, ışıklandırma, motor dışa aktarımı).",
        "details": "Yapay zeka ajanlarına temiz topoloji, hard-surface, PBR materyal, ışıklandırma ve Unity/Unreal/Godot dışa aktarım standartlarını öğretir. Ayarlar penceresinden yalnızca o an gereken skill'leri seçerek bağlam tokenı tasarruf edebilirsiniz.",
        "when_to_use": "Blender'da 3D modelleme, sahne kurulumu veya materyal hazırlarken açın; yalnızca yazılım/web geliştirirken kapatın.",
    },
    "bla": {
        "summary": "Yayınlanan web uygulamalarını ve paketleri yapay zeka tabanlı tersine mühendisliğe karşı korur.",
        "details": "Derlenmiş çıktılara yanıltıcı kaynak haritaları (Honey SourceMaps), SHA-256 dosya mühürleme ve ajan direnci yönergeleri ekler; çalışma zamanı hızını düşürmez.",
        "when_to_use": "Web uygulamasını canlı yayına (production build) hazırlarken açın; günlük geliştirme sırasında kapalı tutun.",
    },
    "caveman": {
        "summary": "Kod kalitesini düşürmeden gereksiz laf kalabalığını keserek çıktı token tüketimini %35-%75 azaltan kural.",
        "details": "Yapay zeka yanıtlarını teknik, kısa ve doğrudan tutar. Kapatıldığında kural dosyası aktif klasörden çıkarılır; mod değiştirildiğinde diskteki sıkıştırma seviyesi güncellenir.",
        "when_to_use": "Çoğu zaman açık bırakılabilir. Uzun anlatımlı dokümantasyon yazarken Lite moda alabilir veya kapatabilirsiniz.",
        "modes": ["Lite (-35%)", "Full (-65%)", "Ultra (-75%)"],
    },
    "serena": {
        "summary": "Büyük kod tabanları için Dil Sunucusu (LSP) tabanlı sembol ve referans analizi.",
        "details": "Tüm dosyaları bağlama yüklemek yerine Dil Sunucusu üzerinden doğrudan sınıf, fonksiyon ve referansları bulur; token tasarrufu ve hız sağlar.",
        "when_to_use": "Orta ve büyük ölçekli projelerde (Unity C#, Python, TypeScript vb.) açın; tek dosyalık işlerde kapatabilirsiniz.",
        "modes": ["Salt-okunur (Analiz)", "Düzenleme açık"],
        "param_label": "LSP Sunucu Portu",
        "param_help": "Serena yerel HTTP sunucu portu (varsayılan: 9121).",
        "options": {
            "no_dashboard": (
                "Web panelini kapalı tut (--open-web-dashboard false)",
                "AÇIK: Serena başlatılırken --open-web-dashboard False ve --enable-gui-log-window False parametrelerini iletir.\nKAPALI: Başlangıçta yerel izleme sayfasının tarayıcıda açılmasına izin verir.",
            ),
        },
    },
    "unity_mcp": {
        "summary": "Açık Unity Editörüne bağlanarak sahne hiyerarşisi, prefab, materyal ve bileşenleri yönetir.",
        "details": "Unity içindeki yerel HTTP köprüsü (:8080) üzerinden çalışır; yapay zekanın objeleri incelemesini, bileşen düzenlemesini ve konsol hatalarını okumasını sağlar.",
        "when_to_use": "Unity Editör açıkken sahne/editör otomasyonu için açın; Unity kapalıyken ~4.6K şema tokenı harcamaması için kapatın.",
        "param_label": "Unity HTTP Portu",
        "param_help": "Unity Editör içindeki MCP for Unity penceresiyle eşleşen yerel port (varsayılan: 8080).",
    },
    "unity_pipeline": {
        "summary": "Unity 6 için arka planda hızlı C# Method-Reload, derleme, test ve Play doğrulaması.",
        "details": "Tam Domain Reload beklemeleri yerine yalnızca değişen C# metotlarını yenileyip arka planda sahne ekran görüntüsü doğrulaması yapılmasını sağlar.",
        "when_to_use": "Unity 6 projelerinde sık C# iterasyonu yaparken açın; Unity dışı işlerde kapatın.",
        "param_label": "Unity Proje Klasörü",
        "param_help": "İçinde Assets ve Packages bulunan Unity proje kök klasörü.",
    },
    "renderdoc_mcp": {
        "summary": "RenderDoc kare yakalama (.rdc) dosyalarından draw call, HLSL shader, CBuffer ve SRP Batcher analizi yapar.",
        "details": "Yapay zeka ajanlarının tahmin yürütmek yerine gerçek GPU durumunu, Constant Buffer değerlerini ve ara pass dokularını doğrudan .rdc kaydından okumasını sağlar.",
        "when_to_use": "Yalnızca grafik hatası, özel shader (HLSL/URP/HDRP) veya draw-call darboğazı incelerken açın.",
        "param_label": "Varsayılan .rdc Klasörü",
        "param_help": "RenderDoc kare yakalama (.rdc) dosyalarınızın bulunduğu varsayılan klasör.",
    },
    "blender_mcp": {
        "summary": "Açık Blender oturumuna soket (:9876) üzerinden bağlanarak canlı 3D model üretir ve düzenler.",
        "details": "Açık Blender sahnesinde bpy komutları çalıştırarak modelleme, UV açma, materyal atama, kamera/ışık kurulumu ve isteğe bağlı PolyHaven indirmesi yapar.",
        "when_to_use": "Blender açıkken canlı sahne düzenlemesi yaptıracağınız zaman açın; Blender kapalıyken kapalı tutun.",
        "param_label": "Blender Soket Portu",
        "param_help": "Blender içindeki BlenderMCP eklentisinin dinlediği yerel TCP portu (varsayılan: 9876; değiştirildiğinde BLENDER_PORT ile iletilir).",
    },
    "trellis": {
        "summary": "Kendi NVIDIA ekran kartınızla (GPU) görsel veya metinden ücretsiz yerel 3D (.glb) model üretir.",
        "details": "Microsoft TRELLIS modelini yerelde çalıştırır. Model ağırlıkları yüksek VRAM kullandığı için işiniz bittiğinde alt çubuktaki VRAM Boşalt butonunu kullanabilirsiniz.",
        "when_to_use": "Yerel GPU ile 3D model üretirken açın; ağır oyun motorları çalışırken kapatıp VRAM boşaltın.",
        "param_label": "TRELLIS Kurulum Klasörü",
        "param_help": "Yerel TRELLIS çalışma zamanı ve model ağırlıklarının bulunduğu klasör.",
    },
    "gltf_transform": {
        "summary": ".glb/.gltf 3D modellerini Blender açmadan oyun bütçesine göre optimize eder (poligon ve doku küçültme).",
        "details": "Yüksek poligonlu modelleri çift vertex birleştirme (weld), temizleme (prune), sadeleştirme (simplify) ve doku boyut küçültmeyle oyun motoruna hazırlar.",
        "when_to_use": "3D modelleri oyun motoruna aktarmadan önce optimize ederken açın; diğer zamanlarda kapalı tutun.",
    },
    "elevenlabs_mcp": {
        "summary": "Metin komutlarından oyun içi ses efekti (SFX), ambiyans ve karakter seslendirmesi üretir.",
        "details": "Ayak sesi, arayüz sesi, atmosfer ve diyalogları ElevenLabs API üzerinden üretir. Ayarlar > API Anahtarları altından ELEVENLABS_API_KEY girilmesi gerekir.",
        "when_to_use": "Ses efekti veya dublaj üretirken açın; sonrasında kredi ve token tasarrufu için kapatın.",
        "param_label": "Ses Çıktı Klasörü",
        "param_help": "Üretilen ses dosyalarının kaydedileceği klasör (ELEVENLABS_MCP_OUTPUT_PATH ortam değişkeni olarak iletilir).",
        "vault_key_desc": "ElevenLabs Ses & SFX API anahtarı",
    },
    "meshy": {
        "summary": "Bulut üzerinden metin/görselden 3D model üretimi, PBR doku kaplama ve temiz Quad topoloji dönüşümü.",
        "details": "Yerel GPU üretimi uygun olmadığında Meshy bulut API'si ile 3D üretim, otomatik PBR kaplama ve animasyona uygun Quad remesh yapar. MESHY_API_KEY gerektirir.",
        "when_to_use": "Yalnızca bilinçli olarak Meshy bulut kredisi kullanacağınız zaman açın; normalde kapalı tutun.",
        "vault_key_desc": "Meshy 3D Bulut API anahtarı",
    },
    "context7": {
        "summary": "Güncel kütüphane ve framework'ler için canlı resmi doküman ve çalışan API örnekleri çeker.",
        "details": "Unity, PySide6, React, Next.js, Tailwind ve Vite gibi araçların en son sürüm dokümanlarını getirerek eski bilgiyle uydurma kod yazılmasını önler. Anahtarsız ücretsiz çalışır (isteğe bağlı CONTEXT7_API_KEY limit artırır).",
        "when_to_use": "Aktif yazılım geliştirilen neredeyse tüm projelerde açık tutulabilir (~1.6K düşük şema yükü).",
        "vault_key_desc": "Context7 Docs API anahtarı (isteğe bağlı)",
    },
    "chrome_devtools": {
        "summary": "Gerçek Chrome tarayıcısı üzerinden konsol hatalarını, DOM düzenini, ağ isteklerini ve Lighthouse hızını denetler.",
        "details": "Canlı tarayıcıda mobil uyumluluk, Core Web Vitals, SEO meta etiketleri, kırık linkler ve etkileşimli UI akışlarını test eder.",
        "when_to_use": "Web arayüzü ayıklarken veya yayın öncesi Lighthouse/SEO denetiminde açın; masaüstü/oyun projelerinde kapatın.",
        "options": {
            "headless_mode": (
                "Chrome'u arka planda görünmez (--headless) çalıştır",
                "AÇIK: chrome-devtools-mcp komutuna --headless bayrağı ekler; görünür pencere açmadan test eder.\nKAPALI: Otomasyon sırasında canlı Chrome penceresini gösterir.",
            ),
            "isolated_profile": (
                "İzole geçici profil kullan (--isolated)",
                "AÇIK: --isolated bayrağı ekleyerek her oturumu temiz geçici bir Chrome profilinde çalıştırır.\nKAPALI: Kalıcı otomasyon profilini kullanır.",
            ),
        },
    },
}


def _tr_tool_bucket(tool_id: str) -> dict[str, Any]:
    return _TR_TOOL_TEXT.get(tool_id) or _TR_LIBRARY_TEXT.get(tool_id) or {}


def localized_tool_text(tool: ToolSpec, field_name: str, lang: str = "en") -> str:
    if lang == "tr":
        tr_entry = _tr_tool_bucket(tool.id)
        if field_name in tr_entry and isinstance(tr_entry[field_name], str):
            return tr_entry[field_name]
    return str(getattr(tool, field_name, "") or "")


def localized_tool_modes(tool: ToolSpec, lang: str = "en") -> list[str]:
    if lang == "tr":
        tr_entry = _tr_tool_bucket(tool.id)
        if "modes" in tr_entry:
            return list(tr_entry["modes"])
    return list(tool.modes)


def localized_option_text(tool_id: str, opt: CheckOption, lang: str = "en") -> tuple[str, str]:
    if lang == "tr":
        tr_opts = _tr_tool_bucket(tool_id).get("options", {})
        if opt.key in tr_opts:
            return tr_opts[opt.key]
    return opt.label, opt.help_text


_SKILL_DESC_EN: dict[str, str] = {
    "blender-director": "Scene planning, composition, and overall 3D production direction standards.",
    "blender-modeler": "Clean quad topology, edge flow, modifiers, and core 3D modeling standards.",
    "hard-surface": "Mechanical parts, vehicles, bevel/boolean workflows, and clean hard-surface modeling.",
    "prop-artist": "Game-ready interactive props and environmental asset creation standards.",
    "lowpoly-style": "Low-polygon budgets, readable silhouettes, and optimized real-time mesh styling.",
    "psx-horror-style": "PS1/PSX low-res texture, affine feel, and retro horror atmosphere guidelines.",
    "horror-style": "Dark atmosphere, eerie proportions, and tension-driven lighting and materials.",
    "indie-horror-aesthetics": "Weathered textures and grounded indie horror visual language.",
    "uv-workflow": "Seam placement, texel density balancing, and clean UV unwrapping.",
    "materials": "PBR shader node setups (Roughness, Metallic, Normal) and realistic surface rules.",
    "asset-optimization": "Polycount, draw-call, material slot, and memory optimization before engine export.",
    "unity-export": "Unity axis conventions (-Z forward, Y up), scale=1.0, and FBX/GLB export checklist.",
    "unreal-export": "Unreal Engine scale, pivots, UCX collision proxies, and FBX export standards.",
    "godot-export": "Godot Engine glTF/GLB scene, material, and collision export workflow.",
    "export-pipeline": "Asset naming, pivot reset, transform application, and clean export validation.",
    "collision-proxy": "Low-poly invisible collision shells and physics proxy authoring.",
    "lod-pipeline": "Distance-based LOD0/LOD1/LOD2 generation and screen-size validation.",
    "lighting": "Three-point lighting, dramatic shadows, volumetrics, and mood illumination.",
    "rigging": "Armatures, IK/FK constraints, and weight painting for deforming or mechanical assets.",
    "animation": "Keyframes, looping game cycles, timing, and NLA animation standards.",
    "geometry-nodes": "Parametric and procedural asset creation with Blender Geometry Nodes.",
    "sculpting": "High-frequency organic sculpting, multiresolution, and surface detail workflows.",
    "retopology": "Converting high-poly sculpts into clean animation-ready low-poly quad meshes.",
    "texture-workflow": "Normal/AO/curvature baking, texture atlases, and memory-efficient texturing.",
}

_SKILL_DESC_TR: dict[str, str] = {
    "blender-director": "Sahne planlama, kompozisyon ve genel 3D üretim yönetmenliği kurallarını uygular.",
    "blender-modeler": "Temiz dörtgen topoloji, kenar akışı (edge flow) ve temel 3D modelleme standartlarını uygular.",
    "hard-surface": "Metal, mekanik parça, araç ve sert yüzey (bevel/boolean) modelleme kurallarını açar.",
    "prop-artist": "Oyun içi etkileşimli eşya ve çevre objeleri (prop) üretim standartlarını öğretir.",
    "lowpoly-style": "Düşük poligon bütçesi, okunabilir silüet ve performanslı oyun estetiği kurallarını uygular.",
    "psx-horror-style": "PS1/PSX dönemi düşük çözünürlüklü retro korku dokusu ve atmosfer kurallarını açar.",
    "horror-style": "Karanlık atmosfer, gerilimli ışıklandırma ve tekinsiz oran kurallarını verir.",
    "indie-horror-aesthetics": "Bağımsız korku oyunlarına özgü eskitilmiş doku ve sahne dili kurallarını açar.",
    "uv-workflow": "Dikiş izi (seam) gizleme, texel yoğunluğu dengeleme ve temiz UV açma kurallarını öğretir.",
    "materials": "PBR materyal düğümleri (Roughness, Metallic, Normal) ve gerçekçi yüzey kurallarını açar.",
    "asset-optimization": "Oyun motoruna aktarmadan önce poligon, draw-call ve bellek optimizasyonu uygular.",
    "unity-export": "Unity için doğru eksen (-Z ileri / Y yukarı), ölçek (1.0) ve FBX/GLB aktarım kurallarını uygular.",
    "unreal-export": "Unreal Engine uyumlu ölçek, pivot, UCX çarpışma kabuğu ve FBX dışa aktarım kurallarını açar.",
    "godot-export": "Godot Engine uyumlu glTF/GLB sahne, materyal ve çarpışma aktarım kurallarını açar.",
    "export-pipeline": "Varlık isimlendirme, pivot sıfırlama, transform uygulama ve hatasız dışa aktarım kontrol listesini çalıştırır.",
    "collision-proxy": "Oyun motoru fiziği için düşük poligonlu görünmez çarpışma (collider) kabuğu üretimini öğretir.",
    "lod-pipeline": "Uzaklığa göre otomatik detay düşüren LOD0/LOD1/LOD2 seviyelerini üretme kurallarını açar.",
    "lighting": "Üç noktalı ışık, dramatik gölge, hacimsel sis ve sahne aydınlatma kurallarını öğretir.",
    "rigging": "Karakter ve mekanik objeler için kemik (armature), IK/FK ve ağırlık boyama kurallarını açar.",
    "animation": "Anahtar kare, döngüsel oyun animasyonu, zamanlama ve NLA standartlarını uygular.",
    "geometry-nodes": "Blender Geometry Nodes ile parametrik ve prosedürel model üretimi kurallarını açar.",
    "sculpting": "Organik detay ve yüksek poligon heykel (sculpt) iş akışı kurallarını öğretir.",
    "retopology": "Yüksek poligonlu modelleri animasyona uygun temiz düşük poligonlu dörtgen ağa dönüştürür.",
    "texture-workflow": "Normal/AO/curvature haritası pişirme (baking) ve doku optimizasyonu iş akışını açar.",
}


def describe_blender_skill(skill_name: str, lang: str = "en") -> str:
    """Explain the effect of enabling or disabling a Blender skill in English or Turkish."""
    readable = skill_name.replace("-", " ").title()
    if lang == "tr":
        core = _SKILL_DESC_TR.get(skill_name)
        if not core:
            if "horror" in skill_name:
                core = f"'{readable}' korku alt türüne özgü atmosfer, ışık ve yüzey kurallarını uygular."
            elif skill_name.startswith("genre-"):
                core = f"'{readable.replace('Genre ', '')}' oyun türüne uygun kamera açısı, okunabilirlik ve ölçek kurallarını uygular."
            elif "style" in skill_name or "mood" in skill_name:
                core = f"'{readable}' görsel sanat tarzına uygun renk paleti, oran ve gölgelendirme kurallarını açar."
            elif "worlds" in skill_name:
                core = f"'{readable}' çevre tasarımı için mimari, bitki örtüsü ve sahne kurulum kurallarını öğretir."
            elif "artist" in skill_name:
                core = f"'{readable}' uzmanlık alanına ait profesyonel 3D üretim standartlarını uygular."
            else:
                core = f"Blender'da '{readable}' aşaması için uzman kontrol listesi ve üretim kurallarını devreye sokar."
        return (
            f"AÇIK: {core} (~{BLENDER_SKILL_INDEX_TOKENS} indeks tokenı başlangıç yükü).\n"
            f"KAPALI: AI başlangıç indeksine yüklenmez (~{BLENDER_SKILL_INDEX_TOKENS} token tasarruf)."
        )

    core = _SKILL_DESC_EN.get(skill_name)
    if not core:
        if "horror" in skill_name:
            core = f"Applies atmosphere, lighting, and material conventions for the '{readable}' horror sub-genre."
        elif skill_name.startswith("genre-"):
            core = f"Applies readability, camera framing, and asset scale rules tailored for '{readable.replace('Genre ', '')}' games."
        elif "style" in skill_name or "mood" in skill_name:
            core = f"Provides palette, proportion, and shading direction for the '{readable}' visual style."
        elif "worlds" in skill_name:
            core = f"Guides architecture, foliage, and environment layout for '{readable}' worlds."
        elif "artist" in skill_name:
            core = f"Applies specialist 3D production standards for '{readable}' assets."
        else:
            core = f"Enables specialist production guidelines and checklists for '{readable}' in Blender."
    return (
        f"ON: {core} (~{BLENDER_SKILL_INDEX_TOKENS} index tokens startup load).\n"
        f"OFF: Excluded from startup skill index (~{BLENDER_SKILL_INDEX_TOKENS} tokens saved)."
    )


PROFILES: dict[str, dict[str, Any]] = {
    "desktop_coding": {
        "title_key": "prof_desktop_coding_title",
        "desc_key": "prof_desktop_coding_desc",
        "enable": {"serena", "context7", "caveman"},
        "tags": ["coding_lsp", "desktop_ui"],
    },
    "unity_shader": {
        "title_key": "prof_unity_shader_title",
        "desc_key": "prof_unity_shader_desc",
        "enable": {"unity_mcp", "unity_pipeline", "renderdoc_mcp", "serena", "context7", "caveman"},
        "tags": ["unity", "shader_gpu"],
    },
    "modeling_3d": {
        "title_key": "prof_modeling_3d_title",
        "desc_key": "prof_modeling_3d_desc",
        "enable": {"blender_mcp", "blender_skills", "trellis", "gltf_transform", "elevenlabs_mcp", "caveman"},
        "tags": ["modeling_3d", "style_3d"],
    },
    "web_security": {
        "title_key": "prof_web_security_title",
        "desc_key": "prof_web_security_desc",
        "enable": {"chrome_devtools", "bla", "serena", "context7", "caveman"},
        "tags": ["web_browser", "security"],
    },
    "token_saver_only": {
        "title_key": "prof_token_saver_only_title",
        "desc_key": "prof_token_saver_only_desc",
        "enable": {"caveman"},
        "tags": ["token_saver"],
    },
}


def profile_title(profile_key: str, lang: str = "en") -> str:
    info = PROFILES.get(profile_key)
    if not info:
        return profile_key
    return tr(lang, info["title_key"])


def profile_desc(profile_key: str, lang: str = "en") -> str:
    info = PROFILES.get(profile_key)
    if not info:
        return ""
    return tr(lang, info["desc_key"])
