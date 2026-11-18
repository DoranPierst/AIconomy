"""Thread-safe Qt signal bridge between background workers and the UI thread."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class WorkerBridge(QObject):
    health_done = Signal(object, object, bool)  # (results_list, live_map_or_None, silent)
    repo_done = Signal(object)
    plugin_check_done = Signal(object, bool)  # (list[PluginCheckResult], manual)
    update_progress = Signal(int, int, str)
    update_item_done = Signal(str, bool, str, str, str, str)  # (tool_id, ok, prev_v, target_v, msg, raw_log)
    update_all_done = Signal(int, int, str)
    app_check_done = Signal(object)
    conn_test_row = Signal(int, bool, int, str, str)
    conn_test_done = Signal()
    vram_done = Signal(str, int, int)
    dcc_done = Signal(object)
    port_kill_done = Signal(int, bool, str)
    app_dl_progress = Signal(int, int)
    app_apply_done = Signal(bool, str, str)
