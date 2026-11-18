"""Built-in tool catalog, 94 Blender skills, project scopes, and starter profiles (100% EN & TR, emoji-free)."""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any

from .i18n import tr

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
    vault_key_name: str = ""
    install_cmd: str = ""
    mcp_server_key: str = ""
    mcp_command: str = ""
    mcp_args: list[str] = field(default_factory=list)
    ai_question_hint: str = ""
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

    return [
        ToolSpec(
            id="blender_skills",
            name="Blender Skills",
            kind="skill_pack",
            version="v1.3.0",
            repo_url="https://github.com/arjun988/blender-skills",
            schema_tokens=33000,
            summary="Library of 94 specialist Blender SKILL.md guides (modeling, UV, materials, lighting, engine export).",
            details="Teaches AI coding agents clean topology, hard-surface rules, PBR shading, lighting, and Unity/Unreal/Godot export standards. Use Configure to enable only the skills needed right now and save tens of thousands of tokens.",
            when_to_use="Enable while creating 3D assets, scenes, or materials in Blender; disable for pure software or web projects.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=[],
            has_gear=True,
            gear_kind="skills94",
            install_cmd="git clone https://github.com/arjun988/blender-skills.git",
            ai_question_hint="For my current 3D asset task, which of the 94 Blender skills should stay enabled for best quality with minimal token cost?",
        ),
        ToolSpec(
            id="bla",
            name="BLA (Blind LLM Agents)",
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
            modes=["Standard", "Maximum (Bankrupt)", "Lint Only"],
            mode_index=1,
            has_gear=True,
            param_label="Build Output Folder",
            param_value="dist/",
            param_help="Target compiled build directory (e.g. dist/, build/, out/). Source files remain untouched.",
            install_cmd="npm install -g bla-agents",
            mcp_server_key="bla-agents",
            mcp_command="npx",
            mcp_args=["-y", "bla-agents", "mcp"],
            ai_question_hint="Which BLA protection options should I enable before deploying a production web bundle without impacting runtime speed?",
            options=[
                CheckOption(
                    "honey_sourcemaps",
                    "Generate VLQ v3 Honey SourceMaps (enableHoneySourceMaps)",
                    True,
                    "ON: Replaces real source maps with decoy source maps to mislead automated code scrapers without affecting runtime speed.\nOFF: Relies only on standard minification.",
                ),
                CheckOption(
                    "self_seal",
                    "SHA-256 sibling file sealing (--self-seal)",
                    True,
                    "ON: Seals JS/CSS output files with SHA-256 integrity hashes to detect tampering.\nOFF: Skips cross-file integrity sealing.",
                ),
                CheckOption(
                    "llm_directives",
                    "Aggressive LLM counter-directives (--llm-directives)",
                    False,
                    "ON: Embeds counter-analysis directives in built bundles (slightly increases bundle size).\nOFF: Produces a leaner output bundle.",
                ),
                CheckOption(
                    "signed_manifest",
                    "Write signed audit manifest (.bla-manifest.json)",
                    False,
                    "ON: Writes a cryptographic file manifest (.bla-manifest.json) to the build folder.\nOFF: No extra manifest file is written.",
                ),
            ],
        ),
        ToolSpec(
            id="caveman",
            name="Caveman",
            kind="rule",
            version="v1.4.1",
            repo_url="https://github.com/JuliusBrussee/caveman",
            schema_tokens=200,
            summary="Output-token reduction rule cutting verbose filler by 35% to 75% without reducing code quality.",
            details="Keeps AI responses concise and technical while preserving full code accuracy. Minimal schema footprint (~200 tokens) across all AI clients.",
            when_to_use="Safe to keep enabled most of the time. Switch to Lite or disable when writing long-form documentation.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": True, "CUR": True},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=["Lite (-35%)", "Full (-65%)", "Ultra (-75%)", "Wenyan"],
            mode_index=1,
            has_gear=False,
            install_cmd="git clone https://github.com/JuliusBrussee/caveman.git",
        ),
        ToolSpec(
            id="serena",
            name="Serena",
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
            modes=["Read-only", "Editing enabled"],
            mode_index=0,
            has_gear=True,
            port=9121,
            param_label="LSP Server Port",
            param_value="9121",
            param_help="Local HTTP port for Serena MCP server (default: 9121).",
            install_cmd="uv tool install serena-agent",
            mcp_server_key="serena",
            ai_question_hint="How should I configure Serena LSP for safe, low-token symbol navigation on a large codebase?",
            options=[
                CheckOption(
                    "read_only",
                    "Read-only analysis mode (--read-only)",
                    True,
                    "ON: Serena searches and inspects symbols without directly editing files.\nOFF: Enables symbol rename and direct code-editing tools.",
                ),
                CheckOption(
                    "shell_allow",
                    "Allow shell command execution",
                    False,
                    "ON: Permits Serena to execute terminal commands directly.\nOFF: Keeps shell execution restricted to your main AI client (recommended).",
                ),
                CheckOption(
                    "no_dashboard",
                    "Keep web dashboard closed (--open-web-dashboard false)",
                    True,
                    "ON: Prevents Serena from opening a browser tab automatically on startup.\nOFF: Opens the local monitoring page on launch.",
                ),
            ],
        ),
        ToolSpec(
            id="unity_mcp",
            name="Unity MCP",
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
            modes=[],
            has_gear=True,
            port=8080,
            param_label="Unity HTTP Port",
            param_value="8080",
            param_help="Local HTTP port matching the MCP for Unity window inside Unity Editor (default: 8080).",
            install_cmd="uv tool install --python 3.12 mcpforunityserver",
            mcp_server_key="unity-mcp",
            ai_question_hint="Are these Unity MCP permissions optimal for safe scene editing and minimal compile stalls?",
            options=[
                CheckOption(
                    "allow_play",
                    "Allow Play Mode and C# script editing",
                    True,
                    "ON: Agents can edit C# scripts and enter Play Mode to verify changes.\nOFF: Restricts actions to scene inspection.",
                ),
                CheckOption(
                    "no_focus_steal",
                    "Prevent Unity window focus stealing",
                    True,
                    "ON: Keeps Unity in the background while automated commands run.\nOFF: Unity Editor may pop to the foreground during operations.",
                ),
                CheckOption(
                    "auto_save_scene",
                    "Auto-save scene after changes",
                    False,
                    "ON: Automatically saves the active .unity scene after every edit.\nOFF: Lets you review changes before pressing Ctrl+S (safer).",
                ),
            ],
        ),
        ToolSpec(
            id="unity_pipeline",
            name="Unity Pipeline",
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
            modes=["Method-Reload (Fast)", "Full Compile + Test"],
            mode_index=0,
            has_gear=True,
            param_label="Unity Project Path",
            param_value=u_path,
            param_help="Root directory of your Unity project (containing Assets and Packages).",
            ai_question_hint="How should I pair Unity Pipeline CLI with Unity MCP for fast focus-free C# iteration?",
            options=[
                CheckOption(
                    "method_reload",
                    "Prefer fast Method-Reload over full Domain Reload",
                    True,
                    "ON: Hot-patches small C# method edits in memory instead of waiting for a full Domain Reload.\nOFF: Runs standard full compilation and Domain Reload.",
                ),
                CheckOption(
                    "bg_screenshot",
                    "Enable background scene screenshot verification",
                    True,
                    "ON: Lets the agent capture scene views in the background to visually verify edits.\nOFF: Relies solely on compilation and console logs.",
                ),
            ],
        ),
        ToolSpec(
            id="renderdoc_mcp",
            name="RenderDoc MCP",
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
            modes=[],
            has_gear=True,
            param_label="Default .rdc Folder",
            param_value=u_parent,
            param_help="Default directory where your RenderDoc frame capture (.rdc) files are saved.",
            install_cmd="uvx renderdoc-mcp",
            mcp_server_key="renderdoc-mcp",
            mcp_command="uvx",
            mcp_args=["renderdoc-mcp"],
            ai_question_hint="Which analysis options should be active when inspecting HLSL/URP shader captures in RenderDoc?",
            options=[
                CheckOption(
                    "cbuffer_dump",
                    "Dump Constant Buffer values",
                    True,
                    "ON: Reads numeric CBuffer inputs bound to each draw call to diagnose material/lighting bugs.\nOFF: Shows high-level draw call sequence only.",
                ),
                CheckOption(
                    "srp_batch_check",
                    "Report SRP Batcher breaks",
                    True,
                    "ON: Identifies objects and shader properties breaking Unity SRP Batcher compatibility.\nOFF: Skips SRP Batcher checks.",
                ),
                CheckOption(
                    "depthnormals_pass",
                    "Inspect DepthNormals / auxiliary passes",
                    True,
                    "ON: Inspects intermediate DepthNormals textures used by SSAO and post-processing.\nOFF: Skips auxiliary pass inspection.",
                ),
            ],
        ),
        ToolSpec(
            id="blender_mcp",
            name="Blender MCP",
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
            modes=[],
            has_gear=True,
            port=9876,
            param_label="Blender Socket Port",
            param_value="9876",
            param_help="Local TCP port configured in the BlenderMCP add-on panel (default: 9876).",
            install_cmd="uvx blender-mcp",
            mcp_server_key="blender",
            mcp_command="uvx",
            mcp_args=["blender-mcp"],
            ai_question_hint="What Blender MCP permissions are recommended for safe 3D modeling and FBX/GLB export?",
            options=[
                CheckOption(
                    "exec_python",
                    "Allow Python (bpy) script execution in Blender",
                    True,
                    "ON: Allows agents to execute bpy scripts to create/edit meshes, UVs, and materials.\nOFF: Restricts the bridge to read-only scene inspection.",
                ),
                CheckOption(
                    "polyhaven",
                    "Enable PolyHaven CC0 asset bridge",
                    False,
                    "ON: Permits downloading CC0 PBR textures, HDRIs, and models from PolyHaven.\nOFF: Uses local or procedural assets only.",
                ),
            ],
        ),
        ToolSpec(
            id="trellis",
            name="TRELLIS (local GPU)",
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
            modes=["Balanced (1024px)", "Fast Preview (512px)", "High Quality (2048px)"],
            mode_index=0,
            has_gear=True,
            port=8790,
            health_url="http://127.0.0.1:8790/health",
            param_label="TRELLIS Install Folder",
            param_value=t_dir,
            param_help="Local installation directory containing TRELLIS runtime and model weights.",
            ai_question_hint="How should I configure TRELLIS to avoid VRAM contention while Unity or Blender is open?",
            options=[
                CheckOption(
                    "idle_vram_free",
                    "Auto-sleep server after 30 min idle to free VRAM",
                    True,
                    "ON: Stops the local GPU server after 30 minutes of inactivity to release 6-10 GB of VRAM.\nOFF: Keeps weights loaded until you click Free VRAM.",
                ),
                CheckOption(
                    "export_glb",
                    "Use .glb as default output format",
                    True,
                    "ON: Exports self-contained .glb files with embedded PBR textures ready for Unity/Blender.\nOFF: Keeps raw separate mesh/texture outputs.",
                ),
            ],
        ),
        ToolSpec(
            id="gltf_transform",
            name="glTF-Transform MCP",
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
            modes=["Game-ready (1024px)", "Mobile / Low (512px)", "Lossless cleanup"],
            mode_index=0,
            has_gear=True,
            param_label="Max Texture Size (px)",
            param_value="1024",
            param_help="Maximum texture resolution when downscaling 2K/4K textures (e.g. 1024 for hero props, 512 for small props).",
            install_cmd="npm install -g @gltf-transform/cli",
            mcp_server_key="3d-asset-processing",
            mcp_command="npx",
            mcp_args=["-y", "3d-asset-processing-mcp"],
            ai_question_hint="Which mesh and texture optimization steps should I keep enabled for game-ready 3D props?",
            options=[
                CheckOption(
                    "weld_dedup",
                    "Weld duplicate vertices & prune unused nodes",
                    True,
                    "ON: Welds overlapping vertices and removes unused materials/channels.\nOFF: Leaves raw mesh buffers unchanged.",
                ),
                CheckOption(
                    "simplify_mesh",
                    "Simplify triangle count while preserving silhouette",
                    True,
                    "ON: Reduces excessive polygon density for real-time engine budgets.\nOFF: Keeps original triangle count and resizes textures only.",
                ),
                CheckOption(
                    "draco_meshopt",
                    "Apply meshopt / geometry compression",
                    False,
                    "ON: Shrinks file size by 60-80% for WebGL or streaming scenes.\nOFF: Outputs standard uncompressed .glb for broad importer compatibility.",
                ),
            ],
        ),
        ToolSpec(
            id="elevenlabs_mcp",
            name="ElevenLabs MCP",
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
            modes=["Sound Effects (SFX)", "Voice & Dialogue"],
            mode_index=0,
            has_gear=True,
            param_label="Audio Output Folder",
            param_value=u_audio,
            param_help="Directory where generated audio files are saved (e.g. Assets/Audio).",
            vault_key_name="ELEVENLABS_API_KEY",
            install_cmd="uvx elevenlabs-mcp",
            mcp_server_key="elevenlabs",
            mcp_command="uvx",
            mcp_args=["elevenlabs-mcp"],
            ai_question_hint="What ElevenLabs MCP settings prevent unnecessary credit spend while producing game SFX?",
            options=[
                CheckOption(
                    "confirm_credit",
                    "Confirm estimated credit usage before generation",
                    True,
                    "ON: Displays duration and estimated credit cost for approval before generating.\nOFF: Generates audio immediately without confirmation.",
                ),
                CheckOption(
                    "auto_wav_ogg",
                    "Save high-quality game-ready audio format",
                    True,
                    "ON: Outputs clean high-bitrate audio suitable for game engines.\nOFF: Uses smaller compressed web mp3 output.",
                ),
            ],
        ),
        ToolSpec(
            id="meshy",
            name="Meshy MCP",
            kind="stdio",
            version="v0.4.1",
            repo_url="https://github.com/meshyai/meshy-mcp-server",
            schema_tokens=2300,
            summary="Cloud text/image-to-3D generation, PBR retexturing, and clean Quad remeshing.",
            details="Uses the Meshy cloud API for 3D generation, automated PBR texturing, and animation-friendly quad topology when local GPU generation isn't suitable.",
            when_to_use="Enable only when intentionally spending Meshy cloud credits; keep disabled otherwise.",
            enabled=False,
            clients={"AGY": False, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=False,
            fixed_location_label="fixed_cloud",
            modes=["Draft (Low Credit)", "Standard Quad", "High PBR"],
            mode_index=0,
            has_gear=True,
            param_label="Target Polycount Limit",
            param_value="10000",
            param_help="Maximum target polygon budget for generated Meshy 3D models.",
            vault_key_name="MESHY_API_KEY",
            install_cmd="uvx meshy-mcp",
            mcp_server_key="meshy",
            mcp_command="uvx",
            mcp_args=["meshy-mcp"],
            ai_question_hint="When should I enable Meshy cloud 3D generation alongside local GPU tools?",
            options=[
                CheckOption(
                    "confirm_paid",
                    "Require confirmation before spending cloud credits",
                    True,
                    "ON: Asks for confirmation before running paid generation or retexture jobs.\nOFF: Submits cloud generation jobs immediately.",
                ),
                CheckOption(
                    "quad_remesh",
                    "Request clean Quad topology",
                    True,
                    "ON: Produces clean quad topology that is easier to rig and edit in Blender.\nOFF: Downloads raw triangle meshes.",
                ),
            ],
        ),
        ToolSpec(
            id="context7",
            name="Context7 Docs MCP",
            kind="stdio",
            version="v1.0.8",
            repo_url="https://github.com/upstash/context7",
            schema_tokens=1600,
            summary="Fetches up-to-date official documentation and working API snippets for modern libraries.",
            details="Prevents outdated API hallucinations by pulling live version-specific docs for frameworks like Unity, PySide6, React, Next.js, Tailwind, and Vite.",
            when_to_use="Useful across almost any active software project (~1.6K modest schema cost).",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": True, "CUR": True},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=[],
            has_gear=True,
            param_label="Priority Libraries",
            param_value="",
            param_help="Optional comma-separated list of frameworks you use most (e.g. Unity 6, PySide6, React).",
            vault_key_name="CONTEXT7_API_KEY",
            install_cmd="npx -y @upstash/context7-mcp",
            mcp_server_key="context7",
            mcp_command="npx",
            mcp_args=["-y", "@upstash/context7-mcp"],
            ai_question_hint="How should I tune Context7 so documentation lookups stay concise and token-efficient?",
            options=[
                CheckOption(
                    "concise_snippets",
                    "Prefer concise code snippets over full pages",
                    True,
                    "ON: Returns targeted API signatures and concise examples to conserve context tokens.\nOFF: Pulls longer full documentation pages.",
                ),
            ],
        ),
        ToolSpec(
            id="chrome_devtools",
            name="Chrome DevTools MCP",
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
            modes=["SEO & Lighthouse Audit", "Full Browser Automation"],
            mode_index=0,
            has_gear=True,
            param_label="Target Site URL",
            param_value="http://localhost:3000",
            param_help="Default local or staging URL inspected by Chrome DevTools / Lighthouse.",
            install_cmd="npx -y chrome-devtools-mcp@latest",
            mcp_server_key="chrome-devtools",
            mcp_command="npx",
            mcp_args=["-y", "chrome-devtools-mcp@latest"],
            ai_question_hint="Which Chrome DevTools MCP options are best for pre-release responsive and Lighthouse audits?",
            options=[
                CheckOption(
                    "mobile_emulation",
                    "Test mobile viewport & responsive layout",
                    True,
                    "ON: Verifies mobile screen sizes, touch targets, and overflow issues.\nOFF: Audits desktop viewport only.",
                ),
                CheckOption(
                    "lighthouse_vitals",
                    "Run Core Web Vitals & Lighthouse audit",
                    True,
                    "ON: Measures LCP/CLS performance, SEO, and accessibility scores.\nOFF: Performs faster DOM and console checks without Lighthouse.",
                ),
                CheckOption(
                    "headless_mode",
                    "Run Chrome headless in background",
                    False,
                    "ON: Runs checks silently without opening a visible browser window.\nOFF: Shows the live Chrome window during automated clicks.",
                ),
            ],
        ),
    ]


