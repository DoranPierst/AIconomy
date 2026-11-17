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
    help_text: str = ""


@dataclass
class ToolSpec:
    id: str
    name: str
    kind: str  # HTTP Servis | stdio MCP | CLI / GPU | Skill Paketi | Skill / Kural
    version: str
    repo_url: str
    schema_tokens: int
    summary: str = ""  # Tek satırlık kısa özet (Ne işe yarar?)
    details: str = ""  # Detaylı çalışma açıklaması (? bilgi penceresi için)
    when_to_use: str = ""  # Ne zaman açmalı / ne zaman kapatmalı?
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
    param_help: str = ""
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
            summary="Blender için 94 adet uzman yapay zeka yetenek (SKILL.md) kütüphanesi (modelleme, UV, materyal, PSX/korku, oyun motoru export).",
            details="Yapay zekaya Blender'da rastgele kod yazmak yerine profesyonel topoloji, hard-surface, ışıklandırma, doku üretimi ve Unity/Unreal/Godot dışa aktarım kurallarını öğretir. Çark (⚙️) menüsünden 94 yetenekten sadece o an ihtiyacınız olanları seçerek on binlerce token tasarruf edersiniz.",
            when_to_use="3D modelleme, sahne kurulumu, materyal veya oyun varlığı hazırlarken AÇIN; sadece yazılım/web geliştirirken KAPATIN.",
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
            summary="Yayınlanan web sitelerini ve uygulama paketlerini yapay zeka tabanlı tersine mühendisliğe (AI Reverse Engineering) karşı korur.",
            details="Kaynak haritalarına (SourceMap) yanıltıcı tuzaklar (Honey SourceMaps), SHA-256 dosya mühürleme ve kod okuyan ajanları şaşırtan yönergeler ekleyerek ürününüzün yapay zeka botlarıyla kopyalanmasını zorlaştırır; çalışma zamanı (runtime) hızını düşürmez.",
            when_to_use="Web sitenizi veya uygulamanızı yayına (production build) hazırlarken AÇIN; günlük geliştirme sırasında KAPALI tutun.",
            enabled=False,
            clients={"AGY": True, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=["Standart Koruma", "Bankrupt (Maks)", "Sadece Lint"],
            mode_index=1,
            has_gear=True,
            param_label="Hedef Çıktı Klasörü",
            param_value="dist/",
            param_help="BLA korumasının uygulanacağı derlenmiş yayın (build) klasörüdür (örn: dist/, build/, out/). Kaynak kodlarınıza dokunmaz, yalnızca buradaki paketlenmiş çıktıyı mühürler.",
            install_cmd="npm install -g bla-agents",
            mcp_server_key="bla-agents",
            mcp_command="npx",
            mcp_args=["-y", "bla-agents", "mcp"],
            ai_question_hint="Web sitemi veya paketimi yayına almadan önce çalışma zamanı (runtime) hızını bozmadan AI tersine mühendislik (REA) korumasını hangi seçeneklerle kullanmalıyım?",
            options=[
                CheckOption(
                    "honey_sourcemaps",
                    "VLQ v3 Honey SourceMap üret (enableHoneySourceMaps)",
                    True,
                    "✅ AÇARSAN: Gerçek kaynak kodunu gizleyip yapay zeka botlarını inandırıcı sahte kod haritalarına (Honey SourceMap) yönlendirir; sitenin çalışma hızını hiç düşürmez.\n⛔ KAPATIRSAN: Sahte kaynak haritası üretilmez; kod gizliliği yalnızca standart küçültmeye (minification) kalır.",
                ),
                CheckOption(
                    "self_seal",
                    "SHA-256 kardeş dosya mühürleme (--self-seal)",
                    True,
                    "✅ AÇARSAN: Yayın klasöründeki JS/CSS dosyalarını SHA-256 özetiyle birbirine mühürler; bir dosyanın dışarıdan kurcalanıp değiştirildiğini anında yakalar.\n⛔ KAPATIRSAN: Dosyalar arası bütünlük mührü eklenmez.",
                ),
                CheckOption(
                    "llm_directives",
                    "Agresif LLM tuzak yönergeleri (--llm-directives)",
                    False,
                    "✅ AÇARSAN: Kodun içine tersine mühendislik yapan yapay zeka ajanlarının bağlamını şaşırtacak agresif tuzak yönergeler gömer (dosya boyutunu çok az artırabilir).\n⛔ KAPATIRSAN: Ek tuzak metinleri gömülmez; daha hafif paket çıktısı alınır.",
                ),
                CheckOption(
                    "signed_manifest",
                    "İmzalı doğrulama çıktısı (.bla-manifest.json)",
                    False,
                    "✅ AÇARSAN: Dağıtım klasörüne tüm dosyaların kriptografik imzasını içeren .bla-manifest.json denetim dosyası yazar.\n⛔ KAPATIRSAN: Ek manifest dosyası oluşturulmaz.",
                ),
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
            summary="Yapay zekanın gereksiz kibarlık ve laf kalabalığını keserek çıktı token tüketimini %35 ila %75 azaltan tasarruf kuralı.",
            details="Kod kalitesini ve teknik doğruluğu hiç bozmadan yapay zeka yanıtlarını kısa, net ve doğrudan çözüme odaklı hale getirir. Şema yükü neredeyse sıfırdır (~200 token) ve tüm AI istemcilerinde kota ömrünü uzatır.",
            when_to_use="Her zaman AÇIK kalması önerilir. Uzun ve detaylı anlatım istediğiniz dokümantasyon/eğitim işlerinde Lite moda alabilir veya kapatabilirsiniz.",
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
            summary="Büyük kod tabanlarını tüm dosyaları baştan sona okutmadan Dil Sunucusu (LSP) ile sembol, sınıf ve fonksiyon bazında analiz eder.",
            details="Binlerce satırlık dosyaları yapay zekaya komple yükleyip kotayı bitirmek yerine doğrudan aranan fonksiyonun tanımını ve referanslarını bulur. Büyük oyun ve yazılım projelerinde yüksek hız ve token tasarrufu sağlar.",
            when_to_use="Orta ve büyük ölçekli kod projelerinde (Unity C#, Python, TypeScript vb.) çalışırken AÇIN; küçük tek dosyalık işlerde kapatabilirsiniz.",
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
            param_help="Serena yerel HTTP dil sunucusunun dinlediği port numarasıdır (varsayılan: 9121). Başka bir programla çakışmadıkça değiştirmeyin.",
            install_cmd="uv tool install serena-agent",
            mcp_server_key="serena",
            ai_question_hint="Büyük kod tabanında minimum token harcayarak güvenli sembol analizi yapmak için Serena LSP ayarlarım nasıl olmalı?",
            options=[
                CheckOption(
                    "read_only",
                    "🔒 Sadece Okuma Yetkisi (--read-only)",
                    True,
                    "✅ AÇARSAN: Serena kodunuzu yalnızca okur, sınıf/fonksiyon arar ve analiz eder; dosyalarınızı doğrudan değiştiremez (en güvenli moddur).\n⛔ KAPATIRSAN: Serena üzerinden doğrudan sembol yeniden adlandırma ve kod değiştirme araçları da aktifleşir.",
                ),
                CheckOption(
                    "shell_allow",
                    "Shell komutu çalıştırma izni",
                    False,
                    "✅ AÇARSAN: Serena sunucusunun kendi içinden terminal/kabuk komutu çalıştırmasına izin verir.\n⛔ KAPATIRSAN: Terminal komut yetkisi kapalı kalır; komutları yalnızca ana AI istemciniz onayınızla çalıştırır (önerilen).",
                ),
                CheckOption(
                    "no_dashboard",
                    "Web panelini kapalı tut (--open-web-dashboard false)",
                    True,
                    "✅ AÇARSAN: Serena her başladığında tarayıcınızda otomatik sekme açmasını engeller; arka planda sessizce çalışır.\n⛔ KAPATIRSAN: Serena başlarken varsayılan tarayıcıda yerel izleme sayfası açılır.",
                ),
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
            summary="Yapay zekayı açık olan Unity Editörüne bağlayarak sahne hiyerarşisi, GameObject, Prefab, Materyal ve C# bileşenlerini yönetmesini sağlar.",
            details="Unity içinde yerel HTTP köprüsü (:8080) üzerinden çalışır. Yapay zeka sahnedeki objeleri inceleyebilir, bileşen ekleyip özelliklerini değiştirebilir, konsol hatalarını okuyabilir ve sahne kurulumunu otomatikleştirebilir.",
            when_to_use="Unity Editör açıkken sahne, obje veya C# bileşeni düzenletirken AÇIN; Unity kapalıyken ~4.6K şema tokenı harcamaması için KAPATIN.",
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=[],
            has_gear=True,
            port=8080,
            param_label="Unity HTTP Portu",
            param_value="8080",
            param_help="Unity Editör içindeki MCP for Unity paketinin dinlediği yerel port numarasıdır (varsayılan: 8080). Unity içindeki MCP penceresiyle aynı olmalıdır.",
            install_cmd="uv tool install --python 3.12 mcpforunityserver",
            mcp_server_key="unity-mcp",
            ai_question_hint="Unity sahnesinde güvenli çalışmak ve gereksiz derleme gecikmesi yaşamamak için bu Unity MCP ayarlarım uygun mu?",
            options=[
                CheckOption(
                    "allow_play",
                    "Play Mode ve C# script düzenleme izni",
                    True,
                    "✅ AÇARSAN: Yapay zeka C# scriptleri oluşturup düzenleyebilir ve oyunu Play Mode'a alıp test edebilir.\n⛔ KAPATIRSAN: Yalnızca sahne ve obje incelemesi yapar; kod değiştirme ve Play başlatma kısıtlanır.",
                ),
                CheckOption(
                    "no_focus_steal",
                    "Unity penceresini öne getirme (odak koruma)",
                    True,
                    "✅ AÇARSAN: Yapay zeka Unity'de işlem yaparken Unity penceresi ekranınızın önüne fırlamaz; kod editöründe veya tarayıcıda kesintisiz çalışmaya devam edersiniz.\n⛔ KAPATIRSAN: İşlem sırasında Unity Editör penceresi öne gelip klavye/fare odağını alabilir.",
                ),
                CheckOption(
                    "auto_save_scene",
                    "İşlem sonrası sahneyi otomatik kaydet",
                    False,
                    "✅ AÇARSAN: Yapay zekanın sahnede yaptığı her değişiklikten sonra .unity sahne dosyası otomatik kaydedilir.\n⛔ KAPATIRSAN: Değişiklikleri önce gözünüzle kontrol edip beğenirseniz Ctrl+S ile kendiniz kaydedersiniz (deneme yaparken daha güvenlidir).",
                ),
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
            summary="Unity penceresini öne getirmeden (klavye/fare odağını çalmadan) arka planda hızlı C# Method-Reload, derleme ve Play doğrulaması yapar.",
            details="Unity 6 resmi otomasyon hattını kullanır. Uzun süren tam Domain Reload beklemeleri yerine yalnızca değişen C# metotlarını anında yenileyip test ve sahne ekran görüntüsü doğrulaması yapabilmesini sağlar.",
            when_to_use="Unity'de sık C# kod değişikliği ve hızlı test döngüsü yaparken AÇIN; oyun dışı projelerde KAPATIN.",
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=["Method-Reload (Hızlı)", "Tam Derleme + Test"],
            mode_index=0,
            has_gear=True,
            param_label="Aktif Unity Projesi",
            param_value=u_path,
            param_help="Unity Pipeline CLI komutlarının hedef alacağı Unity proje kök klasörüdür (içinde Assets ve Packages bulunan klasör).",
            ai_question_hint="Unity projemde klavye/fare odağını çalmadan hızlı C# Method-Reload ve Play doğrulaması için Unity Pipeline CLI ile CoplayDev Unity MCP'yi nasıl birlikte kullanmalıyım?",
            options=[
                CheckOption(
                    "method_reload",
                    "Domain Reload yerine hızlı Method-Reload tercih et",
                    True,
                    "✅ AÇARSAN: Küçük C# metot değişikliklerinde 10-30 saniyelik tam Domain Reload beklemek yerine metodu bellekte anında yeniler; iterasyon hızını katlar.\n⛔ KAPATIRSAN: Her kod değişikliğinde klasik tam derleme ve Domain Reload beklenir.",
                ),
                CheckOption(
                    "bg_screenshot",
                    "Arka planda kamera/sahne ekran görüntüsü doğrulaması",
                    True,
                    "✅ AÇARSAN: Yapay zeka yaptığı görsel/sahne değişikliğini arka planda kameradan ekran görüntüsü alarak kendi gözüyle kontrol eder.\n⛔ KAPATIRSAN: Görsel doğrulama yapılmaz; yalnızca derleme ve konsol loglarına bakılır.",
                ),
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
            summary="RenderDoc kare yakalama (.rdc) dosyalarını yapay zekaya okutarak GPU draw call, HLSL shader, CBuffer ve SRP Batcher hatalarını çözdürür.",
            details="Yapay zekanın sadece shader koduna bakıp tahmin yürütmesi yerine; hangi draw call'da hangi doku veya CBuffer değerinin sıfırlandığını, derinlik/normal pass çıktılarını ve grafik darboğazlarını doğrudan GPU kaydından görmesini sağlar.",
            when_to_use="Yalnızca grafik hatası, özel shader (HLSL/URP/HDRP) veya FPS/draw-call optimizasyonu incelerken AÇIN; diğer zamanlarda KAPALI tutun.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=[],
            has_gear=True,
            param_label="Varsayılan .rdc Klasörü",
            param_value=u_parent,
            param_help="RenderDoc ile aldığınız kare yakalama (.rdc) dosyalarının bulunduğu varsayılan klasör yoludur.",
            install_cmd="uvx renderdoc-mcp",
            mcp_server_key="renderdoc-mcp",
            mcp_command="uvx",
            mcp_args=["renderdoc-mcp"],
            ai_question_hint="Özel HLSL/URP shader'larda (smoothness/metallic, DepthNormals, SRP Batcher) kare yakalaması (.rdc) incelerken hangi analiz seçenekleri açık olmalı?",
            options=[
                CheckOption(
                    "cbuffer_dump",
                    "CBuffer (_Smoothness / _Metallic) değerlerini oku",
                    True,
                    "✅ AÇARSAN: Seçili draw call anında GPU'ya giden Constant Buffer (_Smoothness, _Metallic, renk, ışık vb.) gerçek sayısal değerlerini okur; materyalin neden mat veya siyah kaldığını kesin gösterir.\n⛔ KAPATIRSAN: CBuffer sayısal içerikleri çekilmez; yalnızca genel draw call sırası görülür.",
                ),
                CheckOption(
                    "srp_batch_check",
                    "SRP Batcher kırılma nedenlerini raporla",
                    True,
                    "✅ AÇARSAN: Unity URP/HDRP sahnesinde SRP Batcher'ın hangi objelerde ve hangi uyumsuz shader özelliğinden dolayı kırıldığını otomatik tespit eder.\n⛔ KAPATIRSAN: SRP Batcher uyumluluk kontrolü atlanır.",
                ),
                CheckOption(
                    "depthnormals_pass",
                    "DepthNormals / X-Ray pass çıktısını denetle",
                    True,
                    "✅ AÇARSAN: Outline, SSAO ve X-Ray gibi efektlerin kullandığı DepthNormals ara dokusunu inceleyip özel shader'ların derinlik/normal bozup bozmadığını yakalar.\n⛔ KAPATIRSAN: DepthNormals ara pass dokuları incelenmez.",
                ),
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
            summary="Yapay zekayı açık olan Blender uygulamasına soket (:9876) üzerinden bağlayarak sahnede canlı 3D model üretmesi ve düzenlemesini sağlar.",
            details="Blender içinde Python komutları çalıştırarak modelleme, materyal atama, kamera/ışık kurulumu, FBX/GLB dışa aktarımı ve PolyHaven üzerinden ücretsiz CC0 doku/model indirme işlemlerini doğrudan açık sahnede uygular.",
            when_to_use="Blender açıkken yapay zekaya sahnede doğrudan işlem yaptıracağınız zaman AÇIN; Blender kapalıyken KAPALI tutun.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=False,
            fixed_location_label="🖥️ Blender 5.2 (:9876)",
            modes=[],
            has_gear=True,
            port=9876,
            param_label="Blender Soket Portu",
            param_value="9876",
            param_help="Blender içindeki BlenderMCP eklentisinin (N yan menüsü -> BlenderMCP) dinlediği yerel port numarasıdır (varsayılan: 9876).",
            install_cmd="uvx blender-mcp",
            mcp_server_key="blender",
            mcp_command="uvx",
            mcp_args=["blender-mcp"],
            ai_question_hint="Blender sahne üretiminde ve FBX/GLB dışa aktarımında güvenlik ve performans için bu Blender MCP izinlerim nasıl olmalı?",
            options=[
                CheckOption(
                    "exec_python",
                    "Blender içinde Python kodu çalıştırma izni",
                    True,
                    "✅ AÇARSAN: Yapay zeka açık Blender sahnesinde doğrudan bpy (Python) scriptleri çalıştırarak 3D model üretebilir, UV açabilir ve materyal bağlayabilir.\n⛔ KAPATIRSAN: Kod çalıştırma engellenir; yapay zeka yalnızca sahnedeki mevcut objelerin bilgisini okuyabilir.",
                ),
                CheckOption(
                    "polyhaven",
                    "PolyHaven CC0 doku/model indirme köprüsü",
                    False,
                    "✅ AÇARSAN: Yapay zekanın PolyHaven kütüphanesinden telifsiz (CC0) PBR dokuları, HDRI çevre ışıklarını ve hazır modelleri doğrudan sahneye indirmesine izin verir.\n⛔ KAPATIRSAN: İnternetten hazır doku/model indirme kapatılır; yalnızca yerel/prosedürel materyaller kullanılır.",
                ),
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
            summary="Kendi ekran kartınızı (GPU) kullanarak görselden veya metinden yerel ve ücretsiz olarak yüksek detaylı 3D model (.glb) üretir.",
            details="Microsoft TRELLIS modelini kendi bilgisayarınızda çalıştırarak bulut kredisi harcamadan 3D oyun varlığı üretir. Çalışırken yüksek VRAM kullandığı için işiniz bittiğinde üst bardaki '🧹 VRAM Boşalt' butonuyla uyutabilirsiniz.",
            when_to_use="Yerel GPU ile yeni 3D model üreteceğiniz zaman AÇIN; oyun motoru veya ağır sahnelerde VRAM gerektiğinde KAPATIP VRAM boşaltın.",
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
            param_help="Bilgisayarınızdaki yerel Microsoft TRELLIS kurulum ve model ağırlıklarının bulunduğu klasör yoludur.",
            ai_question_hint="Ekran kartımda Unity ve Blender açıkken VRAM şişmesi yaşamadan 3D model üretmek için Trellis ayarlarım nasıl olmalı?",
            options=[
                CheckOption(
                    "idle_vram_free",
                    "30 dk boşta kalırsa sunucuyu kapatıp VRAM boşalt",
                    True,
                    "✅ AÇARSAN: Trellis 30 dakika boyunca yeni 3D üretim yapmazsa GPU sunucusunu otomatik uyutup 6-10 GB ekran kartı belleğini (VRAM) oyun motorunuz için geri verir.\n⛔ KAPATIRSAN: Siz üst bardan '🧹 VRAM Boşalt' diyene kadar model ekran kartı belleğinde hazır bekler.",
                ),
                CheckOption(
                    "export_glb",
                    "Varsayılan çıktı formatı olarak .glb kullan",
                    True,
                    "✅ AÇARSAN: Üretilen 3D modelleri PBR dokuları içine gömülü tek dosya .glb olarak çıkarır; Unity ve Blender'a sürükle-bırak ile sorunsuz girer.\n⛔ KAPATIRSAN: Ham/ayrık çıktı formatı kullanılır.",
                ),
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
            summary="Ham .glb/.gltf 3D modelleri Blender bile açmadan tek komutla oyun bütçesine uygun hale getirir (poligon düşürme, doku küçültme).",
            details="Trellis, Meshy veya Blender'dan çıkan yüksek poligonlu ve büyük dokulu modelleri; çift vertex birleştirme (weld), poligon sadeleştirme (simplify), gereksiz kanal silme ve 2048px -> 1024px/512px doku küçültmeyle optimize eder.",
            when_to_use="3D modelleri oyun projesine aktarmadan önce boyut ve FPS optimizasyonu yaparken AÇIN; diğer zamanlarda KAPALI tutun.",
            enabled=False,
            clients={"AGY": True, "CDX": True, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=["Oyun İçi (1024px · Optimize)", "Mobil/Düşük (512px)", "Kayıpsız Temizlik"],
            mode_index=0,
            has_gear=True,
            param_label="Maksimum Doku Boyutu",
            param_value="1024",
            param_help="3D modellerin içindeki 2048px/4096px ağır dokuların küçültüleceği üst piksel sınırıdır (örn: oyun içi prop için 1024, küçük eşyalar için 512).",
            install_cmd="npm install -g @gltf-transform/cli",
            mcp_server_key="3d-asset-processing",
            mcp_command="npx",
            mcp_args=["-y", "3d-asset-processing-mcp"],
            ai_question_hint="Üretilen 3D prop modellerini oyun motoruna sokmadan önce poligon ve doku optimizasyonunda hangi adımları açık tutmalıyım?",
            options=[
                CheckOption(
                    "weld_dedup",
                    "Çift vertex ve gereksiz materyalleri birleştir (weld + prune)",
                    True,
                    "✅ AÇARSAN: Üst üste binen kopuk noktaları (vertex) kaynatır ve kullanılmayan boş materyal/doku kanallarını silerek modeli temizler.\n⛔ KAPATIRSAN: Ham modeldeki tekrarlı vertex ve boş kanallar olduğu gibi kalır.",
                ),
                CheckOption(
                    "simplify_mesh",
                    "Görünümü bozmadan poligon sadeleştir (simplify)",
                    True,
                    "✅ AÇARSAN: AI üretimi modellerin yüz binlerce gereksiz üçgenini silüeti bozmadan oyun motoru bütçesine indirir; FPS'i ciddi artırır.\n⛔ KAPATIRSAN: Poligon sayısına dokunulmaz; yalnızca doku boyutu küçültülür.",
                ),
                CheckOption(
                    "draco_meshopt",
                    "Meshopt / sıkıştırma uygula",
                    False,
                    "✅ AÇARSAN: Geometri verisini sıkıştırarak özellikle WebGL veya büyük açık sahnelerde dosya boyutunu %60-80 küçültür.\n⛔ KAPATIRSAN: Ek sıkıştırma yapılmaz (Unity/Blender'a doğrudan ham .glb atarken kapalı kalması eklenti gereksinimini önler).",
                ),
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
            summary="Metinden doğrudan oyun içi ses efekti (SFX), ambiyans ve karakter seslendirmesi üretip proje klasörüne indiren ses üretim aracı.",
            details="Metal kapı sesi, ayak sesi, arayüz bip sesi, rüzgar uğultusu veya karakter replikleri gibi sesleri metin komutundan üretir. ElevenLabs API anahtarınız Windows DPAPI Şifreli Kasa'da korunur.",
            when_to_use="Oyun veya video için ses efekti / dublaj üreteceğiniz zaman AÇIN; kredi ve token harcamaması için işiniz bitince KAPATIN.",
            enabled=False,
            clients={"AGY": True, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope=def_scope,
            modes=["SFX (Ses Efekti)", "Karakter Diyalog / Mırıltı"],
            mode_index=0,
            has_gear=True,
            param_label="Ses Çıktı Klasörü",
            param_value=u_audio,
            param_help="Üretilen ses efektlerinin (SFX) ve diyalog dosyalarının otomatik kaydedileceği klasör yoludur (örn: Assets/Audio).",
            vault_key_name="ELEVENLABS_API_KEY",
            install_cmd="uvx elevenlabs-mcp",
            mcp_server_key="elevenlabs",
            mcp_command="uvx",
            mcp_args=["elevenlabs-mcp"],
            ai_question_hint="Oyun içi atmosfer, eşya ve karakter sesleri üretirken kredi israfını önlemek için bu ElevenLabs MCP ayarlarım uygun mu?",
            options=[
                CheckOption(
                    "confirm_credit",
                    "Üretim öncesi kredi/süre onayı iste",
                    True,
                    "✅ AÇARSAN: ElevenLabs kredisi harcamadan önce üretilecek sesin süresini ve tahmini kredi maliyetini gösterip onayınızı ister.\n⛔ KAPATIRSAN: Yapay zeka onay beklemeden doğrudan ses üretip klasöre indirir.",
                ),
                CheckOption(
                    "auto_wav_ogg",
                    "Oyun motoru için doğrudan yüksek kaliteli ses kaydet",
                    True,
                    "✅ AÇARSAN: Ses dosyalarını oyun motorlarında gecikmesiz ve kayıpsız çalışacak yüksek kaliteli formatta indirir.\n⛔ KAPATIRSAN: Varsayılan düşük bit hızlı web mp3 çıktısı kullanılır.",
                ),
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
            summary="Bulut üzerinden metinden/görselden 3D model üretimi, otomatik PBR doku kaplama (retexture) ve Quad topoloji dönüşümü yapar.",
            details="Yerel ekran kartı yetersiz kaldığında veya bulut tabanlı otomatik PBR materyal kaplama ve animasyona uygun temiz Quad remesh gerektiğinde Meshy API anahtarınızla çalışır.",
            when_to_use="Yalnızca bulut tabanlı 3D üretim / kaplama yapacağınız zaman AÇIN (ücretli API kredisi kullanır); normalde KAPALI tutun.",
            enabled=False,
            clients={"AGY": False, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=False,
            fixed_location_label="☁️ Bulut API (stdio)",
            modes=["Taslak (Az Kredi)", "Standart Quad", "PBR Yüksek"],
            mode_index=0,
            has_gear=True,
            param_label="Hedef Poligon Limiti",
            param_value="10000",
            param_help="Meshy bulut servisinden üretilecek 3D modelin hedef maksimum yüzey/poligon (polycount) sınırıdır.",
            vault_key_name="MESHY_API_KEY",
            install_cmd="uvx meshy-mcp",
            mcp_server_key="meshy",
            mcp_command="uvx",
            mcp_args=["meshy-mcp"],
            ai_question_hint="Yerelde GPU aracım varken Meshy bulut kredilerimi yalnızca hangi durumlarda ve hangi ayarlarla açmalıyım?",
            options=[
                CheckOption(
                    "confirm_paid",
                    "Ücretli kredi harcamadan önce onay iste",
                    True,
                    "✅ AÇARSAN: Ücretli Meshy API kredisi tüketecek model üretimi veya doku kaplama işleminden önce sizden onay ister.\n⛔ KAPATIRSAN: Komut verildiğinde onay sormadan bulut kredisini kullanarak üretimi başlatır.",
                ),
                CheckOption(
                    "quad_remesh",
                    "Oyun uyumlu Quad topoloji iste",
                    True,
                    "✅ AÇARSAN: Modeli karmaşık üçgenler yerine temiz dörtgen (Quad) yüzeylerle üretir; Blender'da düzenleme ve iskelet (rig) bağlama çok kolaylaşır.\n⛔ KAPATIRSAN: Standart üçgen (triangle) ağ yapısıyla indirir.",
                ),
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
            summary="Yapay zekanın eski bilgiyle uydurma kod yazmasını önlemek için kütüphanelerin en güncel resmi dokümanlarını anlık çeker.",
            details="Unity 6, PySide6, React, Next.js, Tailwind, Vite gibi yüzlerce güncel kütüphanenin en son sürüm API kurallarını ve çalışan kod örneklerini doğrudan kaynağından getirir.",
            when_to_use="Güncel kütüphane ve framework kullandığınız her yazılım projesinde AÇIK tutabilirsiniz (~1.6K düşük şema yükü).",
            enabled=True,
            clients={"AGY": True, "CDX": True, "CLD": True, "CUR": True},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=[],
            has_gear=True,
            param_label="Öncelikli Kütüphaneler",
            param_value="Unity 6 URP, PySide6, Vite",
            param_help="Sorgularda öncelik verilecek ana teknolojilerinizin listesidir; yapay zekanın doğru doküman sürümünü seçmesine yardımcı olur.",
            vault_key_name="CONTEXT7_API_KEY",
            install_cmd="npx -y @upstash/context7-mcp",
            mcp_server_key="context7",
            mcp_command="npx",
            mcp_args=["-y", "@upstash/context7-mcp"],
            ai_question_hint="Güncel kütüphane dokümanlarını çekerken gereksiz bağlam şişmesini önlemek için Context7 kullanım ayarım nasıl olmalı?",
            options=[
                CheckOption(
                    "concise_snippets",
                    "Tam sayfa yerine özet kod örnekleri getir",
                    True,
                    "✅ AÇARSAN: Dokümanın tüm uzun makalesini çekmek yerine yalnızca ilgili fonksiyonun güncel kullanım ve kod örneğini getirir; büyük token tasarrufu sağlar.\n⛔ KAPATIRSAN: Doküman sayfalarını tam metin halinde uzun olarak çeker.",
                ),
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
            summary="Yapay zekanın gerçek Chrome tarayıcısını açıp web sitenizi canlı test etmesini, konsol hatalarını görmesini ve Lighthouse hız/SEO ölçmesini sağlar.",
            details="Mobil görünüm uyumluluğu, tıklama/form otomasyonu, sayfa açılış hızı (Core Web Vitals), ağ istekleri, kırık linkler ve SEO/erişilebilirlik denetimlerini tarayıcı üzerinden bizzat görerek raporlar.",
            when_to_use="Web sitesi geliştirirken, arayüz hatası ayıklarken veya yayın öncesi SEO/hız testi yaparken AÇIN; masaüstü/oyun geliştirirken KAPATIN.",
            enabled=False,
            clients={"AGY": True, "CDX": False, "CLD": False, "CUR": False},
            scope_selectable=True,
            project_scope="GLOBAL",
            modes=["SEO & Lighthouse Denetimi", "Tam Tarayıcı Otomasyonu"],
            mode_index=0,
            has_gear=True,
            param_label="Test Edilecek Site URL",
            param_value="http://localhost:3000",
            param_help="Chrome DevTools ve Lighthouse denetiminin varsayılan olarak açıp inceleyeceği yerel veya canlı web adresi.",
            install_cmd="npx -y chrome-devtools-mcp@latest",
            mcp_server_key="chrome-devtools",
            mcp_command="npx",
            mcp_args=["-y", "chrome-devtools-mcp@latest"],
            ai_question_hint="Web sitemi yayına almadan önce mobil görünüm, site hızı (Core Web Vitals), meta etiketleri ve konsol hatalarını denetlerken hangi seçenekler açık olmalı?",
            options=[
                CheckOption(
                    "mobile_emulation",
                    "Mobil görünüm ve duyarlılık (Responsive) testi",
                    True,
                    "✅ AÇARSAN: Siteyi mobil ekran çözünürlüğünde ve dokunmatik modda da test ederek taşan yazıları, küçük butonları ve sabit (sticky) barları denetler.\n⛔ KAPATIRSAN: Yalnızca masaüstü (desktop) ekran boyutunda inceleme yapar.",
                ),
                CheckOption(
                    "lighthouse_vitals",
                    "Core Web Vitals & Site Hızı ölçümü",
                    True,
                    "✅ AÇARSAN: Google Lighthouse motoruyla sayfa açılış hızı (LCP/CLS), SEO ve erişilebilirlik puanlarını ölçüp darboğazları listeler.\n⛔ KAPATIRSAN: Lighthouse hız testi çalıştırılmaz (daha hızlı ama yüzeysel DOM/konsol kontrolü yapılır).",
                ),
                CheckOption(
                    "headless_mode",
                    "Arka planda görünmez (Headless) çalıştır",
                    False,
                    "✅ AÇARSAN: Chrome penceresini ekranda hiç açmadan arka planda sessizce test eder; ekranınızı meşgul etmez.\n⛔ KAPATIRSAN: Test sırasında Chrome penceresini ve yapay zekanın tıklamalarını canlı olarak ekranda izlersiniz.",
                ),
            ],
            usage_count=12,
        ),
    ]


_SKILL_EXACT_DESC: dict[str, str] = {
    "blender-director": "Sahne planlama, kompozisyon ve genel 3D üretim yönetmenliği kurallarını öğretir.",
    "blender-modeler": "Temiz topoloji, kenar akışı (edge flow) ve temel 3D modelleme standartlarını uygular.",
    "hard-surface": "Metal, mekanik parça, silah, vagon/araç ve sert yüzey (bevel/boolean) modelleme kurallarını açar.",
    "prop-artist": "Oyun içi etkileşimli eşya ve çevre objeleri (prop) üretim standartlarını öğretir.",
    "lowpoly-style": "Düşük poligonlu, yüksek performanslı oyun modeli estetiği ve bütçe kurallarını uygular.",
    "psx-horror-style": "PS1/PSX dönemi düşük çözünürlüklü, retro korku dokusu ve atmosfer kurallarını açar.",
    "horror-style": "Korku oyunları için karanlık atmosfer, tekinsiz oranlar ve gerilim odaklı ışık/materyal kurallarını verir.",
    "indie-horror-aesthetics": "Bağımsız (indie) korku oyunlarına özgü kirli/eskitilmiş doku ve sahne dili kurallarını açar.",
    "uv-workflow": "Dikiş izi (seam) gizleme, texel yoğunluğu dengeleme ve düzgün UV açma kurallarını öğretir.",
    "materials": "PBR materyal düğümleri (Roughness, Metallic, Normal) kurulum ve gerçekçi yüzey kurallarını açar.",
    "asset-optimization": "Oyun motoruna atmadan önce poligon, draw-call ve bellek optimizasyonu kurallarını uygular.",
    "unity-export": "Unity için doğru eksen (-Z Forward / Y Up), ölçek (Scale=1.0) ve FBX/GLB aktarım kurallarını zorunlu kılar.",
    "unreal-export": "Unreal Engine uyumlu eksen, pivot, çarpışma (UCX_) ve dışa aktarım kurallarını açar.",
    "godot-export": "Godot Engine uyumlu glTF/GLB sahne ve materyal aktarım kurallarını açar.",
    "export-pipeline": "Model isimlendirme, pivot sıfırlama, transform apply ve hatasız dışa aktarım kontrol listesini çalıştırır.",
    "collision-proxy": "Oyun motoru fiziği için görünmez düşük poligonlu çarpışma (collider) kabuğu üretimini öğretir.",
    "lod-pipeline": "Uzaklığa göre otomatik detay düşüren LOD0/LOD1/LOD2 seviyelerini üretme kurallarını açar.",
    "lighting": "Üç noktalı ışık, dramatik gölge, sis (volumetrics) ve sahne aydınlatma kurallarını öğretir.",
    "rigging": "Karakter ve mekanik objelere kemik (armature) ve ağırlık boyama (weight paint) kurallarını açar.",
    "animation": "Anahtar kare (keyframe), döngüsel oyun animasyonu ve zamanlama kurallarını öğretir.",
    "geometry-nodes": "Blender Geometry Nodes ile parametrik ve prosedürel model üretimi kurallarını açar.",
    "sculpting": "Organik detay ve yüksek poligon heykel (sculpt) iş akışı kurallarını öğretir.",
    "retopology": "Yüksek poligonlu modelleri oyuna uygun temiz düşük poligonlu ağa dönüştürme kurallarını açar.",
    "texture-workflow": "Baking (Normal/AO haritası pişirme) ve doku boyama iş akışı kurallarını öğretir.",
}


def describe_blender_skill(skill_name: str) -> str:
    """94 Blender skill'inin her biri için açıldığında ve kapatıldığında ne olacağını açıklar."""
    core = _SKILL_EXACT_DESC.get(skill_name)
    if not core:
        readable = skill_name.replace("-", " ").title()
        if "horror" in skill_name:
            core = f"'{readable}' korku alt türüne özgü atmosfer, form, ışık ve eskitme kurallarını yapay zekaya öğretir."
        elif skill_name.startswith("genre-"):
            core = f"'{readable.replace('Genre ', '')}' oyun türüne uygun kamera açısı, okunabilirlik ve varlık ölçek kurallarını uygular."
        elif "style" in skill_name or "mood" in skill_name:
            core = f"'{readable}' görsel sanat tarzına uygun renk paleti, oran, gölgelendirme ve yüzey kurallarını açar."
        elif "worlds" in skill_name:
            core = f"'{readable}' dünya ve çevre tasarımı için mimari, bitki örtüsü ve sahne kurulum kurallarını öğretir."
        elif "artist" in skill_name:
            core = f"'{readable}' uzmanlık alanına ait profesyonel 3D üretim ve detaylandırma standartlarını uygular."
        else:
            core = f"Blender'da '{readable}' aşaması için uzman kontrol listesi ve üretim kurallarını devreye sokar."

    return (
        f"✅ AÇARSAN: {core} (Aktif bağlama yalnızca ~350 token ekler).\n"
        f"⛔ KAPATIRSAN: Bu uzmanlık kuralı AI bağlamına yüklenmez; o an bu tarzda çalışmıyorsanız ~350 token tasarruf sağlar."
    )


PROFILES: dict[str, dict[str, Any]] = {
    "unity_game": {
        "title": "🎮 Unity & Shader",
        "desc": "Unity 6 & Grafik: Unity MCP + Pipeline + RenderDoc + Serena + Context7 + Caveman açık; 3D/Web kapalı.",
        "enable": {"unity_mcp", "unity_pipeline", "renderdoc_mcp", "serena", "context7", "caveman"},
    },
    "asset_3d": {
        "title": "🎨 3D & Korku Asset",
        "desc": "3D Üretim: Blender MCP + Seçili Blender Skills + Trellis GPU + glTF-Transform + ElevenLabs SFX açık.",
        "enable": {"blender_mcp", "blender_skills", "trellis", "gltf_transform", "elevenlabs_mcp", "caveman"},
    },
    "web_release": {
        "title": "🌐 Web & Yayın (BLA)",
        "desc": "Web Geliştirme & Yayın: Chrome DevTools/Lighthouse + BLA koruma + Serena + Context7 açık.",
        "enable": {"serena", "chrome_devtools", "bla", "context7", "caveman"},
    },
    "zero_token": {
        "title": "⚡ Sıfır Token (Uyku)",
        "desc": "Tüm MCP şema yükünü kapatır; yalnızca Caveman tasarruf kuralını açık bırakır.",
        "enable": {"caveman"},
    },
}
