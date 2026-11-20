"""Thread-safe Qt signal bridge between background workers and the UI thread."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal


def safe_emit(sig: Any, *args: Any) -> None:
    """Emit a Qt signal safely, ignoring shutdown races if the QObject was already destroyed."""
    try:
        sig.emit(*args)
    except RuntimeError:
        pass


class WorkerBridge(QObject):
    health_done = Signal(object, object, bool)  # (results_list, live_map_or_None, silent)
    repo_done = Signal(object)
    plugin_check_done = Signal(object, bool)  # (list[PluginCheckResult], manual)
    update_progress = Signal(int, int, str)
    update_item_done = Signal(str, bool, str, str, str, str)  # (tool_id, ok, prev_v, target_v, msg, raw_log)
    update_all_done = Signal(int, int, str)
    app_check_done = Signal(object)
    conn_test_row = Signal(int, int, bool, int, str, str, str)  # (gen, row, ok, ms, msg, raw, badge_state)
    conn_test_cfg = Signal(int, bool, str)  # (gen, parse_ok, cfg_banner_msg)
    conn_test_done = Signal(int, bool)  # (gen, was_dry_run)
    vram_done = Signal(str, int, int)
    dcc_done = Signal(object)
    port_kill_done = Signal(int, bool, str)
    app_dl_progress = Signal(int, int)
    app_apply_done = Signal(bool, str, str)
    runtime_transition_done = Signal(str, object, object, str)  # (target_state, health_out, live_map, msg)
    lib_install_progress = Signal(int, int, str)  # (idx, total, tool_name)
    lib_install_item_done = Signal(str, bool, str, str, str, bool)  # (tool_id, ok, new_ver, msg, raw_log, enable_after)
    lib_install_all_done = Signal(int, int)  # (ok_cnt, fail_cnt)
    lib_uninstall_done = Signal(str, bool, str, str)  # (tool_id, ok, msg, raw_log)
    schema_measure_done = Signal(object, int)  # (measured_dict, count)
    auto_heal_done = Signal(bool, str, str, str)  # (ok, tool_name, summary, raw_detail)
