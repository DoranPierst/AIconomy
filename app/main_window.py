"""Compatibility facade re-exporting modularized UI components."""
from __future__ import annotations

from .ui.dialogs import (
    AddRepoDialog,
    AiPasteDialog,
    AppUpdateDialog,
    BlenderSkillsDialog,
    DiagnosticsDialog,
    ManageProfilesDialog,
    SettingsDialog,
    ToolGearDialog,
    ToolInfoDialog,
)
from .ui.main_window import MainWindow
from .ui.theme import DARK_QSS, LIGHT_QSS, create_app_icon
from .ui.widgets import AiMatrixHeaderView, FullRowHoverDelegate, HoverTableWidget, StatusBadgeWidget, ToggleSwitch
from .ui.workers import WorkerBridge

__all__ = [
    "AddRepoDialog",
    "AiMatrixHeaderView",
    "AiPasteDialog",
    "AppUpdateDialog",
    "BlenderSkillsDialog",
    "DARK_QSS",
    "DiagnosticsDialog",
    "FullRowHoverDelegate",
    "HoverTableWidget",
    "LIGHT_QSS",
    "MainWindow",
    "ManageProfilesDialog",
    "SettingsDialog",
    "StatusBadgeWidget",
    "ToggleSwitch",
    "ToolGearDialog",
    "ToolInfoDialog",
    "WorkerBridge",
    "create_app_icon",
]
