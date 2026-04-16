import logging

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QListWidget,
    QLineEdit,
    QPushButton,
    QStyle,
    QLabel,
    QListWidgetItem,
)
from pylablib.core.utils import py3
from pylablib.devices.Attocube.anc300 import ANC300 as PLL_ANC300, AttocubeError

from .axis import ANM300Widget
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
    def __init__(self, controller: ANC300, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.controller = controller
        self.console = ControllerConsoleWidget(self.controller)

        self.axes = self.controller.axes
        self.axes_widgs = []

        layout = QVBoxLayout(self)

        top_bar = QHBoxLayout()

        self.serial_label = QLabel("Controller Serial: " + "; Version: ".join(self.controller.get_device_info()))
        top_bar.addWidget(self.serial_label)

        self.refresh_button = QPushButton(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "Refresh"
        )
        self.refresh_button.clicked.connect(self.refresh)
        top_bar.addWidget(self.refresh_button)

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
            )
            axis_layout.addWidget(widg)
            self.axes_widgs.append(widg)

        middle_bar.addWidget(self.console)

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
