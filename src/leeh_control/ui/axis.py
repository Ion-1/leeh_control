import logging
import functools

from enum import StrEnum
from typing import Callable, Literal

from PySide6.QtCore import Slot, Signal, SignalInstance, QSize, Qt
from PySide6.QtGui import (
    QDoubleValidator,
    QValidator,
    QIntValidator,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QButtonGroup,
    QRadioButton,
    QStackedWidget,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QGroupBox,
    QSizePolicy,
    QScrollArea,
    QFrame,
    QToolTip,
)

from ..config import Limits, ConfigProvider
from ..controller import ANC300

logger = logging.getLogger(__name__)


def rm_trailing_zeroes(x: str) -> str:
    if "." in x:
        return x.rstrip("0").rstrip(".")
    return x


def _validator_error_message(validator: QValidator) -> str:
    if isinstance(validator, QIntValidator):
        return f"Enter an integer between {validator.bottom()} and {validator.top()}."
    if isinstance(validator, QDoubleValidator):
        return (
            "Enter a number between "
            f"{rm_trailing_zeroes(f'{validator.bottom():f}')} and "
            f"{rm_trailing_zeroes(f'{validator.top():f}')}."
        )
    return "Input is invalid."


def tooltip_popup_with_focus(line_edit: QLineEdit, message: str):
    line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
    line_edit.selectAll()
    QToolTip.showText(
        line_edit.mapToGlobal(line_edit.rect().bottomLeft()),
        message,
        line_edit,
        msecShowTime=5000,
    )


def ensure_acceptable_input(line_edit: QLineEdit, message: str | None = None) -> bool:
    validator = line_edit.validator()
    if validator is None:
        return True

    if line_edit.hasAcceptableInput():
        return True

    tooltip_popup_with_focus(line_edit, message or _validator_error_message(validator))
    return False


def attach_validation_balloon(
    line_edit: QLineEdit, call_message: Callable[[QValidator], str] | None = None
):
    line_edit.inputRejected.connect(
        lambda: tooltip_popup_with_focus(
            line_edit,
            call_message(line_edit.validator())
            if call_message is not None
            else _validator_error_message(line_edit.validator()),
        )
    )


class CurrentPageStackedWidget(QStackedWidget):
    """Dynamic sizeHint based on the current widget in the QStackedWidget"""

    def _safe_current_hint(self, minimum: bool = False) -> QSize:
        w = self.currentWidget()
        if w is None:
            return QSize()
        hint = w.minimumSizeHint() if minimum else w.sizeHint()
        return (
            hint
            if hint.isValid() and hint.width() > 0 and hint.height() > 0
            else QSize()
        )

    def sizeHint(self):
        return self._safe_current_hint(minimum=False) or super().sizeHint()

    def minimumSizeHint(self):
        return self._safe_current_hint(minimum=True) or super().minimumSizeHint()


