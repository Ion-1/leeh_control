import logging

from typing import Callable, Literal, Any

from serial.tools.list_ports_common import ListPortInfo
from PySide6.QtCore import Slot, Signal
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QComboBox,
    QPushButton,
    QErrorMessage,
    QStackedWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStyle,
)

from .controller import ANC300Widget
from ..controller import ANC300, COMConnectionOptions
from ..state import ControllerState, AppState
from ..config import ConfigProvider


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        state: AppState,
        config_provider: ConfigProvider,
        show_fake: bool = False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.app_state = state
        self.config_provider = config_provider

        self.widget_stack = QStackedWidget(self)
        self.setCentralWidget(self.widget_stack)

        self.choose_widget = ChooseControllerWindow(show_fake, parent=self)
        self.choose_widget.selection.connect(self.connect_controller)
        self.widget_stack.insertWidget(0, self.choose_widget)

        self.controller_widget = None

    @Slot(ListPortInfo)
    def connect_controller(self, selected_port: ListPortInfo):
        query_holder = QueryHolder()

        connect_result = ANC300.connect_COM(
            COMConnectionOptions(port=selected_port.device),
            query_callback=query_holder.on_query,
            reply_callback=query_holder.on_reply,
        )

        if connect_result.is_err():
            QErrorMessage(self).showMessage(
                f"Error connecting to controller: {connect_result.unwrap_err()}"
            )
            return

        self.app_state.controller = ControllerState.Connected(
            controller := connect_result.unwrap()
        )
        controller.add_error_callback(self.display_error)

        self.controller_widget = ANC300Widget(
            controller, self.config_provider, query_holder.messages
        )
        self.widget_stack.insertWidget(1, self.controller_widget)
        self.widget_stack.setCurrentIndex(1)

        controller.remove_query_callback(query_holder.on_query)
        controller.remove_reply_callback(query_holder.on_reply)

    @Slot(str)
    def display_error(self, msg: str):
        QErrorMessage(self).showMessage(msg)


class ChooseControllerWindow(QWidget):
    selection = Signal(ListPortInfo)

    def __init__(self, show_fake: bool = False, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)

        drop_layout = QHBoxLayout()
        layout.addLayout(drop_layout)

        self.dropdown = QComboBox()
        drop_layout.addWidget(self.dropdown, stretch=1)

        self.refresh_button = QPushButton("")
        self.refresh_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        drop_layout.addWidget(self.refresh_button)
        self.refresh_button.clicked.connect(self.refresh)

        self.show_fake = show_fake
        ports = ANC300.list_ports(show_fake=show_fake)

        for port in ports:
            self.dropdown.addItem(port.name, userData=port)

        self.button = QPushButton("Connect")
        layout.addWidget(self.button)
        self.button.clicked.connect(self.clicked)

    @Slot()
    def refresh(self):
        ports = ANC300.list_ports(self.show_fake)

        self.dropdown.clear()
        for port in ports:
            self.dropdown.addItem(port.name, userData=port)

    @Slot()
    def clicked(self):
        if (port := self.dropdown.currentData()) is not None:
            self.selection.emit(port)


class QueryHolder:
    def __init__(self):
        self.query_callbacks: list[Callable[[str], Any]] = []
        self.reply_callbacks: list[Callable[[str], Any]] = []
        self.messages: list[tuple[Literal[0, 1], str]] = []

    def on_query(self, msg: str):
        self.messages.append((0, msg))

    def on_reply(self, msg: str):
        self.messages.append((1, msg))

    def replay(
        self,
        query_callback: Callable[[str], Any] | None = None,
        reply_callback: Callable[[str], Any] | None = None,
    ):
        for kind, message in self.messages:
            if kind == 0 and query_callback is not None:
                query_callback(message)
            elif kind == 1 and reply_callback is not None:
                reply_callback(message)
