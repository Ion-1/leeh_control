from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pylablib.core.devio.comm_backend import IDeviceCommBackend
from pylablib.core.utils import py3


FAKE_ANC300_PORT = "FAKE_ANC300"


@dataclass(slots=True)
class _AxisState:
    serial: str
    mode: str = "gnd"
    voltage_v: float = 30.0
    offset_v: float = 0.0
    frequency_hz: float = 1000.0
    capacitance_nf: float = 60.0
    acin: bool = False
    dcin: bool = False
    output_v: float = 0.0
    filter: str = "off"


class FakeANC300Backend(IDeviceCommBackend):
    """Small ANC300 emulator implementing the pylablib backend contract."""

    _backend = "fake-anc300"

    def __init__(
        self,
        conn,
        timeout: float = 3.0,
        term_write: str | bytes | None = "\r\n",
        term_read: str | bytes | None = "\n",
        datatype: str = "auto",
        reraise_error=None,
        axes: Iterable[int] = (1, 2, 3),
    ):
        super().__init__(
            conn=conn,
            timeout=timeout,
            term_write=term_write,
            term_read=term_read,
            datatype=datatype,
            reraise_error=reraise_error,
        )
        self._timeout = timeout
        self._opened = True
        self._rx_buffer = b""
        self._controller_serial = "FAKE-ANC300-0001"
        self._version = "ANC300 v0.0-sim"
        self._axes = {axis: _AxisState(serial=f"ANM300-{axis:03d}") for axis in axes}

    def open(self):
        self._opened = True

    def close(self):
        self._opened = False

    def is_opened(self):
        return self._opened

    def set_timeout(self, timeout):
        self._timeout = timeout

    def get_timeout(self):
        return self._timeout

    def flush_read(self):
        length = len(self._rx_buffer)
        self._rx_buffer = b""
        return length

    def read(self, size=None):
        if size is None:
            data = self._rx_buffer
            self._rx_buffer = b""
            return self._to_datatype(data)
        data = self._rx_buffer[:size]
        self._rx_buffer = self._rx_buffer[size:]
        return self._to_datatype(data)

    def readline(self, remove_term=True, timeout=None, skip_empty=True):  # pylint: disable=unused-argument
        data = py3.as_builtin_bytes(self.read())
        if remove_term and self.term_read:
            term = py3.as_builtin_bytes(self.term_read)
            if data.endswith(term):
                data = data[: -len(term)]
        return self._to_datatype(data)

    def read_multichar_term(self, term, remove_term=True, timeout=None, error_on_timeout=True):  # pylint: disable=unused-argument
        data = py3.as_builtin_bytes(self.read())
        if isinstance(term, py3.anystring):
            term = [term]
        terms = [py3.as_builtin_bytes(t) for t in (term or [])]
        if remove_term:
            for t in sorted(terms, key=len, reverse=True):
                if t and data.endswith(t):
                    data = data[: -len(t)]
                    break
        return self._to_datatype(data)

    def write(self, data, flush=True, read_echo=False, read_echo_delay=0, read_echo_lines=1):  # pylint: disable=unused-argument
        if isinstance(data, bytes):
            cmd = py3.as_str(data)
        else:
            cmd = str(data)

        if self.term_write:
            term = py3.as_str(self.term_write)
            if cmd.endswith(term):
                cmd = cmd[: -len(term)]

        msg, ok = self._handle_command(cmd.strip())
        suffix = "OK" if ok else "ERROR"
        payload = f"{msg} {suffix}" if msg else suffix
        self._rx_buffer += payload.encode("ascii")

    def _axis_numbers(self, token: str):
        if token.lower() == "all":
            return list(self._axes)
        axis = int(token)
        if axis not in self._axes:
            raise ValueError(f"axis {axis} is not available")
        return [axis]

    def _one_axis(self, token: str):
        axes = self._axis_numbers(token)
        if len(axes) != 1:
            raise ValueError("expected a single axis")
        return axes[0]

    def _onoff(self, token: str):
        value = token.lower()
        if value not in {"on", "off"}:
            raise ValueError(f"expected on/off, got {token}")
        return value == "on"

    def _handle_command(self, cmd: str):
        try:
            parts = cmd.split()
            if not parts:
                return "empty command", False

            op = parts[0].lower()

            if op == "echo" and len(parts) == 2:
                return "", True
            if op == "getcser":
                return self._controller_serial, True
            if op == "ver":
                return self._version, True

            if op == "getser" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return self._axes[axis].serial, True

            if op == "getm" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return f"mode = {self._axes[axis].mode}", True
            if op == "setm" and len(parts) == 3:
                for axis in self._axis_numbers(parts[1]):
                    self._axes[axis].mode = parts[2].lower()
                return "", True

            if op == "getfil" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return f"filter = {self._axes[axis].filter}", True
            if op == "setfil" and len(parts) == 3:
                for axis in self._axis_numbers(parts[1]):
                    self._axes[axis].filter = parts[2].lower()
                return "", True

            if op == "getv" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return f"voltage = {self._axes[axis].voltage_v:.3f} V", True
            if op == "setv" and len(parts) == 3:
                value = float(parts[2])
                for axis in self._axis_numbers(parts[1]):
                    self._axes[axis].voltage_v = value
                return "", True

            if op == "geta" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return f"voltage = {self._axes[axis].offset_v:.3f} V", True
            if op == "seta" and len(parts) == 3:
                value = float(parts[2])
                for axis in self._axis_numbers(parts[1]):
                    self._axes[axis].offset_v = value
                return "", True

            if op == "getf" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return f"frequency = {self._axes[axis].frequency_hz:.3f} Hz", True
            if op == "setf" and len(parts) == 3:
                value = float(parts[2])
                for axis in self._axis_numbers(parts[1]):
                    self._axes[axis].frequency_hz = value
                return "", True

            if op == "getc" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return f"capacitance = {self._axes[axis].capacitance_nf:.3f} nF", True
            if op == "capw" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                self._axes[axis].mode = "gnd"
                return "", True

            if op == "getaci" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return f"acin = {'on' if self._axes[axis].acin else 'off'}", True
            if op == "setaci" and len(parts) == 3:
                value = self._onoff(parts[2])
                for axis in self._axis_numbers(parts[1]):
                    self._axes[axis].acin = value
                return "", True

            if op == "getdci" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return f"dcin = {'on' if self._axes[axis].dcin else 'off'}", True
            if op == "setdci" and len(parts) == 3:
                value = self._onoff(parts[2])
                for axis in self._axis_numbers(parts[1]):
                    self._axes[axis].dcin = value
                return "", True

            if op == "geto" and len(parts) == 2:
                axis = self._one_axis(parts[1])
                return f"voltage = {self._axes[axis].output_v:.3f} V", True

            if op in {"stepu", "stepd"} and len(parts) == 3:
                for axis in self._axis_numbers(parts[1]):
                    steps = parts[2].lower()
                    self._axes[axis].output_v = 1.0 if steps == "c" else 0.0
                return "", True

            if op == "stepw" and len(parts) == 2:
                self._one_axis(parts[1])
                return "", True

            if op == "stop" and len(parts) == 2:
                for axis in self._axis_numbers(parts[1]):
                    self._axes[axis].output_v = 0.0
                return "", True

            return f"unknown command: {cmd}", False
        except Exception as exc:
            return str(exc), False

