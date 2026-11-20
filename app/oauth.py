"""Browser OAuth 2.1 remote MCP endpoints and official CLI OAuth sign-in helpers (EN & TR)."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass

import psutil

from .security import build_isolated_child_env

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


@dataclass(frozen=True)
class OAuthSupportSpec:
    kind: str  # "remote_mcp" | "cli_login"
    provider_label: str
    remote_mcp_url: str = ""
    cli_binary: str = ""
    login_args: tuple[str, ...] = ()
    status_args: tuple[str, ...] = ()
    token_args: tuple[str, ...] = ()


# Curated official OAuth 2.1 PKCE remote MCP endpoints & official CLI browser OAuth flows
OAUTH_TOOL_SPECS: dict[str, OAuthSupportSpec] = {
    # Official Remote OAuth 2.1 MCP servers (via mcp-remote -> opens browser consent automatically)
    "cloudflare_mcp": OAuthSupportSpec(
        kind="remote_mcp",
        provider_label="Cloudflare OAuth",
        remote_mcp_url="https://observability.mcp.cloudflare.com/sse",
    ),
    "linear_mcp": OAuthSupportSpec(
        kind="remote_mcp",
        provider_label="Linear OAuth",
        remote_mcp_url="https://mcp.linear.app/sse",
    ),
    "sentry_mcp": OAuthSupportSpec(
        kind="remote_mcp",
        provider_label="Sentry OAuth",
        remote_mcp_url="https://mcp.sentry.dev/mcp",
    ),
    "notion_mcp": OAuthSupportSpec(
        kind="remote_mcp",
        provider_label="Notion OAuth",
        remote_mcp_url="https://mcp.notion.com/mcp",
    ),
    "atlassian_mcp": OAuthSupportSpec(
        kind="remote_mcp",
        provider_label="Atlassian OAuth",
        remote_mcp_url="https://mcp.atlassian.com/v1/sse",
    ),
    "supabase_mcp": OAuthSupportSpec(
        kind="remote_mcp",
        provider_label="Supabase OAuth",
        remote_mcp_url="https://mcp.supabase.com/mcp",
    ),
    "netlify_mcp": OAuthSupportSpec(
        kind="remote_mcp",
        provider_label="Netlify OAuth",
        remote_mcp_url="https://netlify-mcp.netlify.app/sse",
    ),
    "stripe_mcp": OAuthSupportSpec(
        kind="remote_mcp",
        provider_label="Stripe OAuth",
        remote_mcp_url="https://mcp.stripe.com",
    ),
    # Official CLI Browser OAuth sign-in flows
    "github_mcp": OAuthSupportSpec(
        kind="cli_login",
        provider_label="GitHub CLI OAuth",
        cli_binary="gh",
        login_args=("auth", "login", "--web"),
        status_args=("auth", "status"),
        token_args=("auth", "token"),
    ),
    "gh_actions_mcp": OAuthSupportSpec(
        kind="cli_login",
        provider_label="GitHub CLI OAuth",
        cli_binary="gh",
        login_args=("auth", "login", "--web"),
        status_args=("auth", "status"),
        token_args=("auth", "token"),
    ),
    "azure_mcp": OAuthSupportSpec(
        kind="cli_login",
        provider_label="Azure CLI OAuth",
        cli_binary="az",
        login_args=("login",),
        status_args=("account", "show"),
    ),
    "gcloud_run_mcp": OAuthSupportSpec(
        kind="cli_login",
        provider_label="Google Cloud OAuth",
        cli_binary="gcloud",
        login_args=("auth", "login"),
        status_args=("auth", "print-access-token"),
    ),
    "snyk_mcp": OAuthSupportSpec(
        kind="cli_login",
        provider_label="Snyk Browser OAuth",
        cli_binary="npx",
        login_args=("-y", "snyk", "auth"),
    ),
    "railway_mcp": OAuthSupportSpec(
        kind="cli_login",
        provider_label="Railway Browser OAuth",
        cli_binary="npx",
        login_args=("-y", "@railway/cli", "login"),
    ),
}


def get_oauth_spec(tool_id: str) -> OAuthSupportSpec | None:
    return OAUTH_TOOL_SPECS.get(tool_id)


def supports_oauth(tool_id: str) -> bool:
    return tool_id in OAUTH_TOOL_SPECS


def _find_cli_bin(binary: str) -> str:
    if os.name == "nt":
        for ext in (".exe", ".cmd", ".bat", ""):
            found = shutil.which(f"{binary}{ext}")
            if found:
                return found
    return shutil.which(binary) or ""


def resolve_cli_oauth_token(tool_id: str) -> str:
    """Resolve a live token from an authenticated local CLI (e.g. `gh auth token`) in RAM."""
    spec = OAUTH_TOOL_SPECS.get(tool_id)
    if spec is None or spec.kind != "cli_login" or not spec.token_args:
        return ""
    exe = _find_cli_bin(spec.cli_binary)
    if not exe:
        return ""
    try:
        proc = subprocess.run(
            [exe, *spec.token_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            env=build_isolated_child_env({}),
            creationflags=NO_WINDOW,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    return ""


def check_cli_oauth_ready(tool_id: str) -> bool:
    """Return True when the tool's CLI OAuth session is currently signed in."""
    spec = OAUTH_TOOL_SPECS.get(tool_id)
    if spec is None:
        return False
    if spec.kind == "remote_mcp":
        return True
    if not spec.status_args:
        return bool(_find_cli_bin(spec.cli_binary))
    exe = _find_cli_bin(spec.cli_binary)
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, *spec.status_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            env=build_isolated_child_env({}),
            creationflags=NO_WINDOW,
        )
        return proc.returncode == 0
    except Exception:
        return False


