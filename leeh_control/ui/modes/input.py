import logging

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel

from controller import ANC300
from ui.utils import TwoOptionsRadioWidget

logger = logging.getLogger(__name__)


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
