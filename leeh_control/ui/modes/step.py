import logging
from typing import Literal

from PySide6.QtCore import Slot, Signal, SignalInstance
from PySide6.QtGui import QIntValidator, QDoubleValidator
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QGroupBox, QHBoxLayout, QLineEdit

from ...config import Limits
from ...controller import ANC300
from ..utils import NumButton, rm_trailing_zeroes_float, acceptable_input_popup, attach_validation_balloon

logger = logging.getLogger(__name__)


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
        return rm_trailing_zeroes_float(self.validator.locale().toString(x))

    def converter(self, x: str) -> int:
        intg = self.validator.locale().toInt(x)
        if (ok := intg[1]) is not None and not ok:
            logger.error(f"Error parsing {x} as int even though it should be validated")
        return intg[0]

    @Slot()
    def on_step_down(self):
        if not acceptable_input_popup(self.line_edit):
            return
        steps = self.converter(self.line_edit.text())
        assert 0 <= steps <= 10000
        if steps == 0:
            return
        self.step_signal.emit(-steps)

    @Slot()
    def on_step_up(self):
        if not acceptable_input_popup(self.line_edit):
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
