"""Zero-Qt RAM secret bridge (`aiconomy-bridge.exe` / `AIconomy --mcp-exec <tool_id>`) for zero-plaintext configs."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any

from .security import build_isolated_child_env, split_postgres_uri_secret
from .storage import VAULT_FILENAME, WindowsDpapiVault

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
BRIDGE_MANIFEST_FILENAME = "aiconomy-bridge-specs.json"
BRIDGE_EXE_NAME = "aiconomy-bridge.exe"
_BRIDGE_VERIFIED_SIGS: dict[str, str] = {}
_ACTIVE_JOB_HANDLE: int = 0


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _attach_kill_on_close_job(proc: subprocess.Popen[Any]) -> None:
    """Bind ``proc`` to a Win32 Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE so orphans cannot survive."""
    global _ACTIVE_JOB_HANDLE
    if os.name != "nt":
        return
    try:
        k32 = ctypes.windll.kernel32
        if not _ACTIVE_JOB_HANDLE:
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            h_job = k32.CreateJobObjectW(None, None)
            if not h_job:
                return
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = k32.SetInformationJobObject(
                wintypes.HANDLE(h_job),
                9,  # JobObjectExtendedLimitInformation
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ok:
                k32.CloseHandle(wintypes.HANDLE(h_job))
                return
            _ACTIVE_JOB_HANDLE = int(h_job)
        proc_handle = int(getattr(proc, "_handle", 0) or 0)
        if proc_handle:
            k32.AssignProcessToJobObject(wintypes.HANDLE(_ACTIVE_JOB_HANDLE), wintypes.HANDLE(proc_handle))
    except Exception:
        pass


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
    """Replace ``dst_exe`` safely, retrying across transient Windows Defender scan locks and NTFS image locks."""
    import time

    old_exe = dst_exe.with_suffix(".exe.old")
    try:
        old_exe.unlink(missing_ok=True)
    except OSError:
        pass
    for attempt in range(8):
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
                time.sleep(0.06 * (attempt + 1))
    try:
        if not dst_exe.is_file() and src_or_tmp.is_file():
            shutil.copy2(src_or_tmp, dst_exe)
    except OSError:
        pass
    try:
        src_or_tmp.unlink(missing_ok=True)
    except OSError:
        pass
    return dst_exe.is_file()


def ensure_fast_bridge_binary(data_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    """Materialize the native ``aiconomy-bridge.exe`` into ``<data_dir>/bin`` (<85ms launch, zero _MEI temp)."""
    if os.name != "nt":
        return None
    ddir = data_dir or _default_data_dir()
    bin_dir = ddir / "bin"
    dst_exe = bin_dir / BRIDGE_EXE_NAME
    sha_file = bin_dir / "aiconomy-bridge.sha256"

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
    if _BRIDGE_VERIFIED_SIGS.get(dst_key) == desired_sig and dst_exe.is_file():
        return dst_exe

    cur_sig = ""
    if sha_file.is_file() and dst_exe.is_file():
        try:
            cur_sig = sha_file.read_text(encoding="utf-8").strip()
        except OSError:
            cur_sig = ""

    if cur_sig != desired_sig or not dst_exe.is_file():
        bin_dir.mkdir(parents=True, exist_ok=True)
        tmp_exe = bin_dir / f"aiconomy-bridge-stage-{os.getpid()}.exe"
        built_ok = False
        if bundled is not None and bundled.is_file() and (
            cs_src is None
            or getattr(sys, "frozen", False)
            or bundled.stat().st_mtime >= cs_src.stat().st_mtime
        ):
            shutil.copy2(bundled, tmp_exe)
            built_ok = tmp_exe.is_file()
        elif cs_src is not None:
            csc = _find_csc_compiler()
            if csc is not None:
                try:
                    csc_args = [
                        str(csc),
                        "/nologo",
                        "/optimize+",
                        "/target:exe",
                        "/r:System.Web.Extensions.dll",
                        f"/out:{tmp_exe}",
                        str(cs_src),
                    ]
                    proc = subprocess.run(
                        csc_args,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30,
                        creationflags=NO_WINDOW,
                    )
                    built_ok = proc.returncode == 0 and tmp_exe.is_file()
                except Exception:
                    built_ok = False
            if not built_ok and bundled is not None and bundled.is_file():
                shutil.copy2(bundled, tmp_exe)
                built_ok = tmp_exe.is_file()

        if built_ok and _replace_exe_safely(tmp_exe, dst_exe):
            try:
                sha_file.write_text(desired_sig + "\n", encoding="utf-8")
            except OSError:
                pass

    if not dst_exe.is_file():
        return None

    for attempt in range(2):
        try:
            ping = subprocess.run(
                [str(dst_exe), "--ping"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                creationflags=NO_WINDOW,
            )
            if ping.returncode == 0 and "AICONOMY_BRIDGE_OK" in ping.stdout:
                _BRIDGE_VERIFIED_SIGS[dst_key] = desired_sig
                return dst_exe
        except Exception:
            if attempt == 0:
                import time

                time.sleep(0.25)
    return None


def _pipe_device_path() -> str:
    custom = (os.environ.get("AICONOMY_PIPE_NAME") or "").strip()
    if custom:
        return rf"\\.\pipe\{custom}"
    suffix = (os.environ.get("USERNAME") or "user").replace(" ", "_")
    return rf"\\.\pipe\AIconomy.SingleInstance.{suffix}"


def _request_launch_from_running_gui(
    tool_id: str,
    data_dir: pathlib.Path,
) -> tuple[dict[str, Any] | None, bool, bool]:
    """Request authoritative RAM ``(cmd, args, env)`` launch spec from the unlocked AIconomy GUI.

    Returns ``(spec_dict, is_locked, is_denied)``.
    """
    pipe_path = _pipe_device_path()
    dir_b64 = base64.b64encode(str(data_dir.resolve()).encode("utf-8")).decode("ascii")
    try:
        with open(pipe_path, "r+b", buffering=0) as pipe:
            pipe.write(f"resolve_launch:{tool_id}|{dir_b64}".encode("ascii"))
            chunks: list[bytes] = []
            total_read = 0
            while total_read < 524288:
                try:
                    chunk = pipe.read(16384)
                except OSError:
                    if chunks:
                        break
                    raise
                if not chunk:
                    break
                chunks.append(chunk)
                total_read += len(chunk)
                if b"\n" in chunk:
                    break
            resp = b"".join(chunks)
            txt = resp.decode("ascii", errors="ignore").strip()
            if txt == "LOCKED":
                return None, True, False
            if txt == "DENIED" or not txt:
                return None, False, True
            if txt.startswith("LAUNCH:"):
                b64_part = txt.split(":", 1)[1].strip()
                raw_json = base64.b64decode(b64_part.encode("ascii")).decode("utf-8")
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict):
                    return parsed, False, False
    except OSError:
        return None, True, False
    except Exception:
        return None, False, True
    return None, False, True


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


def _unwrap_node_batch(exe_path: str, cmd_args: list[str]) -> tuple[str, list[str]]:
    if os.name != "nt":
        return exe_path, cmd_args
    p = pathlib.Path(exe_path)
    low = p.name.lower()
    if low not in ("npx.cmd", "npm.cmd"):
        return exe_path, cmd_args
    node_exe = p.parent / "node.exe"
    cli_js = p.parent / "node_modules" / "npm" / "bin" / ("npx-cli.js" if low == "npx.cmd" else "npm-cli.js")
    if node_exe.is_file() and cli_js.is_file():
        return str(node_exe), [str(cli_js), *cmd_args]
    return exe_path, cmd_args


def _resolve_from_manifest(
    tool_id: str,
    data_dir: pathlib.Path,
) -> tuple[str, str, list[str], dict[str, str], str] | int | None:
    """Fast pre-catalog path reading ``aiconomy-bridge-specs.json`` (<5ms) when vault is unprotected."""
    vault = WindowsDpapiVault(data_dir / VAULT_FILENAME)
    if vault.is_locked():
        auth_spec, is_locked, _is_denied = _request_launch_from_running_gui(tool_id, data_dir)
        if auth_spec is None:
            if is_locked:
                _write_err(
                    f"AIconomy vault is locked with a Master Passphrase. Open AIconomy and unlock your vault before starting '{tool_id}'.\n"
                )
            else:
                _write_err(
                    f"AIconomy --mcp-exec: launch denied for '{tool_id}' (ensure Tools are Started and tool is enabled in AIconomy).\n"
                )
            return 3
        t_name = str(auth_spec.get("name") or tool_id)
        r_cmd = str(auth_spec.get("cmd") or "").strip()
        if not r_cmd:
            return 2
        c_args = [str(x) for x in (auth_spec.get("args") or [])]
        t_env = {str(k): str(v) for k, v in (auth_spec.get("env") or {}).items()}
        v_key = str(auth_spec.get("vault_key") or "").strip()
        return t_name, r_cmd, c_args, t_env, v_key

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
    secret_env_var = str(spec.get("secret_env_var") or vault_key).strip()
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
                encoding="utf-8",
                errors="replace",
                timeout=4,
                env=build_isolated_child_env({}),
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
        secret_val = vault.get_secret(vault_key)
        if not secret_val and vault_req:
            _write_err(f"AIconomy --mcp-exec: missing required credential for '{tool_name}'.\n")
            return 3

    if secret_val:
        if secret_flag == "__PG_POSITIONAL__":
            clean_pg, pg_pw = split_postgres_uri_secret(secret_val)
            if clean_pg and clean_pg not in cmd_args:
                cmd_args.append(clean_pg)
            if pg_pw:
                tool_env["PGPASSWORD"] = pg_pw
        elif secret_flag == "__POSITIONAL__":
            if secret_val not in cmd_args:
                cmd_args.append(secret_val)
        elif secret_flag and secret_flag not in cmd_args:
            cmd_args.extend([secret_flag, secret_val])
        if secret_env_var and secret_flag != "__PG_POSITIONAL__":
            tool_env[secret_env_var] = secret_val

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
        # Lazy fallback for ad-hoc CLI invocations before a manifest is written (unprotected vault only)
        from .catalog import build_default_catalog
        from .mcp_config import build_effective_stdio_spec
        from .storage import STATE_FILENAME, StateStore

        vault = WindowsDpapiVault(data_dir / VAULT_FILENAME)
        tools = build_default_catalog(data_dir=data_dir)
        store = StateStore(data_dir / STATE_FILENAME, vault=vault)
        store.load_into(tools, vault=vault)

        target = next((t for t in tools if t.id == tool_id), None)
        if target is None:
            _write_err(f"AIconomy --mcp-exec: unknown tool '{tool_id}'.\n")
            return 2

        vault_key = target.vault_key_name
        spec = build_effective_stdio_spec(target, vault, wrap_windows_npx=False)
        if spec is None:
            _write_err(f"AIconomy --mcp-exec: missing required credential for '{target.name}'.\n")
            return 3
        raw_cmd, cmd_args, tool_env = spec

    exe_path = _resolve_executable(raw_cmd)
    exe_path, cmd_args = _unwrap_node_batch(exe_path, cmd_args)
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
        _attach_kill_on_close_job(proc)
        return int(proc.wait())
    except FileNotFoundError:
        _write_err(f"AIconomy --mcp-exec: executable not found: {raw_cmd}\n")
        return 127
    except KeyboardInterrupt:
        return 0
