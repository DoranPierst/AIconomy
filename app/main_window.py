"""Compatibility facade re-exporting modularized UI components."""
from __future__ import annotations

from .ui.dialogs import (
    AiPasteDialog,
    AppUpdateDialog,
    BlenderSkillsDialog,
    ConnectionTestDialog,
    ToolGearDialog,
    ToolInfoDialog,
)
from .ui.main_window import MainWindow
from .ui.theme import DARK_QSS, LIGHT_QSS, create_app_icon
from .ui.widgets import AiMatrixHeaderView, FullRowHoverDelegate, HoverTableWidget
from .ui.workers import WorkerBridge

__all__ = [
    "AiMatrixHeaderView",
    "AiPasteDialog",
    "AppUpdateDialog",
    "BlenderSkillsDialog",
    "ConnectionTestDialog",
    "DARK_QSS",
    "FullRowHoverDelegate",
    "HoverTableWidget",
    "LIGHT_QSS",
    "MainWindow",
    "ToolGearDialog",
    "ToolInfoDialog",
    "WorkerBridge",
    "create_app_icon",
]
