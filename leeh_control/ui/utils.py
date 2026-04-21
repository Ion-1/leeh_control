import logging

from typing import Callable

from PySide6.QtCore import Qt, QSize, Signal, Slot, QSignalBlocker
from PySide6.QtGui import QValidator, QIntValidator, QDoubleValidator
from PySide6.QtWidgets import QLineEdit, QToolTip, QStackedWidget, QGroupBox, QHBoxLayout, QButtonGroup, QRadioButton, QPushButton

logger = logging.getLogger(__name__)


def rm_trailing_zeroes_float(x: str) -> str:
    if "." in x:
        return x.rstrip("0").rstrip(".")
    return x


def _validator_error_message(validator: QValidator) -> str:
    if isinstance(validator, QIntValidator):
        return f"Enter an integer between {validator.bottom()} and {validator.top()}."
    if isinstance(validator, QDoubleValidator):
        return (
            "Enter a number between "
            f"{rm_trailing_zeroes_float(f'{validator.bottom():f}')} and "
            f"{rm_trailing_zeroes_float(f'{validator.top():f}')}."
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
        """Set the checked state w/o emitting the toggled signal."""
        with QSignalBlocker(self):
            self.false_button.setChecked(not checked)
            self.true_button.setChecked(checked)


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
