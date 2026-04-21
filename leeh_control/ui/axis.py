import logging

from enum import StrEnum

from PySide6.QtCore import Slot, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QButtonGroup,
    QRadioButton,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QFrame,
)

from .modes.ground import GroundModeWidget
from .modes.input import InputModeWidget
from .modes.off_and_step import ScanAndStepModeWidget
from .modes.offset import OffsetModeWidget
from .modes.step import SteppingModeWidget
from .utils import acceptable_input_popup, CurrentPageStackedWidget, AxisTitleLineEdit
from ..config import ConfigProvider
from ..controller import ANC300

logger = logging.getLogger(__name__)


class ANM300Widget(QFrame):
    AXIS_NAME_MAX_LENGTH = 64

    class Modes(StrEnum):
        Ground = "gnd"
        Input = "inp"
        Capacitance = "cap"
        Stepping = "stp"
        Offset = "off"
        Off_plus_step = "stp+"
        Off_minus_step = "stp-"

    class FilterModes(StrEnum):
        Off = "off"
        F16 = "16"
        F160 = "160"

    def __init__(
        self,
        serial: str,
        aid: int,
        controller: ANC300,
        config_provider: ConfigProvider,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)

        self.serial = serial
        self.aid = aid
        self.controller = controller
        self.config_provider = config_provider
        self.config = config_provider.axis_config(serial)
        self.general_config = config_provider.general_config()

        self.config.signals.name.connect(self._refresh_name)  # ty:ignore[unresolved-attribute]
        self.general_config.signals.advanced_mode.connect(self.advanced_mode_toggled)  # ty:ignore[unresolved-attribute]

        layout = QVBoxLayout(self)

        self.label = AxisTitleLineEdit()
        self.label.setMaxLength(self.AXIS_NAME_MAX_LENGTH)
        self.label.start_editing.connect(self._start_label_editing)
        self.label.editingFinished.connect(self._finish_label_editing)
        self._show_label_text()
        layout.addWidget(self.label)

        self.mode_group = QButtonGroup()

        self.gnd_button = QRadioButton("Ground")
        self.gnd_button.clicked.connect(self.create_set_mode_slot(self.Modes.Ground))
        self.mode_group.addButton(self.gnd_button)
        layout.addWidget(self.gnd_button)

        self.inp_button = QRadioButton("Input")
        self.inp_button.clicked.connect(self.create_set_mode_slot(self.Modes.Input))
        self.mode_group.addButton(self.inp_button)
        layout.addWidget(self.inp_button)

        self.step_button = QRadioButton("Stepping")
        self.step_button.clicked.connect(self.create_set_mode_slot(self.Modes.Stepping))
        self.mode_group.addButton(self.step_button)
        layout.addWidget(self.step_button)

        self.off_button = QRadioButton("Offset")
        self.off_button.clicked.connect(self.create_set_mode_slot(self.Modes.Offset))
        self.mode_group.addButton(self.off_button)
        layout.addWidget(self.off_button)

        self.stp_plus_button = QRadioButton("Offset + Step")
        self.stp_plus_button.clicked.connect(
            self.create_set_mode_slot(self.Modes.Off_plus_step)
        )
        self.mode_group.addButton(self.stp_plus_button)
        layout.addWidget(self.stp_plus_button)

        self.stp_minus_button = QRadioButton("Offset - Step")
        self.stp_minus_button.clicked.connect(
            self.create_set_mode_slot(self.Modes.Off_minus_step)
        )
        self.mode_group.addButton(self.stp_minus_button)
        layout.addWidget(self.stp_minus_button)

        self.mode_container = QWidget()
        self.mode_container.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred
        )
        self.mode_container_layout = QVBoxLayout(self.mode_container)
        self.mode_container_layout.setContentsMargins(0, 0, 0, 0)
        self.mode_container_layout.setSizeConstraint(
            QVBoxLayout.SizeConstraint.SetMinAndMaxSize
        )
        layout.addWidget(self.mode_container, stretch=1)

        self.mode_stack = CurrentPageStackedWidget()
        self.mode_stack.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Maximum
        )
        self.mode_stack.currentChanged.connect(lambda _: self._refresh_geometry())

        self.mode_container_layout.addWidget(self.mode_stack)
        self.mode_container_layout.addStretch(1)

        self.stepping_widget = SteppingModeWidget(
            aid,
            controller,
            self.config.step_V_lim,
            self.config.freq_lim,
            self.config.up,
            self.config.down,
        )
        self.offset_widget = OffsetModeWidget(
            aid, controller, **self.config.offset_lim
        )
        self.input_widget = InputModeWidget(aid, controller)
        self.scan_and_step_widget = ScanAndStepModeWidget(
            aid,
            controller,
            self.config.offset_lim,
            self.config.step_V_lim,
            self.config.freq_lim,
            self.config.up,
            self.config.down,
        )

        self.stack_indices = {
            self.Modes.Ground: self.mode_stack.addWidget(GroundModeWidget()),
            self.Modes.Stepping: self.mode_stack.addWidget(self.stepping_widget),
            self.Modes.Offset: self.mode_stack.addWidget(self.offset_widget),
            self.Modes.Input: self.mode_stack.addWidget(self.input_widget),
            self.Modes.Off_minus_step: (
                step_scan_int := self.mode_stack.addWidget(self.scan_and_step_widget)
            ),
            self.Modes.Off_plus_step: step_scan_int,
            self.Modes.Capacitance: self.mode_stack.addWidget(CapacitanceModeWidget()),
        }

        self.config.signals.offset_lim.connect(  # ty:ignore[unresolved-attribute]
            lambda: self.offset_widget.refresh_limits(**self.config.offset_lim)
        )
        self.config.signals.freq_lim.connect(  # ty:ignore[unresolved-attribute]
            lambda: (
                self.stepping_widget.refresh_freq_limits(**self.config.freq_lim),
                self.scan_and_step_widget.refresh_freq_limits(**self.config.freq_lim),
            )
        )
        self.config.signals.step_V_lim.connect(  # ty:ignore[unresolved-attribute]
            lambda: (
                self.stepping_widget.refresh_stepV_limits(**self.config.step_V_lim),
                self.scan_and_step_widget.refresh_stepV_limits(
                    **self.config.step_V_lim
                ),
            )
        )
        self.config.signals.up.connect(  # ty:ignore[unresolved-attribute]
            lambda: (
                self.stepping_widget.refresh_up_name(self.config.up),
                self.scan_and_step_widget.refresh_up_name(self.config.up),
            )
        )
        self.config.signals.down.connect(  # ty:ignore[unresolved-attribute]
            lambda: (
                self.stepping_widget.refresh_down_name(self.config.down),
                self.scan_and_step_widget.refresh_down_name(self.config.down),
            )
        )

        self.filter_widget = FilterWidget(aid, controller, self.FilterModes)
        layout.addWidget(self.filter_widget)

        self.capacitance_widget = CapacitanceWidget(aid, controller)
        layout.addWidget(self.capacitance_widget)

        self._set_advanced_mode(self.general_config.advanced_mode)
        self.refresh()

    def _set_advanced_mode(self, advanced_mode: bool):
        self.advanced_mode = advanced_mode
        self.inp_button.setVisible(advanced_mode)
        self.stp_plus_button.setVisible(advanced_mode)
        self.stp_minus_button.setVisible(advanced_mode)

        if not advanced_mode:
            self.step_button.setText("Coarse Stepping")
            self.off_button.setText("Fine Positioning Offset")
            # self.stp_plus_button.setText("Fine Positioning Offset plus Coarse Stepping")
            # self.stp_minus_button.setText("Fine Positioning Offset minus Coarse Stepping")
        else:
            self.step_button.setText("Stepping")
            self.off_button.setText("Offset")
            # self.stp_plus_button.setText("Offset plus Step")
            # self.stp_minus_button.setText("Offset minus Step")

    @Slot()
    def advanced_mode_toggled(self):
        self._set_advanced_mode(self.general_config.advanced_mode)

    def _label_text(self) -> str:
        if (name := self.config.name) is not None:
            return f"{name} (AID {self.aid}) ({self.serial})"
        return f"Axis {self.aid} ({self.serial})"

    def _show_label_text(self):
        self.label.setReadOnly(True)
        self.label.setFrame(False)
        self.label.setStyleSheet("QLineEdit { border: none; background: transparent; }")
        self.label.setText(self._label_text())
        self.label.setCursorPosition(0)

    @Slot()
    def _start_label_editing(self):
        self.label.setReadOnly(False)
        self.label.setFrame(True)
        self.label.setStyleSheet("")
        self.label.setText(self.config.name or "")
        self.label.selectAll()
        self.label.setFocus(Qt.FocusReason.MouseFocusReason)

    @Slot()
    def _finish_label_editing(self):
        if self.label.isReadOnly():
            return
        if not acceptable_input_popup(
            self.label,
            f"Axis name must be at most {self.AXIS_NAME_MAX_LENGTH} characters.",
        ):
            return
        if self.label.text() != "":
            self.config.name = self.label.text()
        else:
            self.config.name = None

    def create_set_mode_slot(self, mode: Modes):
        """
        Factory method for creating a slot for setting the mode of the axis.
        Do not create a slot for capacitance mode, which gets handled specially.
        """

        @Slot()
        def set_mode():
            self.controller.set_mode(self.aid, mode)
            self.mode_stack.setCurrentIndex(self.stack_indices[mode])
            self.mode_stack.currentWidget().refresh()  # ty:ignore[unresolved-attribute]
            self._refresh_geometry()

        return set_mode

    def _refresh_name(self):
        self._show_label_text()

    def _refresh_mode(self):
        mode = self.Modes(self.controller.get_mode(self.aid))
        if mode == self.Modes.Ground:
            self.gnd_button.setChecked(True)
        elif mode == self.Modes.Input:
            self.inp_button.setChecked(True)
        elif mode == self.Modes.Stepping:
            self.step_button.setChecked(True)
        elif mode == self.Modes.Offset:
            self.off_button.setChecked(True)
        elif mode == self.Modes.Off_minus_step:
            self.stp_minus_button.setChecked(True)
        elif mode == self.Modes.Off_plus_step:
            self.stp_plus_button.setChecked(True)
        else:
            logger.fatal(f"Unknown mode {mode}")
        self.mode_stack.setCurrentIndex(self.stack_indices[mode])

    def _refresh_geometry(self):
        self.mode_stack.updateGeometry()
        self.mode_container.updateGeometry()
        self.updateGeometry()
        self.adjustSize()

    def refresh(self):
        self._refresh_name()
        self.capacitance_widget.refresh()
        self.filter_widget.refresh()

        self._refresh_mode()
        self.mode_stack.currentWidget().refresh()  # ty:ignore[unresolved-attribute]
        self._refresh_geometry()


