import logging

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout

from ...config import Limits
from ...controller import ANC300
from .offset import OffsetModeWidget
from .step import SteppingModeWidget

logger = logging.getLogger(__name__)


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

        self.scan_widget = OffsetModeWidget(aid, controller, **off_lim)
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
