"""Tab mixin modules for MainWindow."""
from __future__ import annotations

from .logs_tab import LogsTabMixin
from .plugins_tab import PluginsTabMixin
from .repo_tab import RepoTabMixin
from .tools_tab import ToolsTabMixin
from .vault_tab import VaultTabMixin

__all__ = [
    "LogsTabMixin",
    "PluginsTabMixin",
    "RepoTabMixin",
    "ToolsTabMixin",
    "VaultTabMixin",
]
