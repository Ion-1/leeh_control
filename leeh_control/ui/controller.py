import logging
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal, Slot, QSignalBlocker
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFormLayout,
    QListWidget,
    QLineEdit,
    QPushButton,
    QStyle,
    QLabel,
    QListWidgetItem,
    QToolButton,
    QDialog,
    QTabWidget,
    QButtonGroup,
    QRadioButton,
)
from pylablib.core.utils import py3
from pylablib.devices.Attocube.anc300 import ANC300 as PLL_ANC300, AttocubeError

from .axis import ANM300Widget
from ..config import ConfigProvider, AxisConfig, Limits
from ..controller import ANC300

logger = logging.getLogger(__name__)


class ConsoleMessageItem(QListWidgetItem):
    def __init__(self, text: str, is_command: bool):
        self.message_text = text
        self.is_command = is_command
        super().__init__(self._render_text())

    def _render_text(self) -> str:
        prefix = "> " if self.is_command else "< "
        cont_prefix = " " * len(prefix)

        lines = self.message_text.splitlines() or [""]
        rendered = [f"{prefix}{lines[0]}"]
        rendered.extend(f"{cont_prefix}{line}" for line in lines[1:])
        return "\n".join(rendered)


class ANC300Widget(QWidget):
    def __init__(
        self, controller: ANC300, config_provider: ConfigProvider, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.controller = controller
        self.config_provider = config_provider
        self.settings_dialog: SettingsDialog | None = None
        self.console = ControllerConsoleWidget(self.controller)

        self.axes = self.controller.axes
        self.axes_widgs = []

        bigger_layout = QHBoxLayout(self)
        layout = QVBoxLayout()
        bigger_layout.addLayout(layout)

        bigger_layout.addWidget(self.console)
        self.console.hide()

        top_bar = QHBoxLayout()

        self.serial_label = QLabel(
            "Controller Serial: "
            + "; Version: ".join(self.controller.get_device_info())
        )
        top_bar.addWidget(self.serial_label, stretch=1)

        self.open_settings_button = QPushButton("Settings")
        self.open_settings_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        self.open_settings_button.clicked.connect(self.open_settings_dialog)
        top_bar.addWidget(self.open_settings_button)

        self.refresh_button = QPushButton(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "Refresh"
        )
        self.refresh_button.clicked.connect(self.refresh)
        top_bar.addWidget(self.refresh_button)

        self.show_console = QToolButton()
        self.show_console.setArrowType(Qt.ArrowType.DownArrow)
        self.show_console.setText("Show Console")
        self.show_console.setCheckable(True)
        self.show_console.toggled.connect(self.toggle_console)
        top_bar.addWidget(self.show_console)

        layout.addLayout(top_bar)

        middle_bar = QHBoxLayout()
        layout.addLayout(middle_bar)

        axis_layout = QHBoxLayout()
        middle_bar.addLayout(axis_layout, stretch=2)

        for axis in self.axes:
            widg = ANM300Widget(
                serial=self.controller.get_serial(axis),
                aid=axis,
                controller=self.controller,
                config_provider=config_provider,
            )
            axis_layout.addWidget(widg)
            self.axes_widgs.append(widg)

    @Slot()
    def open_settings_dialog(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(
                axes_serials=[self.controller.get_serial(axis) for axis in self.axes],
                config_provider=self.config_provider,
                parent=self,
            )
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    @Slot(bool)
    def toggle_console(self, checked: bool):
        if checked:
            self.show_console.setArrowType(Qt.ArrowType.RightArrow)
            self.show_console.setText("Hide Console")
            self.console.show()
        else:
            self.show_console.setArrowType(Qt.ArrowType.DownArrow)
            self.show_console.setText("Show Console")
            self.console.hide()

    @Slot()
    def refresh(self):
        """A controller's axes can not change while it is connected."""
        for widg in self.axes_widgs:
            widg.refresh()


class ControllerConsoleWidget(QWidget):
    command_sent = Signal(str)
    reply_received = Signal(str)

    def __init__(self, controller: ANC300, *args, **kwargs):
        super().__init__(*args, **kwargs)

        controller.inner.query = self._query_patch(controller.inner)
        self.controller = controller

        layout = QVBoxLayout(self)

        self.list_widget = QListWidget(self)
        self.list_widget.setWordWrap(True)
        self.list_widget.setAlternatingRowColors(True)
        layout.addWidget(self.list_widget)

        self.input_widget = QLineEdit(self)
        self.input_widget.returnPressed.connect(self.send_command)
        layout.addWidget(self.input_widget)

        self.command_sent.connect(self.on_command_sent)
        self.reply_received.connect(self.on_reply_received)

    def append(self, item: ConsoleMessageItem):
        self.list_widget.addItem(item)
        self.list_widget.scrollToBottom()

    @Slot()
    def send_command(self):
        self.controller.query_controller(self.input_widget.text())
        self.input_widget.clear()

    @Slot(str)
    def on_command_sent(self, msg: str):
        self.append(ConsoleMessageItem(text=msg, is_command=True))

    @Slot(str)
    def on_reply_received(self, reply: str):
        self.append(ConsoleMessageItem(text=reply, is_command=False))

    def _query_patch(self, controller: PLL_ANC300):
        """Copy-paste of the query method from the pylablib ANC300 class."""

        def query(msg):
            controller.instr.flush_read()
            self.command_sent.emit(py3.as_str(msg))
            logger.info(f"Sending command: {msg}")
            controller.instr.write(msg)
            reply = controller.instr.read_multichar_term(
                ["ERROR", "OK"], remove_term=False
            )
            self.reply_received.emit(reply_text := py3.as_str(reply))
            logger.info(f"Received reply: {reply_text}")
            # self.instr.flush_read()
            if reply_text.upper().endswith("ERROR"):
                err = py3.as_str(reply_text)[:-5].strip()
                raise AttocubeError(err)
            return reply_text[:-2].strip()

        return query


class SettingsDialog(QDialog):
    def __init__(self, axes_serials: list[str], config_provider: ConfigProvider, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.axes_serials = axes_serials
        self.config_provider = config_provider

        self.setModal(False)
        self.setWindowTitle("Settings")
        self.resize(560, 420)

        layout = QVBoxLayout(self)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        self._build_general_tab()
        for serial in self.axes_serials:
            self._build_axis_tab(serial)

        self.done_button = QPushButton("Done")
        self.done_button.clicked.connect(self.accept)
        layout.addWidget(self.done_button, alignment=Qt.AlignmentFlag.AlignRight)

    @staticmethod
    def _to_str(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return f"{value}"

    def _add_optional_text_setting(
        self,
        form: QFormLayout,
        label: str,
        config: Any,
        field: str,
        default: str | None,
        on_change: Callable[[str | None], None],
    ):
        editor = QLineEdit(self)
        editor.setPlaceholderText(self._to_str(default))

        @Slot()
        def refresh_from_config():
            blocker = QSignalBlocker(editor)
            value = getattr(config, field)
            if config.is_default(field) or value is None:
                editor.clear()
            else:
                editor.setText(value)
            del blocker

        @Slot()
        def commit_text():
            text = editor.text()
            if text.strip() == "":
                on_change(None)
                editor.clear()
                return

            if default is not None and text == default:
                on_change(None)
                editor.clear()
                return

            on_change(text)

        editor.editingFinished.connect(commit_text)
        signal = getattr(config.signals, field, None)
        if signal is not None:
            signal.connect(refresh_from_config)
        refresh_from_config()
        form.addRow(label, editor)

    def _add_bool_setting(
        self,
        form: QFormLayout,
        label: str,
        config: Any,
        field: str,
        on_change: Callable[[bool], None],
    ):
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        group = QButtonGroup(row)
        disabled_button = QRadioButton("Disabled", row)
        enabled_button = QRadioButton("Enabled", row)
        group.addButton(disabled_button)
        group.addButton(enabled_button)

        @Slot()
        def refresh_from_config():
            # Block button signals to avoid writing back while syncing from config.
            blocker_disabled = QSignalBlocker(disabled_button)
            blocker_enabled = QSignalBlocker(enabled_button)
            value = bool(getattr(config, field))
            if value:
                enabled_button.setChecked(True)
            else:
                disabled_button.setChecked(True)
            del blocker_disabled
            del blocker_enabled

        @Slot(bool)
        def on_enabled_toggled(checked: bool):
            if checked:
                on_change(True)

        @Slot(bool)
        def on_disabled_toggled(checked: bool):
            if checked:
                on_change(False)

        enabled_button.toggled.connect(on_enabled_toggled)
        disabled_button.toggled.connect(on_disabled_toggled)
        signal = getattr(config.signals, field, None)
        if signal is not None:
            signal.connect(refresh_from_config)
        refresh_from_config()

        row_layout.addWidget(disabled_button)
        row_layout.addWidget(enabled_button)
        row_layout.addStretch(1)
        form.addRow(label, row)

    def _add_limit_setting(
        self,
        form: QFormLayout,
        label: str,
        config: Any,
        field: str,
        default: Limits[Any],
        parser: Callable[[str], Any],
        formatter: Callable[[Any], str],
        on_change: Callable[[Limits[Any] | None], None],
    ):
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        bottom_editor = QLineEdit(self)
        top_editor = QLineEdit(self)

        bottom_editor.setPlaceholderText(formatter(default["bottom"]))
        top_editor.setPlaceholderText(formatter(default["top"]))

        @Slot()
        def refresh_from_config():
            blocker_bottom = QSignalBlocker(bottom_editor)
            blocker_top = QSignalBlocker(top_editor)
            current = getattr(config, field)
            if config.is_default(field):
                bottom_editor.clear()
                top_editor.clear()
            else:
                bottom_editor.setText(formatter(current["bottom"]))
                top_editor.setText(formatter(current["top"]))
            del blocker_bottom
            del blocker_top

        row_layout.addWidget(QLabel("bottom", self))
        row_layout.addWidget(bottom_editor)
        row_layout.addWidget(QLabel("top", self))
        row_layout.addWidget(top_editor)

        @Slot()
        def commit_limit():
            bottom_text = bottom_editor.text().strip()
            top_text = top_editor.text().strip()

            if bottom_text == "" and top_text == "":
                on_change(None)
                bottom_editor.clear()
                top_editor.clear()
                return

            try:
                bottom = parser(bottom_text) if bottom_text != "" else default["bottom"]
                top = parser(top_text) if top_text != "" else default["top"]
            except ValueError:
                refresh_from_config()
                return

            if bottom > top:
                refresh_from_config()
                return

            if bottom == default["bottom"] and top == default["top"]:
                on_change(None)
                bottom_editor.clear()
                top_editor.clear()
                return

            on_change(Limits(bottom=bottom, top=top))
            if bottom_text != "":
                bottom_editor.setText(formatter(bottom))
            else:
                bottom_editor.clear()
            if top_text != "":
                top_editor.setText(formatter(top))
            else:
                top_editor.clear()

        bottom_editor.editingFinished.connect(commit_limit)
        top_editor.editingFinished.connect(commit_limit)
        signal = getattr(config.signals, field, None)
        if signal is not None:
            signal.connect(refresh_from_config)
        refresh_from_config()
        form.addRow(label, row)

    def _build_general_tab(self):
        config = self.config_provider.general_config()

        tab = QWidget(self)
        form = QFormLayout(tab)

        self._add_bool_setting(
            form=form,
            label="Advanced mode",
            config=config,
            field="advanced_mode",
            on_change=lambda value: setattr(config, "advanced_mode", value),
        )

        self.tabs.addTab(tab, "General")

    def _build_axis_tab(self, serial: str):
        config = self.config_provider.axis_config(serial)

        tab = QWidget(self)
        form = QFormLayout(tab)

        self._add_optional_text_setting(
            form=form,
            label="Name",
            config=config,
            field="name",
            default=AxisConfig.name,
            on_change=lambda value: setattr(config, "name", value),
        )

        self._add_optional_text_setting(
            form=form,
            label="Up command",
            config=config,
            field="up",
            default=AxisConfig.up,
            on_change=lambda value: setattr(config, "up", value),
        )

        self._add_optional_text_setting(
            form=form,
            label="Down command",
            config=config,
            field="down",
            default=AxisConfig.down,
            on_change=lambda value: setattr(config, "down", value),
        )

        self._add_limit_setting(
            form=form,
            label="Offset limits (V)",
            config=config,
            field="offset_lim",
            default=AxisConfig.offset_lim,
            parser=float,
            formatter=lambda value: f"{float(value):g}",
            on_change=lambda value: setattr(config, "offset_lim", value),
        )

        self._add_limit_setting(
            form=form,
            label="Frequency limits (Hz)",
            config=config,
            field="freq_lim",
            default=AxisConfig.freq_lim,
            parser=int,
            formatter=lambda value: f"{int(value)}",
            on_change=lambda value: setattr(config, "freq_lim", value),
        )

        self._add_limit_setting(
            form=form,
            label="Step voltage limits (V)",
            config=config,
            field="step_V_lim",
            default=AxisConfig.step_V_lim,
            parser=float,
            formatter=lambda value: f"{float(value):g}",
            on_change=lambda value: setattr(config, "step_V_lim", value),
        )

        self.tabs.addTab(tab, serial)