def launch_browser_oauth_flow(tool_id: str, lang: str = "en") -> tuple[bool, str]:
    """Trigger the non-blocking browser OAuth consent flow for a supported tool."""
    is_tr = lang == "tr"
    spec = OAUTH_TOOL_SPECS.get(tool_id)
    if spec is None:
        return (
            False,
            "Bu araç için tarayıcı OAuth desteği yok." if is_tr else "Browser OAuth is not supported for this tool.",
        )

    if spec.kind == "remote_mcp":
        npx_bin = _find_cli_bin("npx")
        if not npx_bin:
            return (
                False,
                "OAuth köprüsü için Node.js (npx) gerekli." if is_tr else "Node.js (npx) is required for mcp-remote OAuth.",
            )
        try:
            proc = subprocess.Popen(
                [npx_bin, "-y", "mcp-remote", spec.remote_mcp_url],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=build_isolated_child_env({}),
                creationflags=NO_WINDOW,
            )

            def _reap_oauth_helper(p: subprocess.Popen[bytes]) -> None:
                try:
                    p.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    try:
                        parent = psutil.Process(p.pid)
                        for ch in parent.children(recursive=True):
                            try:
                                ch.terminate()
                            except Exception:
                                pass
                        parent.terminate()
                    except Exception:
                        pass
                finally:
                    if p.stdin:
                        try:
                            p.stdin.close()
                        except Exception:
                            pass

            threading.Thread(target=_reap_oauth_helper, args=(proc,), daemon=True).start()
            msg = (
                f"{spec.provider_label} tarayıcı yetkilendirmesi başlatıldı (tarayıcınızda İzin Ver'e tıklayın)."
                if is_tr
                else f"Launched {spec.provider_label} in your browser (click Authorize in the opened tab)."
            )
            return True, msg
        except Exception as exc:
            return False, (f"OAuth başlatılamadı: {exc}" if is_tr else f"Failed to launch OAuth: {exc}")

    exe = _find_cli_bin(spec.cli_binary)
    if not exe:
        msg = (
            f"'{spec.cli_binary}' CLI aracı bulunamadı. Lütfen önce {spec.cli_binary} kurun veya API anahtarı modunu kullanın."
            if is_tr
            else f"'{spec.cli_binary}' CLI was not found on PATH. Install '{spec.cli_binary}' first or use API key mode."
        )
        return False, msg

    try:
        # Open an interactive terminal/browser login for CLI OAuth (`gh auth login --web`, `az login`, etc.)
        subprocess.Popen([exe, *spec.login_args], env=build_isolated_child_env({}))
        msg = (
            f"{spec.provider_label} giriş penceresi açıldı."
            if is_tr
            else f"Opened {spec.provider_label} sign-in flow."
        )
        return True, msg
    except Exception as exc:
        return False, (f"OAuth başlatılamadı: {exc}" if is_tr else f"Failed to start OAuth: {exc}")
