import logging
from typing import Callable, Literal, Any

from PySide6.QtCore import Slot, Signal, Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QComboBox,
    QPushButton,
    QErrorMessage,
    QVBoxLayout,
    QHBoxLayout,
    QStyle,
    QMessageBox,
)
from pylablib.devices import DCAM
from serial.tools.list_ports_common import ListPortInfo

from .controller import ANC300Widget
from ..camera import CameraWidget
from ..config import ConfigProvider
from ..controller import ANC300, COMConnectionOptions
from ..state import ControllerState, AppState

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

        show_fake = show_fake or __debug__

        self.app_state = state
        self.config_provider = config_provider

        main = QWidget()
        self.setCentralWidget(main)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        main.setLayout(layout)

        self.open_controller_window = None
        self.choose_widget = ChooseControllerWindow(show_fake, parent=self)
        self.choose_widget.selection.connect(self.connect_controller)
        layout.addWidget(self.choose_widget)

        self.open_camera_window = None
        self.choose_camera_widget = ChooseCameraWindow(show_fake, parent=self)
        self.choose_camera_widget.selection.connect(self.connect_camera)
        layout.addWidget(self.choose_camera_widget)

        self.controller_widget = None
        self.camera_widget = None

    @Slot(ListPortInfo)
    def connect_controller(self, selected_port: ListPortInfo):
        if self.open_controller_window is not None:
            msg = QMessageBox(self)
            msg.setText("Another controller connection is already open.")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            return

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
        self.controller_widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        new_window = QMainWindow()
        new_window.setWindowTitle("ANC300")
        new_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        new_window.setCentralWidget(self.controller_widget)
        new_window.show()
        self.open_controller_window = new_window
        self.open_controller_window.destroyed.connect(lambda: setattr(self, "open_controller_window", None))

        controller.remove_query_callback(query_holder.on_query)
        controller.remove_reply_callback(query_holder.on_reply)

    @Slot(int)
    def connect_camera(self, selected_camera: int):
        if self.open_camera_window is not None:
            msg = QMessageBox(self)
            msg.setText("Another camera connection is already open.")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            return

        if selected_camera == -1:
            self.camera_widget = CameraWidget(None)
            self.camera_widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            new_window = QMainWindow()
            new_window.setWindowTitle("Camera")
            new_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            new_window.setCentralWidget(self.camera_widget)
            new_window.show()
            self.open_camera_window = new_window
            self.open_camera_window.destroyed.connect(lambda: setattr(self, "open_camera_window", None))
            return

        try:
            cam = DCAM.DCAMCamera(selected_camera)
        except Exception as e:
            QErrorMessage(self).showMessage(f"Error connecting to camera: {e}")
            return
        self.camera_widget = CameraWidget(cam)
        self.camera_widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        new_window = QMainWindow()
        new_window.setWindowTitle("Camera")
        new_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        new_window.setCentralWidget(self.camera_widget)
        new_window.show()
        self.open_camera_window = new_window
        self.open_camera_window.destroyed.connect(lambda: setattr(self, "open_camera_window", None))
        self.camera_widget.destroyed.connect(cam.close)


    @Slot(str)
    def display_error(self, msg: str):
        QErrorMessage(self).showMessage(msg)


def get_cam_numbers():
    try:
        return DCAM.get_cameras_number()
    except OSError as e:
        logger.error(f"DCAM API DLL not available: {e}")
        return []


class ChooseCameraWindow(QWidget):
    selection = Signal(int)

    def __init__(self, show_fake: bool = False, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.show_fake = show_fake

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

        for idx in get_cam_numbers():
            self.dropdown.addItem(f"Camera {idx}", userData=idx)
        if self.show_fake:
            self.dropdown.addItem("Fake camera", userData=-1)

        self.button = QPushButton("Connect")
        layout.addWidget(self.button)
        self.button.clicked.connect(self.clicked)

    @Slot()
    def refresh(self):
        self.dropdown.clear()
        for idx in get_cam_numbers():
            self.dropdown.addItem(f"Camera {idx}", userData=idx)
        if self.show_fake:
            self.dropdown.addItem("Fake camera", userData=-1)

    @Slot()
    def clicked(self):
        if (idx := self.dropdown.currentData()) is not None:
            self.selection.emit(idx)


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