class AxisTitleLineEdit(QLineEdit):
    start_editing = Signal()

    def mouseDoubleClickEvent(self, event):
        self.start_editing.emit()
        super().mouseDoubleClickEvent(event)


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

        self.config.signals.name.connect(self._refresh_name)  # ty:ignore[unresolved-attribute]

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

        self.stp_plus_button = QRadioButton("Step +")
        self.stp_plus_button.clicked.connect(
            self.create_set_mode_slot(self.Modes.Off_plus_step)
        )
        self.mode_group.addButton(self.stp_plus_button)
        layout.addWidget(self.stp_plus_button)

        self.stp_minus_button = QRadioButton("Step -")
        self.stp_minus_button.clicked.connect(
            self.create_set_mode_slot(self.Modes.Off_minus_step)
        )
        self.mode_group.addButton(self.stp_minus_button)
        layout.addWidget(self.stp_minus_button)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.area.setFrameStyle(QFrame.Shape.NoFrame | QFrame.Shadow.Plain)
        self.area.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred
        )
        self.area.setSizeAdjustPolicy(QScrollArea.SizeAdjustPolicy.AdjustToContents)
        layout.addWidget(self.area, stretch=1)

        self.mode_container = QWidget()
        self.mode_container_layout = QVBoxLayout(self.mode_container)
        self.mode_container_layout.setContentsMargins(0, 0, 0, 0)
        self.mode_container_layout.setSizeConstraint(
            QVBoxLayout.SizeConstraint.SetMinAndMaxSize
        )

        self.mode_stack = CurrentPageStackedWidget()
        self.mode_stack.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Maximum
        )
        self.mode_stack.currentChanged.connect(lambda _: self._refresh_geometry())

        self.mode_container_layout.addWidget(self.mode_stack)
        self.mode_container_layout.addStretch(1)
        self.area.setWidget(self.mode_container)

        self.stepping_widget = SteppingModeWidget(
            aid,
            controller,
            self.config.step_V_lim,
            self.config.freq_lim,
            self.config.up,
            self.config.down,
        )
        self.offset_widget = ScanningModeWidget(
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

        self.refresh()

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
        if not ensure_acceptable_input(
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
        self.area.updateGeometry()
        self.updateGeometry()
        self.adjustSize()

    def refresh(self):
        self._refresh_name()
        self.capacitance_widget.refresh()
        self.filter_widget.refresh()

        self._refresh_mode()
        self.mode_stack.currentWidget().refresh()  # ty:ignore[unresolved-attribute]
        self._refresh_geometry()


class CapacitanceModeWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)

        self.label = QLabel("Something broke. You shouldn't be here.")
        layout.addWidget(self.label)

    def refresh(self):
        pass


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


class GroundModeWidget(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__("The positioner is grounded.", *args, **kwargs)

    def refresh(self):
        pass


class InputModeWidget(QWidget):
    def __init__(self, aid: int, controller: ANC300, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)

        self.aid = aid
        self.controller = controller

        initial_state = self.controller.get_external_input_modes(self.aid)

        self.ac_in = TwoOptionsRadioWidget(
            "AC-In", "Disabled", "Enabled", initial_state[0]
        )
        self.ac_in.toggled.connect(self.ac_in_toggled)
        layout.addWidget(self.ac_in)

        self.dc_in = TwoOptionsRadioWidget(
            "DC-In", "Disabled", "Enabled", initial_state[1]
        )
        self.dc_in.toggled.connect(self.dc_in_toggled)
        layout.addWidget(self.dc_in)

        self.notice = QGroupBox("Note:")
        self.notice_label = QLabel(
            "Changing the mode does not affect the DC-In or AC-In settings."
        )
        self.notice.setLayout(notice_lay := QVBoxLayout())
        notice_lay.addWidget(self.notice_label)
        layout.addWidget(self.notice)

    def set_checked(self, acin: bool, dcin: bool):
        self.ac_in.setChecked(acin)
        self.dc_in.setChecked(dcin)

    @Slot(bool)
    def dc_in_toggled(self, enabled: bool):
        acin, dcin = self.controller.set_external_input_modes(self.aid, None, enabled)
        self.set_checked(acin, dcin)

    @Slot(bool)
    def ac_in_toggled(self, enabled: bool):
        acin, dcin = self.controller.set_external_input_modes(self.aid, enabled, None)
        self.set_checked(acin, dcin)

    def refresh(self):
        state = self.controller.get_external_input_modes(self.aid)
        self.ac_in.setChecked(state[0])
        self.dc_in.setChecked(state[1])


class TwoOptionsRadioWidget(QGroupBox):
    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        false_text: str,
        true_text: str,
        initial: bool,
        *args,
        **kwargs,
    ):
        super().__init__(title, *args, **kwargs)

        layout = QHBoxLayout(self)

        self.button_group = QButtonGroup()

        self.false_button = QRadioButton(false_text)
        self.button_group.addButton(self.false_button)
        self.false_button.clicked.connect(self.emit_factory(False))
        self.false_button.setChecked(not initial)
        layout.addWidget(self.false_button)

        self.true_button = QRadioButton(true_text)
        self.button_group.addButton(self.true_button)
        self.true_button.clicked.connect(self.emit_factory(True))
        self.true_button.setChecked(initial)
        layout.addWidget(self.true_button)

        self.toggled.connect(self.true_button.setChecked)

    def emit_factory(self, output: bool):
        @Slot()
        def emit_toggled():
            self.toggled.emit(output)

        return emit_toggled

    def setChecked(self, checked: bool):
        self.false_button.setChecked(not checked)
        self.true_button.setChecked(checked)


class ScanningModeWidget(QWidget):
    def __init__(self, aid: int, controller: ANC300, bottom, top, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)

        self.aid = aid
        self.controller = controller

        self.scan_widget = ScanWidget(
            "Offset (V)",
            self.controller.get_offset(aid),
            bottom,
            top,
            [
                ("-20", lambda x: x - 20),
                ("-10", lambda x: x - 10),
                ("-1", lambda x: x - 1),
            ],
            [
                ("+1", lambda x: x + 1),
                ("+10", lambda x: x + 10),
                ("+20", lambda x: x + 20),
            ],
        )
        self.scan_widget.changed.connect(self.on_scan_changed)
        layout.addWidget(self.scan_widget)

    @Slot(float)
    def on_scan_changed(self, offset: float):
        # We rely on ScanWidget for validation and conversion.
        self.scan_widget.set_active_unvalidated(
            self.controller.set_offset(self.aid, offset)
        )

    @Slot(float, float)
    def refresh_limits(self, bottom: float, top: float):
        self.scan_widget.refresh_limits(bottom, top)

    def refresh(self):
        """
        "For security, the voltage value will be set to zero when disabling
        the offset voltage feature." - ANC300 manual
        """
        self.scan_widget.set_active_unvalidated(self.controller.get_offset(self.aid))


class ScanWidget(QGroupBox):
    changed = Signal(float)

    def __init__(
        self,
        title: str,
        active_V: float,
        bottom: float,
        top: float,
        left_steps: list[tuple[str, Callable[[float], float]]],
        right_steps: list[tuple[str, Callable[[float], float]]],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.setTitle(title)

        self.top = float(top)
        self.bottom = float(bottom)
        self.validator = QDoubleValidator(bottom=bottom, top=top, decimals=6)
        self.validator.setNotation(QDoubleValidator.Notation.StandardNotation)

        layout = QVBoxLayout(self)

        self.line_edit = QLineEdit()
        self.line_edit.setText(self.convert_to_str(active_V))
        self.line_edit.setValidator(self.validator)
        attach_validation_balloon(
            self.line_edit,
            lambda validator: (
                f"Enter a value between {validator.bottom():g} and {validator.top():g}."
            ),
        )
        self.line_edit.editingFinished.connect(self._emit_changed_if_valid)

        layout1 = QHBoxLayout()
        for ls_label, ls_call in left_steps:
            layout1.addWidget(but := QPushButton(ls_label))
            but.clicked.connect(functools.partial(self.on_step_clicked, func=ls_call))
        layout.addLayout(layout1)

        layout.addWidget(self.line_edit)

        layout2 = QHBoxLayout()
        for rs_label, rs_call in right_steps:
            layout2.addWidget(but := QPushButton(rs_label))
            but.clicked.connect(functools.partial(self.on_step_clicked, func=rs_call))
        layout.addLayout(layout2)

    @Slot(float, float)
    def refresh_limits(self, bottom: float, top: float):
        self.validator.setRange(bottom, top)
        self.bottom = bottom
        self.top = top

    @Slot()
    def on_step_clicked(self, func: Callable[[float], float]):
        if not ensure_acceptable_input(
            self.line_edit,
            f"Enter a value between {self.bottom:g} and {self.top:g}.",
        ):
            return
        self.wrap_call(func)(self.line_edit.text())

    @Slot()
    def _emit_changed_if_valid(self):
        if not ensure_acceptable_input(
            self.line_edit,
            f"Enter a value between {self.bottom:g} and {self.top:g}.",
        ):
            return
        self.changed.emit(self.convert_to_float(self.line_edit.text()))

    def wrap_call(self, func: Callable[[float], float]):
        @Slot(str)
        @functools.wraps(func)
        def wrapped(x: str):
            mod = func(self.convert_to_float(x))
            clipped = (
                self.bottom
                if self.bottom > mod
                else self.top
                if self.top < mod
                else mod
            )
            if clipped != mod:
                self.line_edit.inputRejected.emit()
            print(
                self.convert_to_str(clipped),
                self.line_edit.text(),
                self.convert_to_str(clipped) == self.line_edit.text(),
            )
            if (clipped_str := self.convert_to_str(clipped)) == self.line_edit.text():
                return
            self.line_edit.setText(clipped_str)

            # We emit editingFinished instead of changed, so the signal is aware of the change and
            # won't misfire when the user focuses and unfocuses the line edit w/o changing the value
            # We can afford the wasted computation

            # Does not work :( but bug still applies
            # self.line_edit.editingFinished.emit()

            # Workaround: We focus and unfocus the LineEdit to trigger editingFinished
            self.line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            self.line_edit.clearFocus()

            # self.changed.emit(clipped)

        return wrapped

    def convert_to_str(self, x: float) -> str:
        return rm_trailing_zeroes(self.validator.locale().toString(x, "f", 6))

    def convert_to_float(self, x: str) -> float:
        fl = self.validator.locale().toDouble(x)
        if (ok := fl[1]) is not None and not ok:
            logger.error(
                f"Error parsing {x} as float even though it should be validated"
            )
        return fl[0]

    def set_active_unvalidated(self, val: float):
        self.line_edit.setText(self.convert_to_str(val))


class SteppingModeWidget(QWidget):
    def __init__(
        self,
        aid: int,
        controller: ANC300,
        stepV_lims: Limits[float],
        freq_lims: Limits[int],
        up_name: str,
        down_name: str,
        *args,
        mode: Literal["hold", "toggle"] = "hold",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.aid = aid
        self.controller = controller
        self.frequency_validator = QIntValidator(**freq_lims)
        self.voltage_validator = QDoubleValidator(**stepV_lims, decimals=6)
        self.voltage_validator.setNotation(QDoubleValidator.Notation.StandardNotation)

        layout = QVBoxLayout(self)

        self.frequency = NumButton(
            "Frequency (Hz)",
            f"{int(self.controller.get_frequency(self.aid))}",
            validator=self.frequency_validator,
        )
        layout.addWidget(self.frequency)
        self.frequency.submit.connect(self.set_freq)

        self.voltage = NumButton(
            "Voltage (V)",
            f"{self.controller.get_voltage(self.aid):f}",
            validator=self.voltage_validator,
        )
        layout.addWidget(self.voltage)
        self.voltage.submit.connect(self.set_voltage)

        self.plusminus = StepsWidget(
            "Move #n steps", up_name=up_name, down_name=down_name, placeholder="n"
        )
        layout.addWidget(self.plusminus)
        self.plusminus.step_signal.connect(self.step)

        self.continuously_stop = ContinuousStepsWidget(
            f"Continuous Stepping ({mode.capitalize()})",
            up_name=up_name,
            down_name=down_name,
            mode=mode,
        )
        layout.addWidget(self.continuously_stop)

        self.continuously_stop.left_signal.connect(lambda: self.step("c-"))
        self.continuously_stop.middle_signal.connect(self.stop)
        self.continuously_stop.right_signal.connect(lambda: self.step("c+"))

        self.stop_button = QPushButton("STOP")
        layout.addWidget(self.stop_button)
        self.stop_button.pressed.connect(self.stop)

    @Slot(str)
    def set_freq(self, freq: str):
        freqs = int(freq)
        assert (
            self.frequency_validator.bottom() <= freqs <= self.frequency_validator.top()
        )
        self.frequency.setText(f"{int(self.controller.set_frequency(self.aid, freqs))}")

    @Slot(str)
    def set_voltage(self, voltage: str):
        volts = float(voltage)
        assert self.voltage_validator.bottom() <= volts <= self.voltage_validator.top()
        self.voltage.setText(f"{self.controller.set_voltage(self.aid, volts):f}")

    @Slot(int, int)
    def refresh_freq_limits(self, bottom: int, top: int):
        self.frequency_validator.setRange(bottom, top)

    @Slot(float, float)
    def refresh_stepV_limits(self, bottom: float, top: float):
        self.voltage_validator.setRange(bottom, top, self.voltage_validator.decimals())

    @Slot(str)
    def refresh_up_name(self, up_name: str):
        self.plusminus.set_up_name(up_name)
        self.continuously_stop.set_up_name(up_name)

    @Slot(str)
    def refresh_down_name(self, down_name: str):
        self.plusminus.set_down_name(down_name)
        self.continuously_stop.set_down_name(down_name)

    @Slot(int)
    def step(self, steps):
        self.controller.step(self.aid, steps)

    @Slot()
    def stop(self):
        self.controller.stop(self.aid)

    def refresh(self):
        self.frequency.setText(f"{int(self.controller.get_frequency(self.aid))}")
        self.voltage.setText(f"{self.controller.get_voltage(self.aid):f}")


class StepsWidget(QGroupBox):
    step_signal = Signal(int)

    def convert_to_str(self, x: int) -> str:
        return rm_trailing_zeroes(self.validator.locale().toString(x))

    def converter(self, x: str) -> int:
        intg = self.validator.locale().toInt(x)
        if (ok := intg[1]) is not None and not ok:
            logger.error(f"Error parsing {x} as int even though it should be validated")
        return intg[0]

    @Slot()
    def on_step_down(self):
        if not ensure_acceptable_input(self.line_edit):
            return
        steps = self.converter(self.line_edit.text())
        assert 0 <= steps <= 10000
        if steps == 0:
            return
        self.step_signal.emit(-steps)

    @Slot()
    def on_step_up(self):
        if not ensure_acceptable_input(self.line_edit):
            return
        steps = self.converter(self.line_edit.text())
        assert 0 <= steps <= 10000
        if steps == 0:
            return
        self.step_signal.emit(steps)

    def _down_button_text(self) -> str:
        return f"<-[{self.down_name}]-"

    def _up_button_text(self) -> str:
        return f"-[{self.up_name}]->"

    @Slot(str)
    def set_up_name(self, up_name: str):
        self.up_name = up_name
        self.step_up_button.setText(self._up_button_text())

    @Slot(str)
    def set_down_name(self, down_name: str):
        self.down_name = down_name
        self.step_down_button.setText(self._down_button_text())

    @Slot(str, str)
    def set_step_names(self, up_name: str, down_name: str):
        self.set_up_name(up_name)
        self.set_down_name(down_name)

    def __init__(
        self,
        title,
        up_name: str = "up",
        down_name: str = "down",
        placeholder: str = "",
        *args,
        **kwargs,
    ):
        super().__init__(title, *args, **kwargs)

        self.up_name = up_name
        self.down_name = down_name

        layout = QHBoxLayout(self)

        self.step_down_button = QPushButton(self._down_button_text())
        self.step_down_button.clicked.connect(self.on_step_down)
        layout.addWidget(self.step_down_button)

        self.line_edit = QLineEdit()
        layout.addWidget(self.line_edit)
        self.validator = QIntValidator(0, 10000)
        self.line_edit.setValidator(self.validator)
        attach_validation_balloon(self.line_edit)
        self.line_edit.setPlaceholderText(placeholder)

        self.step_up_button = QPushButton(self._up_button_text())
        self.step_up_button.clicked.connect(self.on_step_up)
        layout.addWidget(self.step_up_button)


class ContinuousStepsWidget(QGroupBox):
    left_signal = Signal()
    middle_signal = Signal()
    right_signal = Signal()

    def _left_button_text(self) -> str:
        return f"{self.down_name}"

    def _right_button_text(self) -> str:
        return f"{self.up_name}"

    @Slot(str)
    def set_up_name(self, up_name: str):
        self.up_name = up_name
        self.right_button.setText(self._right_button_text())

    @Slot(str)
    def set_down_name(self, down_name: str):
        self.down_name = down_name
        self.left_button.setText(self._left_button_text())

    @Slot()
    def on_left(self):
        self.left_signal.emit()

    @Slot()
    def on_middle(self):
        self.middle_signal.emit()

    @Slot()
    def on_right(self):
        self.right_signal.emit()

    def on_toggle(self, side: SignalInstance):
        @Slot(bool)
        def toggle_side(checked: bool):
            if checked:
                side.emit()
            else:
                self.middle_signal.emit()

        return toggle_side

    def __init__(
        self,
        title: str,
        up_name: str = "up",
        down_name: str = "down",
        *args,
        mode: Literal["hold", "toggle"] = "hold",
        **kwargs,
    ):
        super().__init__(title, *args, **kwargs)

        self.up_name = up_name
        self.down_name = down_name

        layout = QHBoxLayout(self)

        self.left_button = QPushButton(self._left_button_text())
        layout.addWidget(self.left_button)

        self.right_button = QPushButton(self._right_button_text())
        layout.addWidget(self.right_button)

        if mode == "hold":
            self.left_button.pressed.connect(self.on_left)
            self.right_button.pressed.connect(self.on_right)
            self.left_button.released.connect(self.on_middle)
            self.right_button.released.connect(self.on_middle)
        if mode == "toggle":
            self.left_button.setCheckable(True)
            self.right_button.setCheckable(True)
            self.left_button.toggled.connect(self.on_toggle(self.left_signal))
            self.right_button.toggled.connect(self.on_toggle(self.right_signal))


class NumButton(QGroupBox):
    submit = Signal(str)

    @Slot()
    def on_submit(self):
        if not ensure_acceptable_input(self.num):
            logger.error(
                f"Invalid input {self.num.text()} for NumButton {self.title()}"
            )
            return
        self.submit.emit(self.num.text())

    def __init__(self, title: str, text: str, validator: QValidator, *args, **kwargs):
        super().__init__(title, *args, **kwargs)

        layout = QHBoxLayout(self)

        self.num = QLineEdit()
        self.num.setValidator(validator)
        self.num.setText(text)
        layout.addWidget(self.num)
        attach_validation_balloon(self.num)

        self.submit_button = QPushButton("Set")
        self.submit_button.clicked.connect(self.on_submit)
        layout.addWidget(self.submit_button)

    def setText(self, text: str):
        self.num.setText(text)


class ScanAndStepModeWidget(QWidget):
    def __init__(
        self,
        aid: int,
        controller: ANC300,
        off_lim: Limits[float],
        stepV_lim: Limits[float],
        freq_lim: Limits[int],
        up,
        down,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)

        self.aid = aid
        self.controller = controller

        self.scan_widget = ScanningModeWidget(aid, controller, **off_lim)
        layout.addWidget(self.scan_widget)

        self.step_widget = SteppingModeWidget(
            aid, controller, stepV_lim, freq_lim, up, down
        )
        layout.addWidget(self.step_widget)

    def refresh(self):
        self.scan_widget.refresh()
        self.step_widget.refresh()

    @Slot(int, int)
    def refresh_freq_limits(self, bottom: int, top: int):
        self.step_widget.refresh_freq_limits(bottom, top)

    @Slot(float, float)
    def refresh_stepV_limits(self, bottom: float, top: float):
        self.step_widget.refresh_stepV_limits(bottom, top)

    @Slot(str)
    def refresh_up_name(self, up_name: str):
        self.step_widget.refresh_up_name(up_name)

    @Slot(str)
    def refresh_down_name(self, down_name: str):
        self.step_widget.refresh_down_name(down_name)
