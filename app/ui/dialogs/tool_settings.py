"""Per-tool technical settings dialog with mode selector, real CLI options, API key shortcut, and reset."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...catalog import (
    ToolSpec,
    get_default_tool_spec,
    localized_option_text,
    localized_tool_modes,
    localized_tool_text,
)
from ...i18n import tr
from ...oauth import check_cli_oauth_ready, get_oauth_spec, launch_browser_oauth_flow, supports_oauth
from ...security import auto_vault_key_for_tool, contains_embedded_secret
from ..widgets import create_option_help_badge
from ..workers import safe_emit

if TYPE_CHECKING:
    from ..main_window import MainWindow


class ToolGearDialog(QDialog):
    """Configure a tool's active mode, parameter, real CLI options, API key shortcut, and defaults."""

    _oauth_probe_done = Signal(int, bool)

    def __init__(
        self,
        parent: "MainWindow",
        tool: ToolSpec,
        scope_display: str,
    ) -> None:
        super().__init__(parent)
        self.main_win = parent
        self.tool = tool
        self.vault = parent.vault
        self.lang = parent.lang
        self.scope_display = scope_display
        self.reset_requested = False
        self._oauth_probe_gen = 0
        self._oauth_probe_done.connect(self._on_oauth_probe_done)
        self.setWindowTitle(tr(self.lang, "gear_title", name=tool.name))
        self.setMinimumWidth(620)
        self.resize(650, 460)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        loc_card = QFrame()
        loc_card.setObjectName("card")
        loc_lay = QVBoxLayout(loc_card)
        loc_lay.setContentsMargins(12, 8, 12, 8)
        loc_lay.addWidget(QLabel(f"<b>{tr(self.lang, 'gear_scope_lbl')}</b> {scope_display}"))
        if tool.live_location_detail:
            det = QLabel(f"<span style='color:#94a3b8; font-size:11px;'>{tool.live_location_detail}</span>")
            det.setWordWrap(True)
            loc_lay.addWidget(det)
        lay.addWidget(loc_card)

        self.mode_cmb: QComboBox | None = None
        modes_loc = localized_tool_modes(tool, self.lang)
        if len(modes_loc) > 1:
            m_card = QFrame()
            m_card.setObjectName("card")
            m_lay = QHBoxLayout(m_card)
            m_lay.setContentsMargins(12, 8, 12, 8)
            m_lay.setSpacing(10)
            m_lay.addWidget(QLabel(f"<b>{tr(self.lang, 'gear_mode_lbl')}</b>"))
            self.mode_cmb = QComboBox()
            self.mode_cmb.addItems(modes_loc)
            self.mode_cmb.setCurrentIndex(max(0, min(tool.mode_index, len(modes_loc) - 1)))
            self.mode_cmb.setMinimumWidth(220)
            m_lay.addWidget(self.mode_cmb)
            m_lay.addStretch()
            lay.addWidget(m_card)

        self.opt_help_card = QFrame()
        self.opt_help_card.setObjectName("bannerInfo")
        oh_lay = QVBoxLayout(self.opt_help_card)
        oh_lay.setContentsMargins(12, 8, 12, 8)
        oh_lay.setSpacing(4)
        self.opt_help_title = QLabel(f"<b>{tr(self.lang, 'gear_help_hdr')}</b>")
        self.opt_help_body = QLabel("")
        self.opt_help_body.setWordWrap(True)
        self.opt_help_body.setStyleSheet("font-size: 11px;")
        oh_lay.addWidget(self.opt_help_title)
        oh_lay.addWidget(self.opt_help_body)

        param_lbl = localized_tool_text(tool, "param_label", self.lang)
        param_help = localized_tool_text(tool, "param_help", self.lang)
        if param_lbl:
            p_card = QFrame()
            p_card.setObjectName("card")
            p_lay = QVBoxLayout(p_card)
            p_lay.setContentsMargins(12, 8, 12, 8)
            p_hdr = QHBoxLayout()
            p_hdr.setSpacing(6)
            p_hdr.addWidget(QLabel(f"<b>{param_lbl}</b>"))
            if param_help:
                p_hdr.addWidget(
                    create_option_help_badge(
                        param_help,
                        lambda lbl=param_lbl, h=param_help: self._show_option_help(lbl, h),
                    )
                )
            p_hdr.addStretch()
            p_lay.addLayout(p_hdr)
            self.param_inp = QLineEdit(tool.param_value)
            if param_help:
                self.param_inp.setToolTip(param_help)
            p_lay.addWidget(self.param_inp)
            lay.addWidget(p_card)
        else:
            self.param_inp = None

        self.auth_cmb: QComboBox | None = None
        self._oauth_status_lbl: QLabel | None = None
        self._oauth_btn: QPushButton | None = None
        self._oauth_spec = get_oauth_spec(tool.id) if supports_oauth(tool.id) else None
        if self._oauth_spec is not None:
            a_card = QFrame()
            a_card.setObjectName("card")
            a_outer = QVBoxLayout(a_card)
            a_outer.setContentsMargins(12, 8, 12, 8)
            a_outer.setSpacing(6)

            a_top = QHBoxLayout()
            a_top.setSpacing(8)
            a_top.addWidget(QLabel(f"<b>{tr(self.lang, 'gear_auth_lbl')}</b>"))
            self.auth_cmb = QComboBox()
            if tool.vault_key_name:
                self.auth_cmb.addItem(tr(self.lang, "gear_auth_mode_key"), "key")
            self.auth_cmb.addItem(
                tr(self.lang, "gear_auth_mode_oauth", provider=self._oauth_spec.provider_label),
                "oauth",
            )
            cur_auth = getattr(tool, "auth_mode", "key")
            if not tool.vault_key_name:
                cur_auth = "oauth"
            idx_a = self.auth_cmb.findData(cur_auth)
            self.auth_cmb.setCurrentIndex(max(0, idx_a))
            self.auth_cmb.setMinimumWidth(240)
            self.auth_cmb.currentIndexChanged.connect(lambda _idx: self._refresh_auth_ui())
            a_top.addWidget(self.auth_cmb)
            a_top.addStretch()

            self._oauth_btn = QPushButton(tr(self.lang, "gear_oauth_btn"))
            self._oauth_btn.setObjectName("primaryBtn")
            self._oauth_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._oauth_btn.clicked.connect(self._handle_oauth_login)
            a_top.addWidget(self._oauth_btn)
            a_outer.addLayout(a_top)

            self._oauth_status_lbl = QLabel("")
            self._oauth_status_lbl.setWordWrap(True)
            self._oauth_status_lbl.setStyleSheet("font-size: 11px;")
            a_outer.addWidget(self._oauth_status_lbl)
            lay.addWidget(a_card)

        self._vault_card: QFrame | None = None
        self._key_status_lbl: QLabel | None = None
        if tool.vault_key_name:
            v_card = QFrame()
            v_card.setObjectName("card")
            v_lay = QHBoxLayout(v_card)
            v_lay.setContentsMargins(12, 8, 12, 8)
            self._key_status_lbl = QLabel()
            v_lay.addWidget(self._key_status_lbl, stretch=1)
            btn_set_key = QPushButton(tr(self.lang, "gear_set_key_btn"))
            btn_set_key.clicked.connect(self._open_api_keys)
            v_lay.addWidget(btn_set_key)
            lay.addWidget(v_card)
            self._vault_card = v_card
            self._refresh_key_status()

        if self._oauth_spec is not None:
            self._refresh_auth_ui()

        self.opt_checks: dict[str, QCheckBox] = {}
        if tool.options:
            opt_card = QFrame()
            opt_card.setObjectName("card")
            opt_lay = QVBoxLayout(opt_card)
            opt_lay.setContentsMargins(12, 10, 12, 10)
            opt_lay.setSpacing(6)
            opt_lay.addWidget(
                QLabel(
                    f"<b>{tr(self.lang, 'gear_opts_hdr')}</b>  "
                    f"<span style='color:#94a3b8; font-size:11px;'>({tr(self.lang, 'gear_opts_hint')})</span>"
                )
            )
            for opt in tool.options:
                o_lbl, o_help = localized_option_text(tool.id, opt, self.lang)
                row_w = QWidget()
                row_w.setObjectName("cellBox")
                r_lay = QHBoxLayout(row_w)
                r_lay.setContentsMargins(2, 2, 2, 2)
                r_lay.setSpacing(8)

                cb = QCheckBox(o_lbl)
                cb.setChecked(opt.enabled)
                cb.setCursor(Qt.CursorShape.PointingHandCursor)
                if o_help:
                    cb.setToolTip(o_help)
                cb.installEventFilter(self)
                cb.setProperty("opt_title", o_lbl)
                cb.setProperty("opt_help", o_help)
                self.opt_checks[opt.key] = cb
                r_lay.addWidget(cb)

                if o_help:
                    info_btn = create_option_help_badge(
                        o_help,
                        lambda lbl=o_lbl, h=o_help: self._show_option_help(lbl, h),
                    )
                    r_lay.addWidget(info_btn)
                r_lay.addStretch()
                opt_lay.addWidget(row_w)
            lay.addWidget(opt_card)

        lay.addWidget(self.opt_help_card)

        if tool.options:
            first_lbl, first_help = localized_option_text(tool.id, tool.options[0], self.lang)
            self._show_option_help(first_lbl, first_help)
        elif param_lbl and param_help:
            self._show_option_help(param_lbl, param_help)
        else:
            self.opt_help_card.hide()

        lay.addStretch()

        bot = QHBoxLayout()
        self.btn_reset = QPushButton(tr(self.lang, "btn_reset_defaults"))
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.clicked.connect(self._reset_to_defaults)

        btn_cancel = QPushButton(tr(self.lang, "btn_cancel"))
        btn_save = QPushButton(tr(self.lang, "btn_save"))
        btn_save.setObjectName("primaryBtn")

        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)

        bot.addWidget(self.btn_reset)
        bot.addStretch()
        bot.addWidget(btn_cancel)
        bot.addWidget(btn_save)
        lay.addLayout(bot)

    def _selected_auth_mode(self) -> str:
        if self.auth_cmb is not None:
            return str(self.auth_cmb.currentData() or "key")
        return getattr(self.tool, "auth_mode", "key")

    def _refresh_auth_ui(self) -> None:
        is_oauth = self._selected_auth_mode() == "oauth" and self._oauth_spec is not None
        if self._vault_card is not None:
            self._vault_card.setVisible(not is_oauth)
        if self._oauth_btn is not None:
            self._oauth_btn.setVisible(is_oauth)
        if self._oauth_status_lbl is not None:
            self._oauth_status_lbl.setVisible(is_oauth)
            if is_oauth and self._oauth_spec is not None:
                if self._oauth_spec.kind == "remote_mcp":
                    txt = tr(self.lang, "gear_oauth_remote_ready")
                    col = "#10b981"
                    self._oauth_status_lbl.setText(f"<span style='color:{col}; font-weight:600;'>{txt}</span>")
                elif not getattr(self.main_win, "sync_live_environment", True):
                    txt = tr(self.lang, "gear_oauth_cli_missing")
                    self._oauth_status_lbl.setText(f"<span style='color:#f59e0b; font-weight:600;'>{txt}</span>")
                else:
                    self._oauth_probe_gen += 1
                    cur_gen = self._oauth_probe_gen
                    tid_snap = self.tool.id
                    wait_txt = tr(self.lang, "st_scanning")
                    self._oauth_status_lbl.setText(f"<span style='color:#94a3b8; font-weight:600;'>{wait_txt}</span>")

                    def _probe() -> None:
                        ok_cli = check_cli_oauth_ready(tid_snap)
                        safe_emit(self._oauth_probe_done, cur_gen, ok_cli)

                    threading.Thread(target=_probe, daemon=True).start()

    def _on_oauth_probe_done(self, gen: int, cli_ok: bool) -> None:
        if gen != self._oauth_probe_gen or self._oauth_status_lbl is None or self._oauth_spec is None:
            return
        if cli_ok:
            txt = tr(self.lang, "gear_oauth_cli_ok", provider=self._oauth_spec.provider_label)
            col = "#10b981"
        else:
            txt = tr(self.lang, "gear_oauth_cli_missing")
            col = "#f59e0b"
        self._oauth_status_lbl.setText(f"<span style='color:{col}; font-weight:600;'>{txt}</span>")

    def _handle_oauth_login(self) -> None:
        if not getattr(self.main_win, "sync_live_environment", True):
            return
        ok, msg = launch_browser_oauth_flow(self.tool.id, lang=self.lang)
        self.main_win.logs.add("INFO" if ok else "WARN", self.tool.name, msg)
        self.main_win.set_status(msg)
        self.main_win._refresh_logs_tab()
        if self._oauth_status_lbl is not None:
            col = "#10b981" if ok else "#ef4444"
            self._oauth_status_lbl.setText(f"<span style='color:{col}; font-weight:600;'>{msg}</span>")
            self._oauth_status_lbl.show()

    def _refresh_key_status(self) -> None:
        if self._key_status_lbl is None:
            return
        if self.vault.is_locked() and (self.tool.vault_key_required or self.vault.has_key_entry(self.tool.vault_key_name)):
            status_txt = tr(self.lang, "st_vault_locked")
            col = "#f59e0b"
        elif self.vault.has_secret(self.tool.vault_key_name):
            status_txt = tr(self.lang, "gear_key_set")
            col = "#22c55e"
        elif self.tool.vault_key_required:
            status_txt = tr(self.lang, "gear_key_missing")
            col = "#f59e0b"
        else:
            status_txt = tr(self.lang, "gear_key_optional")
            col = "#94a3b8"
        self._key_status_lbl.setText(
            f"<b>{self.tool.vault_key_name}:</b> <span style='color:{col}; font-weight:600;'>{status_txt}</span>"
        )

    def _open_api_keys(self) -> None:
        self.main_win.open_settings(initial_tab=1, focus_key=self.tool.vault_key_name)
        self._refresh_key_status()

    def _show_option_help(self, title: str, help_body: str) -> None:
        if not help_body:
            return
        self.opt_help_title.setText(f"<b>{title}</b>")
        self.opt_help_body.setText(help_body)
        self.opt_help_card.show()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Enter:
            t = watched.property("opt_title")
            h = watched.property("opt_help")
            if t and h:
                self._show_option_help(str(t), str(h))
        return super().eventFilter(watched, event)

    def _reset_to_defaults(self) -> None:
        self.reset_requested = True
        default_spec = get_default_tool_spec(self.tool.id)
        if default_spec is not None:
            if self.auth_cmb is not None:
                def_auth = default_spec.auth_mode if default_spec.vault_key_name else "oauth"
                idx_a = self.auth_cmb.findData(def_auth)
                self.auth_cmb.setCurrentIndex(max(0, idx_a))
            if self.param_inp is not None:
                self.param_inp.setText(default_spec.param_value)
            if self.mode_cmb is not None and default_spec.modes:
                self.mode_cmb.setCurrentIndex(max(0, min(default_spec.mode_index, self.mode_cmb.count() - 1)))
            def_opts = {o.key: o.enabled for o in default_spec.options}
            for key, cb in self.opt_checks.items():
                cb.setChecked(def_opts.get(key, False))
        else:
            if self.auth_cmb is not None:
                self.auth_cmb.setCurrentIndex(0)
            if self.param_inp is not None:
                self.param_inp.setText("")
            if self.mode_cmb is not None:
                self.mode_cmb.setCurrentIndex(0)
            for cb in self.opt_checks.values():
                cb.setChecked(False)
        self._show_option_help(tr(self.lang, "btn_reset_defaults"), tr(self.lang, "gear_reset_loaded"))

    def _save(self) -> None:
        if self.auth_cmb is not None:
            self.tool.auth_mode = self._selected_auth_mode()
        if self.param_inp is not None:
            raw_pv = self.param_inp.text().strip()
            if contains_embedded_secret(raw_pv):
                vk = self.tool.vault_key_name or auto_vault_key_for_tool(self.tool.id)
                self.tool.vault_key_name = vk
                if not self.vault.is_locked():
                    self.vault.set_secret(vk, raw_pv)
                self.tool.param_value = ""
            else:
                self.tool.param_value = raw_pv
            if self.tool.id in ("serena", "unity_mcp", "blender_mcp") and self.tool.param_value.isdigit():
                p_val = int(self.tool.param_value)
                if 1 <= p_val <= 65535:
                    self.tool.port = p_val
        if self.mode_cmb is not None:
            self.tool.mode_index = self.mode_cmb.currentIndex()
        for opt in self.tool.options:
            opt.enabled = self.opt_checks[opt.key].isChecked()
        if self.reset_requested:
            default_spec = get_default_tool_spec(self.tool.id)
            if default_spec is not None:
                if self.tool.scope_selectable:
                    self.tool.project_scope = default_spec.project_scope
                self.tool.clients = dict(default_spec.clients)
                if self.param_inp is None and default_spec.port is not None:
                    self.tool.port = default_spec.port
        self.accept()
