"""14 Araç Kataloğu, 94 Gerçek Blender Skill Listesi, Proje Kapsamları ve Hazır İş Profilleri."""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any

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

DEFAULT_ACTIVE_BLENDER_SKILLS: list[str] = [
    "blender-director", "blender-modeler", "hard-surface", "prop-artist", "lowpoly-style",
    "psx-horror-style", "horror-style", "indie-horror-aesthetics", "uv-workflow",
    "materials", "asset-optimization", "unity-export", "export-pipeline",
]

AI_CLIENTS: list[tuple[str, str]] = [
    ("AGY", "Google Antigravity"),
    ("CDX", "OpenAI Codex"),
    ("CLD", "Claude Code"),
    ("CUR", "Cursor"),
]


def _detect_local_unity_project() -> pathlib.Path | None:
    for desktop_dir in [
        pathlib.Path.home() / "Desktop",
        pathlib.Path("D:/Windows Klasörleri/Desktop"),
    ]:
        if desktop_dir.is_dir():
            for child in desktop_dir.iterdir():
                nested = child / child.name
                if (nested / "Packages" / "manifest.json").is_file():
                    return nested
                if (child / "Packages" / "manifest.json").is_file():
                    return child
    return None


def _detect_local_trellis_dir() -> str:
    candidates = [
        pathlib.Path("D:/Programs/TrainAI/Trellis"),
        pathlib.Path.home() / "Trellis",
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


@dataclass
class ToolSpec:
    id: str
    name: str
    kind: str  # HTTP Servis | stdio MCP | CLI / GPU | Skill Paketi | Skill / Kural
    version: str
    repo_url: str
    schema_tokens: int
    latest_version: str = ""
    has_update: bool = False
    release_notes_url: str = ""
    enabled: bool = True
    clients: dict[str, bool] = field(default_factory=lambda: {"AGY": True, "CDX": True, "CLD": False, "CUR": False})
    scope_selectable: bool = True
    project_scope: str = "GLOBAL"  # "GLOBAL" veya proje anahtarı (ör: "project-train-unity")
    fixed_location_label: str = ""  # Proje seçimi uygulanmayan sistem servisleri için sabit konum etiketi
    live_location_detail: str = ""  # Çalışan süreçten veya diskten okunan canlı dosya/proje konumu
    modes: list[str] = field(default_factory=list)
    mode_index: int = 0
    has_gear: bool = False
    gear_kind: str = "standard"  # standard | skills94
    port: int | None = None
    health_url: str | None = None
    param_label: str = ""
    param_value: str = ""
    vault_key_name: str = ""
    install_cmd: str = ""
    mcp_server_key: str = ""
    mcp_command: str = ""
    mcp_args: list[str] = field(default_factory=list)
    ai_question_hint: str = ""
    options: list[CheckOption] = field(default_factory=list)
    usage_count: int = 0
    last_ping: str = "Kontrol bekliyor"
    last_latency_ms: int = -1


def build_default_catalog() -> list[ToolSpec]:
    u_proj = _detect_local_unity_project()
    def_scope = u_proj.name if u_proj else "GLOBAL"
    u_path = str(u_proj) if u_proj else ""
    u_parent = str(u_proj.parent) if u_proj else ""
    u_audio = str(u_proj / "Assets" / "Audio") if u_proj else ""
    t_dir = _detect_local_trellis_dir()

    return [
        ToolSpec(
            id="blender_skills",
            name="Blender Skills (arjun988)",
            kind="Skill Paketi",
            version="v1.3.0",
            repo_url="https://github.com/arjun988/blender-skills",
            schema_tokens=33000,
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=[],
            has_gear=True,
            gear_kind="skills94",
            install_cmd="git clone https://github.com/arjun988/blender-skills.git",
            ai_question_hint="Üzerinde çalıştığım 3D/oyun varlığı için 94 Blender skill içinden hangilerini açık bırakıp hangilerini kapatmam token tasarrufu ve kalite açısından en doğrusu olur?",
            usage_count=64,
        ),
        ToolSpec(
            id="bla",
            name="BLA (Blind LLM Agents)",
            kind="stdio MCP",
            version="v3.4.3",
            repo_url="https://github.com/qybaihe/bla",
            schema_tokens=3800,
            enabled=False,
            clients={"AGY": True, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=["Standart Koruma", "Bankrupt (Maks)", "Sadece Lint"],
            mode_index=1,
            has_gear=True,
            param_label="Hedef Çıktı Klasörü",
            param_value="dist/",
            install_cmd="npm install -g bla-agents",
            mcp_server_key="bla-agents",
            mcp_command="npx",
            mcp_args=["-y", "bla-agents", "mcp"],
            ai_question_hint="Web sitemi veya oyun paketimi yayına almadan önce çalışma zamanı (runtime) hızını bozmadan AI tersine mühendislik (REA) korumasını hangi seçeneklerle kullanmalıyım?",
            options=[
                CheckOption("honey_sourcemaps", "VLQ v3 Honey SourceMap üret (enableHoneySourceMaps)", True),
                CheckOption("self_seal", "SHA-256 kardeş dosya mühürleme (--self-seal)", True),
                CheckOption("llm_directives", "Agresif LLM tuzak yönergeleri (--llm-directives)", False),
                CheckOption("signed_manifest", "İmzalı doğrulama çıktısı (.bla-manifest.json)", False),
            ],
            usage_count=19,
        ),
        ToolSpec(
            id="caveman",
            name="Caveman",
            kind="Skill / Kural",
            version="v1.4.1",
            repo_url="https://github.com/JuliusBrussee/caveman",
            schema_tokens=200,
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": True, "CUR": True},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=["Lite (-35%)", "Full (-65%)", "Ultra (-75%)", "Wenyan"],
            mode_index=1,
            has_gear=False,
            install_cmd="git clone https://github.com/JuliusBrussee/caveman.git",
            usage_count=198,
        ),
        ToolSpec(
            id="serena",
            name="Serena (LSP)",
            kind="HTTP Servis",
            version="v0.9.2",
            repo_url="https://github.com/oraios/serena",
            schema_tokens=4200,
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=["Salt-Okunur", "Düzenleme Açık"],
            mode_index=0,
            has_gear=True,
            port=9121,
            param_label="LSP Sunucu Portu",
            param_value="9121",
            install_cmd="uv tool install serena-agent",
            mcp_server_key="serena",
            ai_question_hint="Büyük Unity/Web kod tabanında minimum token harcayarak güvenli sembol analizi yapmak için Serena LSP ayarlarım nasıl olmalı?",
            options=[
                CheckOption("read_only", "🔒 Sadece Okuma Yetkisi (--read-only)", True),
                CheckOption("shell_allow", "Shell komutu çalıştırma izni", False),
                CheckOption("no_dashboard", "Web panelini kapalı tut (--open-web-dashboard false)", True),
            ],
            usage_count=142,
        ),
        ToolSpec(
            id="unity_mcp",
            name="Unity MCP (CoplayDev)",
            kind="HTTP Servis",
            version="v2.2.0",
            repo_url="https://github.com/CoplayDev/unity-mcp",
            schema_tokens=4600,
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=[],
            has_gear=True,
            port=8080,
            param_label="Unity HTTP Portu",
            param_value="8080",
            install_cmd="uv tool install mcp-for-unity",
            mcp_server_key="unity-mcp",
            ai_question_hint="Unity 6 URP sahnesinde güvenli çalışmak ve gereksiz derleme gecikmesi yaşamamak için bu Unity MCP ayarlarım uygun mu?",
            options=[
                CheckOption("allow_play", "Play Mode ve C# script düzenleme izni", True),
                CheckOption("no_focus_steal", "Unity penceresini öne getirme (odak koruma)", True),
                CheckOption("auto_save_scene", "İşlem sonrası sahneyi otomatik kaydet", False),
            ],
            usage_count=86,
        ),
        ToolSpec(
            id="unity_pipeline",
            name="Unity Pipeline CLI (Resmi)",
            kind="CLI / GPU",
            version="v0.8.0-exp.1",
            repo_url="https://docs.unity3d.com/",
            schema_tokens=900,
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=["Method-Reload (Hızlı)", "Tam Derleme + Test"],
            mode_index=0,
            has_gear=True,
            param_label="Aktif Unity Projesi",
            param_value=u_path,
            ai_question_hint="Unity 6 projemde klavye/fare odağını çalmadan hızlı C# Method-Reload ve Play doğrulaması için Unity Pipeline CLI ile CoplayDev Unity MCP'yi nasıl birlikte kullanmalıyım?",
            options=[
                CheckOption("method_reload", "Domain Reload yerine hızlı Method-Reload tercih et", True),
                CheckOption("bg_screenshot", "Arka planda kamera/sahne ekran görüntüsü doğrulaması", True),
            ],
            usage_count=41,
        ),
        ToolSpec(
            id="renderdoc_mcp",
            name="RenderDoc MCP (Shader/SRP)",
            kind="stdio MCP",
            version="v0.3.2",
            repo_url="https://github.com/Linkingooo/renderdoc-mcp",
            schema_tokens=2900,
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=[],
            has_gear=True,
            param_label="Varsayılan .rdc Klasörü",
            param_value=u_parent,
            install_cmd="uvx renderdoc-mcp",
            mcp_server_key="renderdoc-mcp",
            mcp_command="uvx",
            mcp_args=["renderdoc-mcp"],
            ai_question_hint="Özel URP tek-pass HLSL shader'larımızda (smoothness/metallic, DepthNormals X-Ray, SRP Batcher) kare yakalaması (.rdc) incelerken hangi analiz seçenekleri açık olmalı?",
            options=[
                CheckOption("cbuffer_dump", "CBuffer (_Smoothness / _Metallic) değerlerini oku", True),
                CheckOption("srp_batch_check", "SRP Batcher kırılma nedenlerini raporla", True),
                CheckOption("depthnormals_pass", "DepthNormals / X-Ray pass çıktısını denetle", True),
            ],
            usage_count=15,
        ),
        ToolSpec(
            id="blender_mcp",
            name="Blender MCP Köprüsü",
            kind="HTTP Servis",
            version="v1.2.4",
            repo_url="https://github.com/ahujasid/blender-mcp",
            schema_tokens=2800,
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=False,
            fixed_location_label="🖥️ Blender 5.2 (:9876)",
            modes=[],
            has_gear=True,
            port=9876,
            param_label="Blender Soket Portu",
            param_value="9876",
            install_cmd="uvx blender-mcp",
            mcp_server_key="blender",
            mcp_command="uvx",
            mcp_args=["blender-mcp"],
            ai_question_hint="Blender 5.2 sahne üretiminde ve FBX/GLB dışa aktarımında güvenlik ve performans için bu Blender MCP izinlerim nasıl olmalı?",
            options=[
                CheckOption("exec_python", "Blender içinde Python kodu çalıştırma izni", True),
                CheckOption("polyhaven", "PolyHaven CC0 doku/model indirme köprüsü", False),
            ],
            usage_count=28,
        ),
        ToolSpec(
            id="trellis",
            name="Trellis Sunucu & CLI",
            kind="CLI / GPU",
            version="v1.1.0",
            repo_url="https://github.com/microsoft/TRELLIS",
            schema_tokens=1100,
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=False,
            fixed_location_label=f"🖥️ {t_dir}",
            modes=["Dengeli (1024px)", "Hızlı Önizleme (512px)", "Yüksek Kalite (2048px)"],
            mode_index=2,
            has_gear=True,
            port=8790,
            health_url="http://127.0.0.1:8790/health",
            param_label="Trellis Kurulum Klasörü",
            param_value=t_dir,
            ai_question_hint="RTX ekran kartımda Unity ve Blender açıkken VRAM şişmesi yaşamadan 3D model üretmek için Trellis ayarlarım nasıl olmalı?",
            options=[
                CheckOption("idle_vram_free", "30 dk boşta kalırsa sunucuyu kapatıp VRAM boşalt", True),
                CheckOption("export_glb", "Varsayılan çıktı formatı olarak .glb kullan", True),
            ],
            usage_count=31,
        ),
        ToolSpec(
            id="gltf_transform",
            name="glTF-Transform / 3D Asset MCP",
            kind="stdio MCP",
            version="v4.0.2",
            repo_url="https://github.com/GeoLibra/3d-asset-processing-mcp",
            schema_tokens=2100,
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=["Oyun İçi (1024px · Optimize)", "Mobil/Düşük (512px)", "Kayıpsız Temizlik"],
            mode_index=0,
            has_gear=True,
            param_label="Maksimum Doku Boyutu",
            param_value="1024",
            install_cmd="npm install -g @gltf-transform/cli",
            mcp_server_key="3d-asset-processing",
            mcp_command="npx",
            mcp_args=["-y", "3d-asset-processing-mcp"],
            ai_question_hint="Trellis ve Blender'dan çıkan prop modellerini Unity 6 URP'ye sokmadan önce poligon ve doku optimizasyonunda hangi adımları açık tutmalıyım?",
            options=[
                CheckOption("weld_dedup", "Çift vertex ve gereksiz materyalleri birleştir (weld + prune)", True),
                CheckOption("simplify_mesh", "Görünümü bozmadan poligon sadeleştir (simplify)", True),
                CheckOption("draco_meshopt", "Meshopt / sıkıştırma uygula", False),
            ],
            usage_count=9,
        ),
        ToolSpec(
            id="elevenlabs_mcp",
            name="ElevenLabs Ses & SFX MCP",
            kind="stdio MCP",
            version="v0.9.1",
            repo_url="https://github.com/elevenlabs/elevenlabs-mcp",
            schema_tokens=2600,
            enabled=False,
            clients={"AGY": True, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=["SFX (Ses Efekti)", "Karakter Diyalog / Mırıltı"],
            mode_index=0,
            has_gear=True,
            param_label="Ses Çıktı Klasörü",
            param_value=u_audio,
            vault_key_name="ELEVENLABS_API_KEY",
            install_cmd="uvx elevenlabs-mcp",
            mcp_server_key="elevenlabs",
            mcp_command="uvx",
            mcp_args=["elevenlabs-mcp"],
            ai_question_hint="Oyun içi atmosfer, eşya ve karakter sesleri üretirken kredi israfını önlemek için bu ElevenLabs MCP ayarlarım uygun mu?",
            options=[
                CheckOption("confirm_credit", "Üretim öncesi kredi/süre onayı iste", True),
                CheckOption("auto_wav_ogg", "Unity için doğrudan yüksek kaliteli ses kaydet", True),
            ],
            usage_count=6,
        ),
        ToolSpec(
            id="meshy",
            name="Meshy MCP",
            kind="stdio MCP",
            version="v0.4.1",
            repo_url="https://github.com/meshyai/meshy-mcp-server",
            schema_tokens=2300,
            enabled=False,
            clients={"AGY": False, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=False,
            fixed_location_label="☁️ Bulut API (stdio)",
            modes=["Taslak (Az Kredi)", "Standart Quad", "PBR Yüksek"],
            mode_index=0,
            has_gear=True,
            param_label="Hedef Poligon Limiti",
            param_value="10000",
            vault_key_name="MESHY_API_KEY",
            install_cmd="uvx meshy-mcp",
            mcp_server_key="meshy",
            mcp_command="uvx",
            mcp_args=["meshy-mcp"],
            ai_question_hint="Yerelde Trellis varken Meshy bulut kredilerimi yalnızca hangi durumlarda ve hangi ayarlarla açmalıyım?",
            options=[
                CheckOption("confirm_paid", "Ücretli kredi harcamadan önce onay iste", True),
                CheckOption("quad_remesh", "Oyun uyumlu Quad topoloji iste", True),
            ],
            usage_count=0,
        ),
        ToolSpec(
            id="context7",
            name="Context7 Docs MCP",
            kind="stdio MCP",
            version="v1.0.8",
            repo_url="https://github.com/upstash/context7",
            schema_tokens=1600,
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": True, "CUR": True},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=[],
            has_gear=True,
            param_label="Öncelikli Kütüphaneler",
            param_value="Unity 6 URP, PySide6, Vite",
            vault_key_name="CONTEXT7_API_KEY",
            install_cmd="npx -y @upstash/context7-mcp",
            mcp_server_key="context7",
            mcp_command="npx",
            mcp_args=["-y", "@upstash/context7-mcp"],
            ai_question_hint="Güncel kütüphane dokümanlarını çekerken gereksiz bağlam şişmesini önlemek için Context7 kullanım ayarım nasıl olmalı?",
            options=[
                CheckOption("concise_snippets", "Tam sayfa yerine özet kod örnekleri getir", True),
            ],
            usage_count=77,
        ),
        ToolSpec(
            id="chrome_devtools",
            name="Chrome DevTools / Lighthouse MCP",
            kind="stdio MCP",
            version="v0.18.0",
            repo_url="https://github.com/ChromeDevTools/chrome-devtools-mcp",
            schema_tokens=3400,
            enabled=False,
            clients={"AGY": True, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=["SEO & Lighthouse Denetimi", "Tam Tarayıcı Otomasyonu"],
            mode_index=0,
            has_gear=True,
            param_label="Test Edilecek Site URL",
            param_value="http://localhost:3000",
            install_cmd="npx -y chrome-devtools-mcp@latest",
            mcp_server_key="chrome-devtools",
            mcp_command="npx",
            mcp_args=["-y", "chrome-devtools-mcp@latest"],
            ai_question_hint="20 maddelik web sitesi yayına alma kontrol listemizi (mobil sticky CTA, site hızı, meta etiketleri, 404, zengin içerik) denetlerken hangi seçenekler açık olmalı?",
            options=[
                CheckOption("mobile_emulation", "Mobil görünüm ve Sticky Telefon CTA testi", True),
                CheckOption("lighthouse_vitals", "Core Web Vitals & Site Hızı ölçümü", True),
                CheckOption("headless_mode", "Arka planda görünmez (Headless) çalıştır", False),
            ],
            usage_count=12,
        ),
    ]


PROFILES: dict[str, dict[str, Any]] = {
    "unity_game": {
        "title": "🎮 Unity & Shader",
        "desc": "Project Train: Unity MCP + Pipeline + RenderDoc + Serena + Context7 + Caveman açık; 3D/Web kapalı.",
        "enable": {"unity_mcp", "unity_pipeline", "renderdoc_mcp", "serena", "context7", "caveman"},
    },
    "asset_3d": {
        "title": "🎨 3D & Korku Asset",
        "desc": "Blender MCP + Seçili Blender Skills + Trellis GPU + glTF-Transform + ElevenLabs SFX açık.",
        "enable": {"blender_mcp", "blender_skills", "trellis", "gltf_transform", "elevenlabs_mcp", "caveman"},
    },
    "web_release": {
        "title": "🌐 Web & Yayın (BLA)",
        "desc": "20 maddelik site güncellemesi + Chrome DevTools/Lighthouse + BLA koruma + Serena + Context7 açık.",
        "enable": {"serena", "chrome_devtools", "bla", "context7", "caveman"},
    },
    "zero_token": {
        "title": "⚡ Sıfır Token (Uyku)",
        "desc": "Tüm MCP şema yükünü kapatır; yalnızca Caveman tasarruf kuralını açık bırakır.",
        "enable": {"caveman"},
    },
}
