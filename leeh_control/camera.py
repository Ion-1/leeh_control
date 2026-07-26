import math
import logging

import zarr
import numpy as np

from dataclasses import dataclass

from PIL import Image as PILImage
from PySide6.QtCore import Qt, Slot, QSignalBlocker
from PySide6.QtGui import QValidator, QDoubleValidator, QIntValidator, QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QErrorMessage,
    QSlider,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QMainWindow,
    QScrollArea,
    QSplitter,
    QSizePolicy,
)
from pylablib.devices import DCAM
from pylablib.devices.DCAM.dcamprop_defs import DCAMPROPUNIT
from zarr.storage import ZipStore

from .ui.utils import acceptable_input_popup, rm_trailing_zeroes_float, Printable


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CapturedImage:
    data: np.ndarray
    metadata: dict[str, Printable]


class CameraWidget(QWidget):
    def __init__(self, camera: DCAM.DCAMCamera, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.camera = camera

        logger.info(f"Found attributes: {camera.get_all_attributes()}")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Camera"))

        attr = self.camera.get_attribute("EXPOSURE TIME")
        layout.addWidget(DCAMAttributeQWidget(attr))

        self.capture_button = QPushButton("Take picture")
        layout.addWidget(self.capture_button)
        self.capture_button.clicked.connect(self.capture_image_slot)

        self.image_window: MultipleImageViewerWindow | None = None

    @Slot()
    def capture_image_slot(self):
        self.capture_image()

    def capture_image(self):
        try:
            image_data = self.camera.snap()
        except Exception as e:
            logger.error(f"Failed to capture image: {e}")
            return

        # Create CapturedImage object with metadata
        image = CapturedImage(data=image_data, metadata={})

        # Check if image window exists
        if self.image_window is None:
            # Create new window with the image
            self.image_window = MultipleImageViewerWindow(initial_image=image)
            self.image_window.setWindowTitle("Images")
            self.image_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.image_window.destroyed.connect(
                lambda: setattr(self, "image_window", None)
            )
            self.image_window.show()
        else:
            # Add image to existing window
            self.image_window.add_image(image)
            self.image_window.raise_()
            self.image_window.activateWindow()


UNIT_SYMBOLS = {
    DCAMPROPUNIT.DCAMPROP_UNIT_NONE: "",
    DCAMPROPUNIT.DCAMPROP_UNIT_SECOND: "s",
    DCAMPROPUNIT.DCAMPROP_UNIT_CELSIUS: "°C",
    DCAMPROPUNIT.DCAMPROP_UNIT_KELVIN: "K",
    DCAMPROPUNIT.DCAMPROP_UNIT_METERPERSECOND: "m/s",
    DCAMPROPUNIT.DCAMPROP_UNIT_PERSECOND: "1/s",
    DCAMPROPUNIT.DCAMPROP_UNIT_DEGREE: "°",
    DCAMPROPUNIT.DCAMPROP_UNIT_MICROMETER: "µm",
    None: "?",  # represents unknown value returned from API
}


###
### A lot of the following can be made more robust by checking the set DCAMPROP_ATTR_* flags
### for each attribute, but for simplicity we presume AUTOROUNDING exists and will snap the value
### whether or not STEPPING_INCONSISTENT when we set the value outside of the steps
###


class DCAMAttributeQWidget(QWidget):
    def __init__(self, attr: DCAM.DCAM.DCAMAttribute, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)
        unit_name = DCAM.DCAM.dcamprop_defs.drDCAMPROPUNIT.get(
            attr.unit,
            None,
        )
        if unit_name != DCAMPROPUNIT.DCAMPROP_UNIT_NONE:
            layout.addWidget(QLabel(f"{attr.name} [{UNIT_SYMBOLS[attr.unit]}]"))
        else:
            layout.addWidget(QLabel(f"{attr.name} [unitless]"))

        if attr.kind == "int":
            self.control_widget = IntSliderAttributeWidget(attr)
            layout.addWidget(self.control_widget)
        elif attr.kind == "float":
            self.control_widget = FloatSliderAttributeWidget(attr)
            layout.addWidget(self.control_widget)
        elif attr.kind == "enum":
            self.control_widget = EnumAttributeWidget(attr)
            layout.addWidget(self.control_widget)


class IntSliderAttributeWidget(QWidget):
    def __init__(self, attr: DCAM.DCAM.DCAMAttribute, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QHBoxLayout(self)
        self.attr = attr
        self.step = abs(int(attr.step)) or 1
        self.min_value = int(attr.min)
        self.max_value = int(attr.max)
        self.slider_min = 0
        self.slider_max = max(0, (self.max_value - self.min_value) // self.step)

        self.validator = QIntValidator(attr.min, attr.max, self)

        self.curr_val = int(attr.get_value())

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(self.slider_min)
        self.slider.setMaximum(self.slider_max)
        self.slider.setSingleStep(1)
        self.slider.setValue(self._value_to_slider(self.curr_val))
        layout.addWidget(self.slider, stretch=1)

        self.input = QLineEdit(self)
        self.input.setText(str(self.curr_val))
        self.input.setValidator(self.validator)
        layout.addWidget(self.input)

        self.slider.valueChanged.connect(self.on_slider_value_changed)
        self.input.editingFinished.connect(self.on_input_editing_finished)

    def _value_to_slider(self, value: int) -> int:
        slider_value = round((value - self.min_value) / self.step)
        return max(self.slider_min, min(self.slider_max, slider_value))

    def _slider_to_value(self, slider_value: int) -> int:
        return self.min_value + slider_value * self.step

    def _sync_widgets(self, value: int):
        with QSignalBlocker(self.slider), QSignalBlocker(self.input):
            self.curr_val = value
            self.slider.setValue(self._value_to_slider(value))
            self.input.setText(str(value))

    def change_value(self, value: int):
        validation = self.validator.validate(str(value), 0)
        state = validation[0] if isinstance(validation, tuple) else validation
        if state != QValidator.State.Acceptable:
            acceptable_input_popup(
                self.input,
                f"Enter an integer between {self.validator.bottom()} and {self.validator.top()}.",
            )
            return

        try:
            self.attr.set_value(value)
        except Exception as exc:
            logger.error(f"Failed to set {self.attr.name} to {value}: {exc}")
            return

        self.curr_val = int(self.attr.get_value())
        self._sync_widgets(self.curr_val)

    @Slot(int)
    def on_slider_value_changed(self, value: int):
        self.change_value(self._slider_to_value(value))

    @Slot()
    def on_input_editing_finished(self):
        if not acceptable_input_popup(
            self.input,
            f"Enter an integer between {self.validator.bottom()} and {self.validator.top()}.",
        ):
            return

        try:
            parsed_value = int(self.input.text())
        except ValueError:
            logger.error(
                f"Failed to parse {self.input.text()} as an int for {self.attr.name}"
            )
            return

        self.change_value(parsed_value)


class FloatSliderAttributeWidget(QWidget):
    def __init__(self, attr: DCAM.DCAM.DCAMAttribute, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QHBoxLayout(self)
        self.attr = attr
        self.step = abs(float(attr.step)) or 1.0
        self.min_value = float(attr.min)
        self.max_value = float(attr.max)
        self.slider_min = 0
        self.slider_max = max(
            0,
            math.floor(((self.max_value - self.min_value) / self.step) + 1e-9),
        )

        decimals = self._decimals_for_float(self.step, self.min_value, self.max_value)
        self.validator = QDoubleValidator(attr.min, attr.max, decimals, self)
        self.validator.setNotation(QDoubleValidator.Notation.StandardNotation)

        self.curr_val = attr.get_value()

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(self.slider_min)
        self.slider.setMaximum(self.slider_max)
        self.slider.setSingleStep(1)
        self.slider.setValue(self._value_to_slider(self.curr_val))
        layout.addWidget(self.slider, stretch=1)

        self.input = QLineEdit(self)
        self.input.setText(self._value_to_text(self.curr_val))
        self.input.setValidator(self.validator)
        layout.addWidget(self.input)

        self.slider.valueChanged.connect(self.on_slider_value_changed)
        self.input.editingFinished.connect(self.on_input_editing_finished)

    def _decimals_for_float(self, *values: float) -> int:
        decimals = 0
        for value in values:
            text = f"{abs(value):.12f}".rstrip("0").rstrip(".")
            if "." in text:
                decimals = max(decimals, len(text.split(".")[1]))
        return decimals

    def _value_to_text(self, value: float) -> str:
        text = self.validator.locale().toString(value, "f", self.validator.decimals())
        return rm_trailing_zeroes_float(text)

    def _value_to_slider(self, value: float) -> int:
        slider_value = round((value - self.min_value) / self.step)
        return max(self.slider_min, min(self.slider_max, slider_value))

    def _slider_to_value(self, slider_value: int) -> float:
        return self.min_value + slider_value * self.step

    def _sync_widgets(self, value: float):
        with QSignalBlocker(self.slider), QSignalBlocker(self.input):
            self.curr_val = value
            self.slider.setValue(self._value_to_slider(value))
            self.input.setText(self._value_to_text(value))

    def change_value(self, value: float):
        formatted = self._value_to_text(value)
        validation = self.validator.validate(formatted, 0)
        state = validation[0] if isinstance(validation, tuple) else validation
        if state != QValidator.State.Acceptable:
            acceptable_input_popup(
                self.input,
                f"Enter a value between {self.validator.bottom():g} and {self.validator.top():g}.",
            )
            return

        try:
            self.attr.set_value(value)
        except Exception as exc:
            logger.error(f"Failed to set {self.attr.name} to {value}: {exc}")
            return

        self.curr_val = self.attr.get_value()
        self._sync_widgets(self.curr_val)

    @Slot(int)
    def on_slider_value_changed(self, value: int):
        self.change_value(self._slider_to_value(value))

    @Slot()
    def on_input_editing_finished(self):
        if not acceptable_input_popup(
            self.input,
            f"Enter a value between {self.validator.bottom():g} and {self.validator.top():g}.",
        ):
            return

        parsed_value = self.validator.locale().toDouble(self.input.text())
        if not parsed_value[1]:
            logger.error(
                f"Failed to parse {self.input.text()} as a float for {self.attr.name}"
            )
            return

        self.change_value(parsed_value[0])


class EnumAttributeWidget(QWidget):
    def __init__(self, attr: DCAM.DCAM.DCAMAttribute, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)
        self.attr = attr

        self.combo = QComboBox(self)
        for label, index in attr.labels.items():
            self.combo.addItem(str(label), index)
        self._sync_combo(int(attr.get_value()))
        self.combo.currentIndexChanged.connect(self.on_combo_index_changed)
        layout.addWidget(self.combo)

    def _sync_combo(self, value: int):
        with QSignalBlocker(self.combo):
            target_index = self.combo.findData(value)
            if target_index >= 0:
                self.combo.setCurrentIndex(target_index)

    def change_value(self, value: int):
        try:
            self.attr.set_value(value)
        except Exception as exc:
            logger.error(f"Failed to set {self.attr.name} to {value}: {exc}")
            return

        self._sync_combo(int(self.attr.get_value()))

    @Slot(int)
    def on_combo_index_changed(self, index: int):
        value = self.combo.itemData(index)
        if value is None:
            return
        self.change_value(int(value))


class MultipleImageViewerWindow(QMainWindow):
    def __init__(self, initial_image: CapturedImage, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setWindowTitle("Image Viewer")
        self.images: list[CapturedImage] = []
        self.current_image_index = 0
        self._current_pixmap: QPixmap | None = None

        self.images.append(initial_image)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        button_bar = QHBoxLayout()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter = splitter

        layout.addLayout(button_bar)
        layout.addWidget(splitter, stretch=1)

        self.prev_button = QPushButton("◄")
        self.prev_button.clicked.connect(self.show_previous_image)
        button_bar.addWidget(self.prev_button)

        self.image_counter_label = QLabel("1/1")
        self.image_counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        button_bar.addWidget(self.image_counter_label)

        self.next_button = QPushButton("►")
        self.next_button.clicked.connect(self.show_next_image)
        button_bar.addWidget(self.next_button)

        button_bar.addStretch()

        self.save_zarr_button = QPushButton("Save as .zarr.zip")
        self.save_zarr_button.clicked.connect(self.save_as_zarr)
        button_bar.addWidget(self.save_zarr_button)

        self.save_png_button = QPushButton("Save as .png")
        self.save_png_button.clicked.connect(self.save_as_png)
        button_bar.addWidget(self.save_png_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_current_image)
        button_bar.addWidget(self.delete_button)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setScaledContents(False)
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        scroll_area = QScrollArea()
        self.scroll_area = scroll_area
        scroll_area.setWidget(self.image_label)
        scroll_area.setWidgetResizable(True)
        splitter.splitterMoved.connect(self.on_splitter_moved)
        splitter.addWidget(scroll_area)

        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout()
        sidebar_layout.addWidget(QLabel("Metadata"))
        sidebar_widget.setLayout(sidebar_layout)
        splitter.addWidget(sidebar_widget)

        self.metadata_widget = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_widget)
        self.metadata_layout.addStretch()

        metadata_scroll = QScrollArea()
        metadata_scroll.setWidget(self.metadata_widget)
        metadata_scroll.setWidgetResizable(True)
        sidebar_layout.addWidget(metadata_scroll)

        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setHandleWidth(1)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

        self.resize(1000, 600)
        splitter.setSizes([700, 300])

        self.update_display()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fill_image_to_viewport()

    @Slot(int, int)
    def on_splitter_moved(self, pos: int, index: int):
        self.fill_image_to_viewport()

    def fill_image_to_viewport(self):
        if self._current_pixmap is None:
            return

        viewport_size = self.scroll_area.viewport().size()
        if viewport_size.width() > 1 and viewport_size.height() > 1:
            scaled_pixmap = self._current_pixmap.scaled(
                viewport_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.image_label.setPixmap(self._current_pixmap)

    @Slot()
    def show_previous_image(self):
        if len(self.images) > 0:
            self.current_image_index = (self.current_image_index - 1) % len(self.images)
            self.update_display()

    @Slot()
    def show_next_image(self):
        if len(self.images) > 0:
            self.current_image_index = (self.current_image_index + 1) % len(self.images)
            self.update_display()

    def update_display(self):
        if len(self.images) == 0:
            self._current_pixmap = None
            self.image_label.clear()
            self.image_label.setText("No images")
            self.image_counter_label.setText("0/0")
            # Clear metadata
            while self.metadata_layout.count() > 0:
                item = self.metadata_layout.takeAt(0)
                if item is not None:
                    widget = item.widget()
                    if widget:
                        widget.deleteLater()
            self.metadata_layout.addStretch()
            return

        self.image_counter_label.setText(
            f"{self.current_image_index + 1}/{len(self.images)}"
        )

        current_image = self.images[self.current_image_index]

        # Convert numpy array to QPixmap using PIL
        try:
            pil_image = PILImage.fromarray(current_image.data)
            pil_image_rgb = pil_image.convert("RGB")
            data = np.array(pil_image_rgb)
            height, width, _ = data.shape
            bytes_per_line = 3 * width
            q_img = QImage(
                data.data, width, height, bytes_per_line, QImage.Format.Format_RGB888
            )
            pixmap = QPixmap.fromImage(q_img)
        except Exception as e:
            self.image_label.setText(f"Failed to display image: {e}")
            self._current_pixmap = None
            logger.error(f"Failed to display image: {e}")
            return

        self._current_pixmap = pixmap

        while self.metadata_layout.count() > 1:
            item = self.metadata_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget:
                    widget.deleteLater()

        for key, value in current_image.metadata.items():
            label = QLabel(f"{key}: {value}")
            label.setWordWrap(True)
            self.metadata_layout.insertWidget(self.metadata_layout.count() - 1, label)

        self.fill_image_to_viewport()

    @Slot()
    def add_image(self, image: CapturedImage):
        """Add an image to the viewer."""
        self.images.append(image)
        self.current_image_index = len(self.images) - 1
        self.update_display()

    @Slot()
    def save_as_zarr(self):
        if len(self.images) == 0:
            QErrorMessage(self).showMessage("No images to save.")
            return

        file_path = QFileDialog.getSaveFileName(
            self, "Save Image as Zarr", "", "Zarr Zip Files (*.zarr.zip)"
        )[0]

        if not file_path:
            return

        try:
            current_image = self.images[self.current_image_index]

            with ZipStore(file_path, mode="w") as store:
                zarr.save(store, current_image.data)  # type: ignore
            logger.info(f"Saved image to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save image as zarr: {e}")
            QErrorMessage(self).showMessage(f"Failed to save image: {e}")

    @Slot()
    def save_as_png(self):
        if len(self.images) == 0:
            QErrorMessage(self).showMessage("No images to save.")
            return

        file_path = QFileDialog.getSaveFileName(
            self, "Save Image as PNG", "", "PNG Files (*.png)"
        )[0]

        if not file_path:
            return

        try:
            current_image = self.images[self.current_image_index]
            pil_image = PILImage.fromarray(current_image.data)

            pil_image.save(file_path)
            logger.info(f"Saved image to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save image as PNG: {e}")
            QErrorMessage(self).showMessage(f"Failed to save image: {e}")

    @Slot()
    def delete_current_image(self):
        """Delete the current image."""
        if len(self.images) == 0:
            return

        self.images.pop(self.current_image_index)

        # Adjust current index if needed
        if len(self.images) > 0:
            self.current_image_index = min(
                self.current_image_index, len(self.images) - 1
            )
            self.update_display()
        else:
            # No images left, close window
            self.close()

    def closeEvent(self, event):
        """Handle window close event."""
        # Clear all images
        self.images.clear()
        event.accept()
