import logging

from PySide6.QtWidgets import QLabel

logger = logging.getLogger(__name__)


class GroundModeWidget(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__("The positioner is grounded.", *args, **kwargs)

    def refresh(self):
        pass
