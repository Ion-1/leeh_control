import logging
import functools

from typing import Callable

from PySide6.QtCore import Slot, Signal, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLineEdit, QHBoxLayout, QPushButton

from ..controller import ANC300
from ..utils import rm_trailing_zeroes_float, ensure_acceptable_input, attach_validation_balloon

logger = logging.getLogger(__name__)


class OffsetModeWidget(QWidget):
    def __init__(self, aid: int, controller: ANC300, bottom, top, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)

        self.aid = aid
        self.controller = controller

        self.scan_widget = OffsetWidget(
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
        # We rely on OffsetWidget for validation and conversion.
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


class OffsetWidget(QGroupBox):
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
        return rm_trailing_zeroes_float(self.validator.locale().toString(x, "f", 6))

    def convert_to_float(self, x: str) -> float:
        fl = self.validator.locale().toDouble(x)
        if (ok := fl[1]) is not None and not ok:
            logger.error(
                f"Error parsing {x} as float even though it should be validated"
            )
        return fl[0]

    def set_active_unvalidated(self, val: float):
        self.line_edit.setText(self.convert_to_str(val))
