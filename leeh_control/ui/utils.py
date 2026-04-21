import logging

from typing import Callable

from PySide6.QtCore import Qt, QSize, Signal, Slot, QSignalBlocker
from PySide6.QtGui import QValidator, QIntValidator, QDoubleValidator
from PySide6.QtWidgets import QLineEdit, QToolTip, QStackedWidget, QGroupBox, QHBoxLayout, QButtonGroup, QRadioButton, QPushButton, QWidget

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


def acceptable_input_popup(line_edit: QLineEdit, message: str | None = None) -> bool:
    if line_edit.hasAcceptableInput():
        return True

    tooltip_popup_with_focus(line_edit, message or _validator_error_message(line_edit.validator()))
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


def _setup_two_option_controls(
    parent: QWidget,
    layout: QHBoxLayout,
    false_text: str,
    true_text: str,
    initial: bool,
    on_toggled: Callable[[bool], None],
) -> tuple[QButtonGroup, QRadioButton, QRadioButton]:
    button_group = QButtonGroup(parent)

    false_button = QRadioButton(false_text)
    button_group.addButton(false_button)
    false_button.clicked.connect(lambda: on_toggled(False))
    false_button.setChecked(not initial)
    layout.addWidget(false_button)

    true_button = QRadioButton(true_text)
    button_group.addButton(true_button)
    true_button.clicked.connect(lambda: on_toggled(True))
    true_button.setChecked(initial)
    layout.addWidget(true_button)

    return button_group, false_button, true_button


def _set_two_option_checked(
    target: QWidget,
    false_button: QRadioButton,
    true_button: QRadioButton,
    checked: bool,
):
    with QSignalBlocker(target):
        false_button.setChecked(not checked)
        true_button.setChecked(checked)


class TwoOptionsRadioWidget(QWidget):
    toggled = Signal(bool)

    def __init__(
        self,
        false_text: str,
        true_text: str,
        initial: bool,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button_group, self.false_button, self.true_button = _setup_two_option_controls(
            self,
            layout,
            false_text,
            true_text,
            initial,
            self.toggled.emit,
        )
        self.toggled.connect(self.true_button.setChecked)

    def setChecked(self, checked: bool):
        """Set the checked state w/o emitting the toggled signal."""
        _set_two_option_checked(self, self.false_button, self.true_button, checked)


class TwoOptionsRadioGroupBox(QGroupBox):
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
        self.button_group, self.false_button, self.true_button = _setup_two_option_controls(
            self,
            layout,
            false_text,
            true_text,
            initial,
            self.toggled.emit,
        )
        self.toggled.connect(self.true_button.setChecked)

    def setChecked(self, checked: bool):
        """Set the checked state w/o emitting the toggled signal."""
        _set_two_option_checked(self, self.false_button, self.true_button, checked)


class NumButton(QGroupBox):
    submit = Signal(str)

    @Slot()
    def on_submit(self):
        if not acceptable_input_popup(self.num):
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