# Turkish translations for built-in catalog entries (100% parity with English defaults above)
_TR_TOOL_TEXT: dict[str, dict[str, Any]] = {
    "blender_skills": {
        "summary": "Blender için 94 uzman SKILL.md rehberi kütüphanesi (modelleme, UV, materyal, ışıklandırma, motor dışa aktarımı).",
        "details": "Yapay zeka ajanlarına temiz topoloji, hard-surface, PBR materyal, ışıklandırma ve Unity/Unreal/Godot dışa aktarım standartlarını öğretir. Ayarlar penceresinden yalnızca o an gereken skill'leri seçerek on binlerce token tasarruf edebilirsiniz.",
        "when_to_use": "Blender'da 3D modelleme, sahne kurulumu veya materyal hazırlarken açın; yalnızca yazılım/web geliştirirken kapatın.",
        "ai_question_hint": "Üzerinde çalıştığım 3D varlık görevi için 94 Blender skill içinden hangilerini açık bırakmak kalite ve token tasarrufu açısından en doğrusu olur?",
    },
    "bla": {
        "summary": "Yayınlanan web uygulamalarını ve paketleri yapay zeka tabanlı tersine mühendisliğe karşı korur.",
        "details": "Derlenmiş çıktılara yanıltıcı kaynak haritaları (Honey SourceMaps), SHA-256 dosya mühürleme ve ajan direnci yönergeleri ekler; çalışma zamanı hızını düşürmez.",
        "when_to_use": "Web uygulamasını canlı yayına (production build) hazırlarken açın; günlük geliştirme sırasında kapalı tutun.",
        "modes": ["Standart", "Maksimum (Bankrupt)", "Sadece Lint"],
        "param_label": "Derleme Çıktı Klasörü",
        "param_help": "Korumanın uygulanacağı derlenmiş build klasörü (örn: dist/, build/, out/). Kaynak dosyalara dokunmaz.",
        "ai_question_hint": "Web paketini yayına almadan önce çalışma hızını bozmadan hangi BLA koruma seçeneklerini açmalıyım?",
        "options": {
            "honey_sourcemaps": (
                "VLQ v3 Honey SourceMap üret (enableHoneySourceMaps)",
                "AÇIK: Gerçek kaynak haritası yerine yanıltıcı sahte harita üreterek otomatik kod tarayıcıları şaşırtır; hız kaybı yaratmaz.\nKAPALI: Yalnızca standart küçültme (minification) kullanılır.",
            ),
            "self_seal": (
                "SHA-256 kardeş dosya mühürleme (--self-seal)",
                "AÇIK: JS/CSS çıktılarını SHA-256 özetiyle mühürleyerek dışarıdan müdahaleyi yakalar.\nKAPALI: Dosyalar arası bütünlük mührü eklenmez.",
            ),
            "llm_directives": (
                "Agresif LLM karşı yönergeleri (--llm-directives)",
                "AÇIK: Derlenmiş paketlere analiz zorlaştıran karşı yönergeler gömer (paket boyutunu hafifçe artırabilir).\nKAPALI: Daha hafif çıktı paketi üretir.",
            ),
            "signed_manifest": (
                "İmzalı denetim manifesti yaz (.bla-manifest.json)",
                "AÇIK: Derleme klasörüne kriptografik dosya manifesti (.bla-manifest.json) yazar.\nKAPALI: Ek manifest dosyası oluşturulmaz.",
            ),
        },
    },
    "caveman": {
        "summary": "Kod kalitesini düşürmeden gereksiz laf kalabalığını keserek çıktı token tüketimini %35-%75 azaltan kural.",
        "details": "Yapay zeka yanıtlarını teknik, kısa ve doğrudan tutar. Şema yükü çok düşüktür (~200 token) ve tüm AI istemcilerinde çalışır.",
        "when_to_use": "Çoğu zaman açık bırakılabilir. Uzun anlatımlı dokümantasyon yazarken Lite moda alabilir veya kapatabilirsiniz.",
        "modes": ["Lite (-35%)", "Full (-65%)", "Ultra (-75%)", "Wenyan"],
    },
    "serena": {
        "summary": "Büyük kod tabanları için Dil Sunucusu (LSP) tabanlı sembol ve referans analizi.",
        "details": "Tüm dosyaları bağlama yüklemek yerine Dil Sunucusu üzerinden doğrudan sınıf, fonksiyon ve referansları bulur; token tasarrufu ve hız sağlar.",
        "when_to_use": "Orta ve büyük ölçekli projelerde (Unity C#, Python, TypeScript vb.) açın; tek dosyalık işlerde kapatabilirsiniz.",
        "modes": ["Salt-okunur", "Düzenleme açık"],
        "param_label": "LSP Sunucu Portu",
        "param_help": "Serena yerel HTTP sunucu portu (varsayılan: 9121).",
        "ai_question_hint": "Büyük bir kod tabanında düşük token tüketimiyle güvenli sembol analizi için Serena ayarlarım nasıl olmalı?",
        "options": {
            "read_only": (
                "Salt-okunur analiz modu (--read-only)",
                "AÇIK: Serena kodunuzu yalnızca okur ve sembol arar; dosyaları doğrudan değiştirmez.\nKAPALI: Sembol yeniden adlandırma ve doğrudan kod düzenleme araçları açılır.",
            ),
            "shell_allow": (
                "Shell komutu çalıştırma izni",
                "AÇIK: Serena'nın doğrudan terminal komutu çalıştırmasına izin verir.\nKAPALI: Komut çalıştırma yetkisi ana AI istemcinizde kalır (önerilen).",
            ),
            "no_dashboard": (
                "Web panelini kapalı tut (--open-web-dashboard false)",
                "AÇIK: Serena açıldığında otomatik tarayıcı sekmesi açılmasını engeller.\nKAPALI: Başlangıçta yerel izleme sayfası açılır.",
            ),
        },
    },
    "unity_mcp": {
        "summary": "Açık Unity Editörüne bağlanarak sahne hiyerarşisi, prefab, materyal ve bileşenleri yönetir.",
        "details": "Unity içindeki yerel HTTP köprüsü (:8080) üzerinden çalışır; yapay zekanın objeleri incelemesini, bileşen düzenlemesini ve konsol hatalarını okumasını sağlar.",
        "when_to_use": "Unity Editör açıkken sahne/editör otomasyonu için açın; Unity kapalıyken ~4.6K şema tokenı harcamaması için kapatın.",
        "param_label": "Unity HTTP Portu",
        "param_help": "Unity Editör içindeki MCP for Unity penceresiyle eşleşen yerel port (varsayılan: 8080).",
        "ai_question_hint": "Güvenli sahne düzenleme ve minimum derleme beklemesi için bu Unity MCP izinleri uygun mu?",
        "options": {
            "allow_play": (
                "Play Mode ve C# script düzenleme izni",
                "AÇIK: Ajanlar C# scriptlerini düzenleyebilir ve Play Mode'a geçip test edebilir.\nKAPALI: İşlemler sahne incelemesiyle sınırlanır.",
            ),
            "no_focus_steal": (
                "Unity penceresinin odak çalmasını engelle",
                "AÇIK: Otomasyon komutları çalışırken Unity penceresi öne fırlamaz.\nKAPALI: İşlemler sırasında Unity öne geçip klavye/fare odağını alabilir.",
            ),
            "auto_save_scene": (
                "Değişiklik sonrası sahneyi otomatik kaydet",
                "AÇIK: Her değişiklikten sonra aktif .unity sahnesi otomatik kaydedilir.\nKAPALI: Ctrl+S yapmadan önce değişiklikleri gözden geçirmenizi sağlar (daha güvenli).",
            ),
        },
    },
    "unity_pipeline": {
        "summary": "Unity 6 için arka planda hızlı C# Method-Reload, derleme, test ve Play doğrulaması.",
        "details": "Tam Domain Reload beklemeleri yerine yalnızca değişen C# metotlarını yenileyip arka planda sahne ekran görüntüsü doğrulaması yapılmasını sağlar.",
        "when_to_use": "Unity 6 projelerinde sık C# iterasyonu yaparken açın; Unity dışı işlerde kapatın.",
        "modes": ["Method-Reload (Hızlı)", "Tam Derleme + Test"],
        "param_label": "Unity Proje Klasörü",
        "param_help": "İçinde Assets ve Packages bulunan Unity proje kök klasörü.",
        "ai_question_hint": "Odak çalmadan hızlı C# iterasyonu için Unity Pipeline CLI ile Unity MCP'yi nasıl birlikte kullanmalıyım?",
        "options": {
            "method_reload": (
                "Tam Domain Reload yerine hızlı Method-Reload kullan",
                "AÇIK: Küçük C# metot değişikliklerini bellekte anında yeniler.\nKAPALI: Her değişiklikte standart tam derleme ve Domain Reload beklenir.",
            ),
            "bg_screenshot": (
                "Arka planda sahne ekran görüntüsü doğrulaması",
                "AÇIK: Ajanın görsel değişiklikleri arka planda ekran görüntüsü alarak doğrulamasına izin verir.\nKAPALI: Yalnızca derleme ve konsol çıktılarına bakılır.",
            ),
        },
    },
    "renderdoc_mcp": {
        "summary": "RenderDoc kare yakalama (.rdc) dosyalarından draw call, HLSL shader, CBuffer ve SRP Batcher analizi yapar.",
        "details": "Yapay zeka ajanlarının tahmin yürütmek yerine gerçek GPU durumunu, Constant Buffer değerlerini ve ara pass dokularını doğrudan .rdc kaydından okumasını sağlar.",
        "when_to_use": "Yalnızca grafik hatası, özel shader (HLSL/URP/HDRP) veya draw-call darboğazı incelerken açın.",
        "param_label": "Varsayılan .rdc Klasörü",
        "param_help": "RenderDoc kare yakalama (.rdc) dosyalarınızın bulunduğu varsayılan klasör.",
        "ai_question_hint": "RenderDoc ile HLSL/URP shader kare yakalaması incelerken hangi analiz seçenekleri açık olmalı?",
        "options": {
            "cbuffer_dump": (
                "Constant Buffer değerlerini oku",
                "AÇIK: Draw call anında GPU'ya giden gerçek sayısal CBuffer değerlerini okuyarak materyal/ışık hatalarını gösterir.\nKAPALI: Yalnızca genel draw call sırası listelenir.",
            ),
            "srp_batch_check": (
                "SRP Batcher kırılma nedenlerini raporla",
                "AÇIK: Unity URP/HDRP sahnelerinde SRP Batcher'ı kıran obje ve shader özelliklerini tespit eder.\nKAPALI: SRP Batcher denetimi atlanır.",
            ),
            "depthnormals_pass": (
                "DepthNormals / yardımcı pass çıktılarını denetle",
                "AÇIK: SSAO ve post-processing efektlerinin kullandığı ara DepthNormals dokularını inceler.\nKAPALI: Yardımcı pass incelemesi atlanır.",
            ),
        },
    },
    "blender_mcp": {
        "summary": "Açık Blender oturumuna soket (:9876) üzerinden bağlanarak canlı 3D model üretir ve düzenler.",
        "details": "Açık Blender sahnesinde bpy komutları çalıştırarak modelleme, UV açma, materyal atama, kamera/ışık kurulumu ve isteğe bağlı PolyHaven indirmesi yapar.",
        "when_to_use": "Blender açıkken canlı sahne düzenlemesi yaptıracağınız zaman açın; Blender kapalıyken kapalı tutun.",
        "param_label": "Blender Soket Portu",
        "param_help": "Blender içindeki BlenderMCP eklentisinin dinlediği yerel TCP portu (varsayılan: 9876).",
        "ai_question_hint": "Güvenli 3D modelleme ve FBX/GLB dışa aktarımı için hangi Blender MCP izinleri önerilir?",
        "options": {
            "exec_python": (
                "Blender içinde Python (bpy) çalıştırma izni",
                "AÇIK: Ajanlar bpy scriptleriyle mesh, UV ve materyal oluşturup düzenleyebilir.\nKAPALI: Köprü yalnızca salt-okunur sahne incelemesi yapar.",
            ),
            "polyhaven": (
                "PolyHaven CC0 varlık köprüsünü aç",
                "AÇIK: PolyHaven kütüphanesinden telifsiz PBR doku, HDRI ve model indirilmesine izin verir.\nKAPALI: Yalnızca yerel veya prosedürel materyaller kullanılır.",
            ),
        },
    },
    "trellis": {
        "summary": "Kendi NVIDIA ekran kartınızla (GPU) görsel veya metinden ücretsiz yerel 3D (.glb) model üretir.",
        "details": "Microsoft TRELLIS modelini yerelde çalıştırır. Model ağırlıkları yüksek VRAM kullandığı için işiniz bittiğinde alt çubuktaki VRAM Boşalt butonunu kullanabilirsiniz.",
        "when_to_use": "Yerel GPU ile 3D model üretirken açın; ağır oyun motorları çalışırken kapatıp VRAM boşaltın.",
        "modes": ["Dengeli (1024px)", "Hızlı Önizleme (512px)", "Yüksek Kalite (2048px)"],
        "param_label": "TRELLIS Kurulum Klasörü",
        "param_help": "Yerel TRELLIS çalışma zamanı ve model ağırlıklarının bulunduğu klasör.",
        "ai_question_hint": "Unity veya Blender açıkken VRAM çakışması yaşamadan TRELLIS ayarlarımı nasıl yapmalıyım?",
        "options": {
            "idle_vram_free": (
                "30 dk boşta kalırsa sunucuyu uyutup VRAM boşalt",
                "AÇIK: 30 dakika hareketsizlikte yerel GPU sunucusunu durdurarak 6-10 GB VRAM'i geri verir.\nKAPALI: VRAM Boşalt diyene kadar ağırlıklar bellekte hazır bekler.",
            ),
            "export_glb": (
                "Varsayılan çıktı formatı olarak .glb kullan",
                "AÇIK: PBR dokuları gömülü tek dosya .glb üretir; Unity/Blender'a doğrudan aktarılır.\nKAPALI: Ayrık ham mesh/doku çıktıları bırakır.",
            ),
        },
    },
    "gltf_transform": {
        "summary": ".glb/.gltf 3D modellerini Blender açmadan oyun bütçesine göre optimize eder (poligon ve doku küçültme).",
        "details": "Yüksek poligonlu modelleri çift vertex birleştirme (weld), temizleme (prune), sadeleştirme (simplify) ve doku boyut küçültmeyle oyun motoruna hazırlar.",
        "when_to_use": "3D modelleri oyun motoruna aktarmadan önce optimize ederken açın; diğer zamanlarda kapalı tutun.",
        "modes": ["Oyun İçi (1024px)", "Mobil / Düşük (512px)", "Kayıpsız Temizlik"],
        "param_label": "Maksimum Doku Boyutu (px)",
        "param_help": "2K/4K dokuların küçültüleceği üst sınır (örn: ana objeler için 1024, küçük eşyalar için 512).",
        "ai_question_hint": "Oyun içi 3D varlık optimizasyonunda hangi mesh ve doku adımlarını açık tutmalıyım?",
        "options": {
            "weld_dedup": (
                "Çift vertex'leri birleştir ve kullanılmayanları temizle",
                "AÇIK: Üst üste binen vertex'leri birleştirir ve boş materyal/kanalları temizler.\nKAPALI: Ham mesh verilerine dokunulmaz.",
            ),
            "simplify_mesh": (
                "Silüeti koruyarak poligon sayısını azalt",
                "AÇIK: Aşırı yoğun üçgen sayılarını gerçek zamanlı oyun bütçesine indirir.\nKAPALI: Poligon sayısı korunur, yalnızca dokular küçültülür.",
            ),
            "draco_meshopt": (
                "Meshopt / geometri sıkıştırması uygula",
                "AÇIK: WebGL veya akışlı sahneler için dosya boyutunu %60-%80 küçültür.\nKAPALI: Geniş uyumluluk için sıkıştırmasız standart .glb çıkarır.",
            ),
        },
    },
    "elevenlabs_mcp": {
        "summary": "Metin komutlarından oyun içi ses efekti (SFX), ambiyans ve karakter seslendirmesi üretir.",
        "details": "Ayak sesi, arayüz sesi, atmosfer ve diyalogları ElevenLabs API üzerinden üretir. Ayarlar > API Anahtarları altından ELEVENLABS_API_KEY girilmesi gerekir.",
        "when_to_use": "Ses efekti veya dublaj üretirken açın; sonrasında kredi ve token tasarrufu için kapatın.",
        "modes": ["Ses Efekti (SFX)", "Seslendirme / Diyalog"],
        "param_label": "Ses Çıktı Klasörü",
        "param_help": "Üretilen ses dosyalarının kaydedileceği klasör (örn: Assets/Audio).",
        "ai_question_hint": "Oyun SFX üretirken gereksiz kredi harcamamak için ElevenLabs MCP ayarlarım nasıl olmalı?",
        "options": {
            "confirm_credit": (
                "Üretim öncesi tahmini kredi onayı iste",
                "AÇIK: Üretimden önce süre ve tahmini kredi maliyetini onayınıza sunar.\nKAPALI: Onay sormadan doğrudan ses üretir.",
            ),
            "auto_wav_ogg": (
                "Oyun motoruna uygun yüksek kaliteli formatta kaydet",
                "AÇIK: Oyun motorları için temiz yüksek bit hızlı çıktı kaydeder.\nKAPALI: Daha küçük sıkıştırılmış web mp3 çıktısı kullanır.",
            ),
        },
    },
    "meshy": {
        "summary": "Bulut üzerinden metin/görselden 3D model üretimi, PBR doku kaplama ve temiz Quad topoloji dönüşümü.",
        "details": "Yerel GPU üretimi uygun olmadığında Meshy bulut API'si ile 3D üretim, otomatik PBR kaplama ve animasyona uygun Quad remesh yapar.",
        "when_to_use": "Yalnızca bilinçli olarak Meshy bulut kredisi kullanacağınız zaman açın; normalde kapalı tutun.",
        "modes": ["Taslak (Az Kredi)", "Standart Quad", "Yüksek PBR"],
        "param_label": "Hedef Poligon Sınırı",
        "param_help": "Meshy'den üretilecek 3D modeller için hedeflenen maksimum poligon sayısı.",
        "ai_question_hint": "Yerel GPU araçlarım varken Meshy bulut üretimini hangi durumlarda açmalıyım?",
        "options": {
            "confirm_paid": (
                "Bulut kredisi harcamadan önce onay iste",
                "AÇIK: Ücretli üretim veya kaplama başlatmadan önce onay ister.\nKAPALI: Bulut işlerini beklemeden doğrudan başlatır.",
            ),
            "quad_remesh": (
                "Temiz Quad topoloji iste",
                "AÇIK: Blender'da düzenlemesi ve rig bağlaması kolay temiz dörtgen topoloji üretir.\nKAPALI: Ham üçgen (triangle) ağ indirir.",
            ),
        },
    },
    "context7": {
        "summary": "Güncel kütüphane ve framework'ler için canlı resmi doküman ve çalışan API örnekleri çeker.",
        "details": "Unity, PySide6, React, Next.js, Tailwind ve Vite gibi araçların en son sürüm dokümanlarını getirerek eski bilgiyle uydurma kod yazılmasını önler.",
        "when_to_use": "Aktif yazılım geliştirilen neredeyse tüm projelerde açık tutulabilir (~1.6K düşük şema yükü).",
        "param_label": "Öncelikli Kütüphaneler",
        "param_help": "Sık kullandığınız teknolojilerin virgülle ayrılmış isteğe bağlı listesi (örn: Unity 6, PySide6, React).",
        "ai_question_hint": "Context7 doküman sorgularının kısa ve token dostu kalması için nasıl ayarlamalıyım?",
        "options": {
            "concise_snippets": (
                "Tam sayfa yerine özet kod örneklerini tercih et",
                "AÇIK: Bağlam tokenlarını korumak için yalnızca hedefli API imzası ve kısa örnek getirir.\nKAPALI: Daha uzun tam doküman sayfalarını çeker.",
            ),
        },
    },
    "chrome_devtools": {
        "summary": "Gerçek Chrome tarayıcısı üzerinden konsol hatalarını, DOM düzenini, ağ isteklerini ve Lighthouse hızını denetler.",
        "details": "Canlı tarayıcıda mobil uyumluluk, Core Web Vitals, SEO meta etiketleri, kırık linkler ve etkileşimli UI akışlarını test eder.",
        "when_to_use": "Web arayüzü ayıklarken veya yayın öncesi Lighthouse/SEO denetiminde açın; masaüstü/oyun projelerinde kapatın.",
        "modes": ["SEO & Lighthouse Denetimi", "Tam Tarayıcı Otomasyonu"],
        "param_label": "Hedef Site URL",
        "param_help": "Chrome DevTools / Lighthouse denetiminin açacağı varsayılan yerel veya canlı adres.",
        "ai_question_hint": "Yayın öncesi mobil uyumluluk ve Lighthouse denetimi için hangi Chrome DevTools MCP seçenekleri en iyisidir?",
        "options": {
            "mobile_emulation": (
                "Mobil görünüm ve duyarlılık testi",
                "AÇIK: Mobil ekran çözünürlüklerini, dokunmatik hedefleri ve taşma sorunlarını kontrol eder.\nKAPALI: Yalnızca masaüstü görünümünü denetler.",
            ),
            "lighthouse_vitals": (
                "Core Web Vitals & Lighthouse ölçümü çalıştır",
                "AÇIK: LCP/CLS hız, SEO ve erişilebilirlik puanlarını ölçer.\nKAPALI: Lighthouse olmadan daha hızlı DOM ve konsol kontrolü yapar.",
            ),
            "headless_mode": (
                "Chrome'u arka planda görünmez (Headless) çalıştır",
                "AÇIK: Görünür pencere açmadan arka planda sessizce test eder.\nKAPALI: Otomatik tıklamaları canlı Chrome penceresinde gösterir.",
            ),
        },
    },
}