class FilterWidget(QWidget):
    def __init__(
        self, aid: int, controller: ANC300, filter_enum: type[StrEnum], *args, **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.aid = aid
        self.controller = controller
        self.filter_enum = filter_enum

        layout = QHBoxLayout(self)

        self.label = QLabel("Power Filter: ")
        layout.addWidget(self.label)

        self.button_group = QButtonGroup()

        active = self.controller.get_filter(self.aid)

        self.buttons = []

        for filter_ in self.filter_enum:
            button = QRadioButton()
            button.setText(filter_)
            button.setChecked(active == filter_)
            button.clicked.connect(self.set_filter_factory(filter_))

            self.buttons.append(button)
            self.button_group.addButton(button)
            layout.addWidget(button)

    def set_filter_factory(self, filter_: str):
        @Slot()
        def set_filter():
            self.set_active(self.controller.set_filter(self.aid, filter_))

        return set_filter

    def set_active(self, filter_: str):
        for button in self.buttons:
            button.setChecked(filter_ == button.text())

    def refresh(self):
        self.set_active(self.controller.get_filter(self.aid))


class CapacitanceModeWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)

        self.label = QLabel("Something broke. You shouldn't be here.")
        layout.addWidget(self.label)

    def refresh(self):
        pass


class CapacitanceWidget(QWidget):
    def __init__(self, aid: int, controller: ANC300, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.aid = aid
        self.controller = controller

        layout = QHBoxLayout(self)

        self.label = QLabel(
            f"Capacitance: {self.controller.get_capacitance(self.aid, measure=True) * 1e9:f} nF"
        )
        layout.addWidget(self.label)

        self.measure_button = QPushButton("Measure")
        self.measure_button.clicked.connect(self.measure)
        layout.addWidget(self.measure_button)

    def refresh(self):
        self.label.setText(
            f"Capacitance: {self.controller.get_capacitance(self.aid, measure=False) * 1e9:f} nF"
        )

    @Slot()
    def measure(self):
        self.label.setText(
            f"Capacitance: {self.controller.get_capacitance(self.aid, measure=True) * 1e9:f} nF"
        )

