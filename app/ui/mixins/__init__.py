"""Modular controller mixins for MainWindow (profiles, system tray, self-updater, backup/catalog sync)."""
from __future__ import annotations

from .profiles_mixin import ProfilesMixin
from .tray_updater_mixin import TrayUpdaterMixin

__all__ = ["ProfilesMixin", "TrayUpdaterMixin"]