def localized_tool_text(tool: ToolSpec, field_name: str, lang: str = "en") -> str:
    if lang == "tr":
        tr_entry = _TR_TOOL_TEXT.get(tool.id)
        if tr_entry and field_name in tr_entry and isinstance(tr_entry[field_name], str):
            return tr_entry[field_name]
    return str(getattr(tool, field_name, "") or "")


def localized_tool_modes(tool: ToolSpec, lang: str = "en") -> list[str]:
    if lang == "tr":
        tr_entry = _TR_TOOL_TEXT.get(tool.id)
        if tr_entry and "modes" in tr_entry:
            return list(tr_entry["modes"])
    return list(tool.modes)


def localized_option_text(tool_id: str, opt: CheckOption, lang: str = "en") -> tuple[str, str]:
    if lang == "tr":
        tr_opts = _TR_TOOL_TEXT.get(tool_id, {}).get("options", {})
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
            f"AÇIK: {core} (~350 token bağlam yükü).\n"
            "KAPALI: Bu kural AI bağlamına yüklenmez (~350 token tasarruf)."
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
        f"ON: {core} (~350 tokens context load).\n"
        "OFF: Excluded from AI context (~350 tokens saved)."
    )


PROFILES: dict[str, dict[str, Any]] = {
    "unity_game": {
        "title_key": "prof_unity_game_title",
        "desc_key": "prof_unity_game_desc",
        "enable": {"unity_mcp", "unity_pipeline", "renderdoc_mcp", "serena", "context7", "caveman"},
    },
    "asset_3d": {
        "title_key": "prof_asset_3d_title",
        "desc_key": "prof_asset_3d_desc",
        "enable": {"blender_mcp", "blender_skills", "trellis", "gltf_transform", "elevenlabs_mcp", "caveman"},
    },
    "web_release": {
        "title_key": "prof_web_release_title",
        "desc_key": "prof_web_release_desc",
        "enable": {"serena", "chrome_devtools", "bla", "context7", "caveman"},
    },
    "zero_token": {
        "title_key": "prof_zero_token_title",
        "desc_key": "prof_zero_token_desc",
        "enable": {"caveman"},
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
