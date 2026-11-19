"""Zero-Qt RAM secret bridge (`AIconomy --mcp-exec <tool_id>`) for zero-plaintext client configs."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

from .catalog import build_default_catalog
from .mcp_config import build_effective_stdio_spec
from .security import build_isolated_child_env
from .storage import STATE_FILENAME, VAULT_FILENAME, StateStore, WindowsDpapiVault

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _default_data_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        root = pathlib.Path(sys.executable).resolve().parent
    else:
        root = pathlib.Path(__file__).resolve().parent.parent
    if (root / "portable.txt").is_file():
        return root / "data"
    base = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
    return pathlib.Path(base) / "AIconomy" / "data"


def _request_entropy_from_running_gui() -> str:
    """If the user enabled a Master Passphrase, fetch unlocked entropy over the user-scoped local pipe."""
    suffix = (os.environ.get("USERNAME") or "user").replace(" ", "_")
    pipe_path = rf"\\.\pipe\AIconomy.SingleInstance.{suffix}"
    try:
        with open(pipe_path, "r+b", buffering=0) as pipe:
            pipe.write(b"request_entropy")
            resp = pipe.read(256)
            txt = resp.decode("ascii", errors="ignore").strip()
            if txt.startswith("ENTROPY:"):
                return txt.split(":", 1)[1].strip()
    except OSError:
        return ""
    return ""


def _write_err(msg: str) -> None:
    stream = getattr(sys, "stderr", None)
    if stream is not None:
        try:
            stream.write(msg)
            stream.flush()
        except Exception:
            pass


def _valid_stdio_stream(stream: object, is_input: bool = False) -> object:
    """Return a valid inheritable stream/fd for subprocess.Popen even under PyInstaller --windowed."""
    if stream is not None:
        try:
            fd = stream.fileno()  # type: ignore[attr-defined]
            if isinstance(fd, int) and fd >= 0:
                return stream
        except Exception:
            pass
    return subprocess.DEVNULL if is_input else subprocess.DEVNULL


def _resolve_executable(cmd: str) -> str:
    if os.name == "nt":
        for ext in (".cmd", ".exe", ".bat", ""):
            found = shutil.which(f"{cmd}{ext}")
            if found:
                return found
    return shutil.which(cmd) or cmd


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

    tools = build_default_catalog()
    store = StateStore(data_dir / STATE_FILENAME)
    store.load_into(tools)

    target = next((t for t in tools if t.id == tool_id), None)
    if target is None:
        _write_err(f"AIconomy --mcp-exec: unknown tool '{tool_id}'.\n")
        return 2

    vault = WindowsDpapiVault(data_dir / VAULT_FILENAME)
    if vault.is_locked():
        ent_hex = _request_entropy_from_running_gui()
        if ent_hex:
            vault.unlock_with_entropy_hex(ent_hex)
        if vault.is_locked():
            _write_err(
                f"AIconomy vault is locked with a Master Passphrase. Open AIconomy and unlock your vault before starting '{target.name}'.\n"
            )
            return 3

    spec = build_effective_stdio_spec(target, vault, wrap_windows_npx=False)
    if spec is None:
        _write_err(f"AIconomy --mcp-exec: missing required credential for '{target.name}'.\n")
        return 3

    raw_cmd, cmd_args, tool_env = spec
    exe_path = _resolve_executable(raw_cmd)
    child_env = build_isolated_child_env(
        tool_env,
        allowed_secret_key=target.vault_key_name,
    )

    try:
        proc = subprocess.Popen(
            [exe_path, *cmd_args],
            stdin=_valid_stdio_stream(getattr(sys, "stdin", None), is_input=True),
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
