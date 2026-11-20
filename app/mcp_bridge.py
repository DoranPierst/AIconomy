"""Zero-Qt RAM secret bridge (`aiconomy-bridge.exe` / `AIconomy --mcp-exec <tool_id>`) for zero-plaintext configs."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any

from .security import build_isolated_child_env
from .storage import VAULT_FILENAME, WindowsDpapiVault

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
BRIDGE_MANIFEST_FILENAME = "aiconomy-bridge-specs.json"
BRIDGE_EXE_NAME = "aiconomy-bridge.exe"
_BRIDGE_VERIFIED_PATHS: set[str] = set()


def _default_data_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        root = pathlib.Path(sys.executable).resolve().parent
    else:
        root = pathlib.Path(__file__).resolve().parent.parent
    if (root / "portable.txt").is_file():
        return root / "data"
    base = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
    return pathlib.Path(base) / "AIconomy" / "data"


def _bundled_bridge_exe() -> pathlib.Path | None:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            cand = pathlib.Path(meipass) / "assets" / BRIDGE_EXE_NAME
            if cand.is_file():
                return cand
        sib = pathlib.Path(sys.executable).resolve().parent / "assets" / BRIDGE_EXE_NAME
        if sib.is_file():
            return sib
    cand_dev = pathlib.Path(__file__).resolve().parent.parent / "assets" / BRIDGE_EXE_NAME
    return cand_dev if cand_dev.is_file() else None


def _bridge_cs_source() -> pathlib.Path | None:
    cand = pathlib.Path(__file__).resolve().parent / "bridge_host.cs"
    return cand if cand.is_file() else None


def _find_csc_compiler() -> pathlib.Path | None:
    windir = pathlib.Path(os.environ.get("WINDIR", r"C:\Windows"))
    for sub in ("Framework64", "Framework"):
        cand = windir / "Microsoft.NET" / sub / "v4.0.30319" / "csc.exe"
        if cand.is_file():
            return cand
    return None


def _replace_exe_safely(src_or_tmp: pathlib.Path, dst_exe: pathlib.Path) -> bool:
    """Replace ``dst_exe`` even if a running MCP bridge holds an NTFS image lock on it."""
    old_exe = dst_exe.with_suffix(".exe.old")
    try:
        old_exe.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        os.replace(src_or_tmp, dst_exe)
        return True
    except OSError:
        try:
            if dst_exe.is_file():
                os.replace(dst_exe, old_exe)
            os.replace(src_or_tmp, dst_exe)
            return True
        except OSError:
            try:
                src_or_tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return dst_exe.is_file()


def ensure_fast_bridge_binary(data_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    """Materialize the ~15KB native ``aiconomy-bridge.exe`` into ``<data_dir>/bin`` (<85ms launch, zero _MEI temp)."""
    if os.name != "nt":
        return None
    ddir = data_dir or _default_data_dir()
    bin_dir = ddir / "bin"
    dst_exe = bin_dir / BRIDGE_EXE_NAME
    sha_file = bin_dir / "aiconomy-bridge.sha256"

    # Best-effort cleanup of previous swapped bridge binary once unlocked
    old_exe = dst_exe.with_suffix(".exe.old")
    if old_exe.is_file():
        try:
            old_exe.unlink()
        except OSError:
            pass

    cs_src = _bridge_cs_source()
    bundled = _bundled_bridge_exe()
    if cs_src is not None:
        desired_sig = "cs:" + hashlib.sha256(cs_src.read_bytes()).hexdigest()
    elif bundled is not None:
        desired_sig = "exe:" + hashlib.sha256(bundled.read_bytes()).hexdigest()
    else:
        return dst_exe if dst_exe.is_file() else None

    dst_key = str(dst_exe.resolve())
    if dst_key in _BRIDGE_VERIFIED_PATHS and dst_exe.is_file():
        return dst_exe

    cur_sig = ""
    if sha_file.is_file() and dst_exe.is_file():
        try:
            cur_sig = sha_file.read_text(encoding="utf-8").strip()
        except OSError:
            cur_sig = ""

    if cur_sig != desired_sig or not dst_exe.is_file():
        bin_dir.mkdir(parents=True, exist_ok=True)
        tmp_exe = bin_dir / f".{BRIDGE_EXE_NAME}.{os.getpid()}.tmp"
        built_ok = False
        # Prefer bundled precompiled bridge when signature matches or cs compiler unavailable
        if bundled is not None and (cs_src is None or not getattr(sys, "frozen", False)):
            # In dev mode, recompile from bridge_host.cs if csc.exe exists so edits take effect automatically
            if cs_src is not None:
                csc = _find_csc_compiler()
                if csc is not None:
                    proc = subprocess.run(
                        [
                            str(csc),
                            "/nologo",
                            "/optimize+",
                            "/target:exe",
                            "/r:System.Web.Extensions.dll",
                            f"/out:{tmp_exe}",
                            str(cs_src),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        creationflags=NO_WINDOW,
                    )
                    built_ok = proc.returncode == 0 and tmp_exe.is_file()
            if not built_ok and bundled.is_file():
                shutil.copy2(bundled, tmp_exe)
                built_ok = tmp_exe.is_file()
        elif bundled is not None and bundled.is_file():
            shutil.copy2(bundled, tmp_exe)
            built_ok = tmp_exe.is_file()
        elif cs_src is not None:
            csc = _find_csc_compiler()
            if csc is not None:
                proc = subprocess.run(
                    [
                        str(csc),
                        "/nologo",
                        "/optimize+",
                        "/target:exe",
                        "/r:System.Web.Extensions.dll",
                        f"/out:{tmp_exe}",
                        str(cs_src),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    creationflags=NO_WINDOW,
                )
                built_ok = proc.returncode == 0 and tmp_exe.is_file()

        if built_ok and _replace_exe_safely(tmp_exe, dst_exe):
            try:
                sha_file.write_text(desired_sig + "\n", encoding="utf-8")
            except OSError:
                pass

    if not dst_exe.is_file():
        return None

    try:
        ping = subprocess.run(
            [str(dst_exe), "--ping"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=NO_WINDOW,
        )
        if ping.returncode == 0 and "AICONOMY_BRIDGE_OK" in ping.stdout:
            _BRIDGE_VERIFIED_PATHS.add(dst_key)
            return dst_exe
    except Exception:
        pass
    return None


def _request_tool_secret_from_running_gui(tool_id: str) -> tuple[str, bool]:
    """Request ONLY ``tool_id``'s decrypted secret over the kernel-PID-verified local pipe (zero master entropy exposure).

    Returns ``(secret_value, is_locked_or_denied)``.
    """
    suffix = (os.environ.get("USERNAME") or "user").replace(" ", "_")
    pipe_path = rf"\\.\pipe\AIconomy.SingleInstance.{suffix}"
    try:
        with open(pipe_path, "r+b", buffering=0) as pipe:
            pipe.write(f"resolve_secret:{tool_id}".encode("ascii"))
            resp = pipe.read(4096)
            txt = resp.decode("ascii", errors="ignore").strip()
            if txt in ("LOCKED", "DENIED"):
                return "", True
            if txt == "EMPTY":
                return "", False
            if txt.startswith("SECRET:"):
                b64_part = txt.split(":", 1)[1].strip()
                if not b64_part:
                    return "", False
                return base64.b64decode(b64_part.encode("ascii")).decode("utf-8"), False
    except OSError:
        return "", True
    return "", True


def _write_err(msg: str) -> None:
    stream = getattr(sys, "stderr", None)
    if stream is not None:
        try:
            stream.write(msg)
            stream.flush()
        except Exception:
            pass


def _valid_stdio_stream(stream: object) -> object:
    """Return a valid inheritable stream/fd for subprocess.Popen even under PyInstaller --windowed."""
    if stream is not None:
        try:
            fd = stream.fileno()  # type: ignore[attr-defined]
            if isinstance(fd, int) and fd >= 0:
                return stream
        except Exception:
            pass
    return subprocess.DEVNULL


def _resolve_executable(cmd: str) -> str:
    if os.path.isfile(cmd):
        return os.path.abspath(cmd)
    if os.name == "nt":
        for ext in (".cmd", ".exe", ".bat", ""):
            found = shutil.which(f"{cmd}{ext}")
            if found:
                return found
    return shutil.which(cmd) or cmd


def _resolve_from_manifest(
    tool_id: str,
    data_dir: pathlib.Path,
) -> tuple[str, str, list[str], dict[str, str], str] | int | None:
    """Fast pre-catalog path reading ``aiconomy-bridge-specs.json`` (<5ms).

    Returns ``(tool_name, raw_cmd, cmd_args, tool_env, vault_key)`` on success,
    an integer exit code on credential/lock error, or ``None`` if manifest has no entry.
    """
    manifest_path = data_dir / BRIDGE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        tools_map = doc.get("tools") if isinstance(doc, dict) else None
        if not isinstance(tools_map, dict) or tool_id not in tools_map:
            return None
        spec: dict[str, Any] = tools_map[tool_id]
        if not isinstance(spec, dict):
            return None
    except Exception:
        return None

    tool_name = str(spec.get("name") or tool_id)
    raw_cmd = str(spec.get("cmd") or "").strip()
    if not raw_cmd:
        return None
    cmd_args = [str(x) for x in (spec.get("args") or [])]
    tool_env = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
    vault_key = str(spec.get("vault_key") or "").strip()
    vault_req = bool(spec.get("vault_required", False))
    secret_flag = str(spec.get("secret_arg_flag") or "").strip()
    oauth_mode = bool(spec.get("oauth_mode", False))
    oauth_cli = str(spec.get("oauth_cli_bin") or "").strip()
    oauth_targs = [str(x) for x in (spec.get("oauth_token_args") or [])]

    secret_val = ""
    if oauth_mode and oauth_cli and vault_key:
        cli_exe = _resolve_executable(oauth_cli)
        try:
            proc = subprocess.run(
                [cli_exe, *oauth_targs],
                capture_output=True,
                text=True,
                timeout=4,
                creationflags=NO_WINDOW,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                secret_val = proc.stdout.strip().splitlines()[0].strip()
        except Exception:
            pass
        if not secret_val and vault_req:
            _write_err(f"AIconomy --mcp-exec: OAuth CLI token unavailable for '{tool_name}'.\n")
            return 3
    elif vault_key:
        vault = WindowsDpapiVault(data_dir / VAULT_FILENAME)
        if vault.is_locked():
            has_entry = vault.has_key_entry(vault_key)
            secret_val, locked_err = _request_tool_secret_from_running_gui(tool_id)
            if locked_err and (vault_req or has_entry):
                _write_err(
                    f"AIconomy vault is locked with a Master Passphrase. Open AIconomy and unlock your vault before starting '{tool_name}'.\n"
                )
                return 3
        else:
            secret_val = vault.get_secret(vault_key)
        if not secret_val and vault_req:
            _write_err(f"AIconomy --mcp-exec: missing required credential for '{tool_name}'.\n")
            return 3

    if secret_val:
        if secret_flag and secret_flag not in cmd_args:
            cmd_args.extend([secret_flag, secret_val])
        if vault_key:
            tool_env[vault_key] = secret_val

    return tool_name, raw_cmd, cmd_args, tool_env, vault_key


def run_mcp_exec_cli(argv: list[str]) -> int:
    """Launch an MCP stdio server with its DPAPI/OAuth secret injected purely in RAM."""
    if not argv:
        _write_err("Usage: AIconomy --mcp-exec <tool_id> [--data-dir <path>]\n")
        return 2

    tool_id = argv[0].strip()
    data_dir = _default_data_dir()
    idx = 1
    while idx < len(argv):
        if argv[idx] == "--data-dir" and idx + 1 < len(argv):
            data_dir = pathlib.Path(argv[idx + 1])
            idx += 2
        else:
            idx += 1

    fast_res = _resolve_from_manifest(tool_id, data_dir)
    if isinstance(fast_res, int):
        return fast_res

    if fast_res is not None:
        _tool_name, raw_cmd, cmd_args, tool_env, vault_key = fast_res
    else:
        # Lazy fallback for ad-hoc CLI invocations before a manifest is written
        from .catalog import build_default_catalog
        from .mcp_config import build_effective_stdio_spec
        from .storage import STATE_FILENAME, StateStore

        tools = build_default_catalog()
        store = StateStore(data_dir / STATE_FILENAME)
        store.load_into(tools)

        target = next((t for t in tools if t.id == tool_id), None)
        if target is None:
            _write_err(f"AIconomy --mcp-exec: unknown tool '{tool_id}'.\n")
            return 2

        vault = WindowsDpapiVault(data_dir / VAULT_FILENAME)
        vault_key = target.vault_key_name
        if vault.is_locked():
            has_entry = bool(vault_key and vault.has_key_entry(vault_key))
            sec_pipe, locked_err = _request_tool_secret_from_running_gui(tool_id)
            if locked_err and (target.vault_key_required or has_entry):
                _write_err(
                    f"AIconomy vault is locked with a Master Passphrase. Open AIconomy and unlock your vault before starting '{target.name}'.\n"
                )
                return 3
            spec = build_effective_stdio_spec(target, vault, wrap_windows_npx=False, override_secret=sec_pipe)
        else:
            spec = build_effective_stdio_spec(target, vault, wrap_windows_npx=False)

        if spec is None:
            _write_err(f"AIconomy --mcp-exec: missing required credential for '{target.name}'.\n")
            return 3
        raw_cmd, cmd_args, tool_env = spec

    exe_path = _resolve_executable(raw_cmd)
    child_env = build_isolated_child_env(
        tool_env,
        allowed_secret_key=vault_key,
    )

    try:
        proc = subprocess.Popen(
            [exe_path, *cmd_args],
            stdin=_valid_stdio_stream(getattr(sys, "stdin", None)),
            stdout=_valid_stdio_stream(getattr(sys, "stdout", None)),
            stderr=_valid_stdio_stream(getattr(sys, "stderr", None)),
            env=child_env,
            creationflags=NO_WINDOW,
        )
        return int(proc.wait())
    except FileNotFoundError:
        _write_err(f"AIconomy --mcp-exec: executable not found: {raw_cmd}\n")
        return 127
    except KeyboardInterrupt:
        return 0
