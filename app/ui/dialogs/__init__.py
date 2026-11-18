"""Dialog windows for AIconomy."""
from __future__ import annotations

from .add_repo import AddRepoDialog
from .ai_paste import AiPasteDialog
from .app_update import AppUpdateDialog
from .blender_skills import BlenderSkillsDialog
from .diagnostics import DiagnosticsDialog
from .manage_profiles import ManageProfilesDialog
from .settings import SettingsDialog
from .tool_info import ToolInfoDialog
from .tool_settings import ToolGearDialog

__all__ = [
    "AddRepoDialog",
    "AiPasteDialog",
    "AppUpdateDialog",
    "BlenderSkillsDialog",
    "DiagnosticsDialog",
    "ManageProfilesDialog",
    "SettingsDialog",
    "ToolGearDialog",
    "ToolInfoDialog",
]
