"""Tab mixin modules for MainWindow (3 streamlined tabs: Tools, Plugins, Logs)."""
from __future__ import annotations

from .logs_tab import LogsTabMixin
from .plugins_tab import PluginsTabMixin
from .tools_tab import ToolsTabMixin

__all__ = [
    "LogsTabMixin",
    "PluginsTabMixin",
    "ToolsTabMixin",
]
