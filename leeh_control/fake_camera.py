from dataclasses import dataclass

import numpy as np

from pylablib.devices.DCAM.dcamprop_defs import DCAMPROPUNIT


FAKE_CAMERA_NAME = "FAKE_DCAM"


@dataclass(slots=True)
class _FakeAttribute:
    name: str
    kind: str
    unit: int
    min: float
    max: float
    step: float
    _value: float
    labels: dict[str, int] | None = None

    def get_value(self):
        return self._value

    def set_value(self, value):
        value = float(value) if self.kind == "float" else int(value)
        if value < self.min or value > self.max:
            raise ValueError(f"{self.name} must be between {self.min} and {self.max}")
        self._value = value


class FakeDCAMCamera:
    """Small DCAM-like camera emulator for the UI fake mode."""

    def __init__(self, camera_index: int | None = None, width: int = 2304, height: int = 2304):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self._opened = True
        self._frame_index = 0
        self._attributes = {
            "EXPOSURE TIME": _FakeAttribute(
                name="EXPOSURE TIME",
                kind="float",
                unit=DCAMPROPUNIT.DCAMPROP_UNIT_SECOND,
                min=0.001,
                max=1.0,
                step=0.001,
                _value=0.05,
            )
        }

    def close(self):
        self._opened = False

    def is_opened(self):
        return self._opened

    def get_all_attributes(self):
        return list(self._attributes)

    def get_attribute(self, name: str):
        return self._attributes[name]

    def snap(self):
        if not self._opened:
            raise RuntimeError("camera is closed")

        exposure = float(self._attributes["EXPOSURE TIME"].get_value())

        max_exposure = float(self._attributes["EXPOSURE TIME"].max)
        brightness = int(round(255 * exposure / max_exposure))
        brightness = max(0, min(255, brightness))
        return np.full((self.height, self.width), brightness, dtype=np.uint16)
