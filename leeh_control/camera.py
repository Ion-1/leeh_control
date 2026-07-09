import logging

import numpy as np
import pylablib as pll

from PIL import Image, ImageShow
from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QErrorMessage,
)
from pylablib.devices.DCAM import DCAMCamera

logger = logging.getLogger(__name__)


class CameraWidget(QWidget):
    def __init__(self, camera: DCAMCamera | None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.camera = camera
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Camera"))

        self.capture_button = QPushButton("Take picture")
        layout.addWidget(self.capture_button)
        self.capture_button.clicked.connect(self.capture_image)

    @Slot()
    def capture_image(self):
        if self.camera is None:
            image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        else:
            try:
                image = self.camera.snap()
            except Exception as e:
                logger.error(f"Failed to capture image: {e}")
                return
        im = Image.fromarray(image)

        save_location = QFileDialog.getSaveFileName(self, "Save Image", "", "Image Files (*.png *.jpg)")

        if not save_location[0]:
            im.show()
            QErrorMessage(self).showMessage("No file selected; image not saved.")
        else:
            im.save(save_location[0])
            for viewer in ImageShow._viewers:
                if viewer.show_file(save_location[0]):
                    break
            else:
                logger.error("Failed to open image in a viewer.")
