import logging
import functools

import serial.tools.list_ports as lpo

from dataclasses import dataclass, asdict
from typing import Self, Annotated, Literal, Optional, Callable, Any, Concatenate

from pylablib.core.utils import py3
from rust_enum import Result, enum, Case
from pylablib.devices.Attocube.anc300 import ANC300 as PLL_ANC300, AttocubeError
from pylablib.core.devio.comm_backend import (
    new_backend,
    IDeviceCommBackend,
    DeviceBackendError,
    DeviceSerialError,
)
from serial.tools.list_ports_common import ListPortInfo

from .fake_backend import FakeANC300Backend, FAKE_ANC300_PORT


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True, eq=True, repr=True, order=False)
class COMConnectionOptions:
    port: str = "COM1"
    baudrate: int = 38400
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    xonxoff: int = 0
    rtscts: int = 0
    dsrdtr: int = 0


@enum
class COMConnectionError:
    TimedOut = Case()
    SerialError = Case(inner=DeviceSerialError)
    DeviceError = Case(inner=AttocubeError)
    Unknown = Case(inner=Exception)


@enum
class QueryError:
    Unknown = Case()
    TimedOut = Case()
    DeviceError = Case(inner=AttocubeError)
    SerialError = Case(inner=DeviceSerialError)


def list_ports(show_fake: bool = False) -> list[ListPortInfo]:
    ports: list[ListPortInfo] = lpo.comports()
    if show_fake or __debug__:
        fake_port = ListPortInfo(FAKE_ANC300_PORT)
        fake_port.description = "Simulated ANC300 controller"
        ports.append(fake_port)
    logger.info(f"Listing available serial ports: {ports}")
    return ports


def handle_errors[T, **P](func: Callable[Concatenate[object, P], T]) -> Callable[Concatenate[object, P], T]:
    @functools.wraps(func)
    def wrapper(self, *args: P.args, **kwargs: P.kwargs) -> T:
        if (eback := getattr(self, "error_callback", None)) is not None:
            def callback(e):
                logger.error(e)
                eback(e)
        else:
            callback = logger.error
        try:
            return func(self, *args, **kwargs)
        except DeviceSerialError as e:
            callback(f"Serial error while querying: {e}")
            raise
        except AttocubeError as e:
            callback(f"Controller responded with ERROR to query: {e}")
            raise
        except DeviceBackendError as e:
            if "timeout" in str(e).lower():
                callback(f"Timeout during ANC300 query: {e}")
                raise
            callback(f"Backend error during ANC300 query: {e}")
            raise
        except Exception as e:
            callback(f"Unexpected error during ANC300 query: {e}")
            raise

    return wrapper


def render_command(msg, is_command) -> str:
    prefix = ">>> " if is_command else "<<< "
    cont_prefix = "... "

    lines = msg.splitlines() or [""]
    rendered = [f"{prefix}{lines[0]}"]
    rendered.extend(f"{cont_prefix}{line}" for line in lines[1:])
    return "\n".join(rendered)


class ANC300(PLL_ANC300):
    def __init__(
        self,
        *args,
        query_callback: Callable[[str], Any] | None = None,
        reply_callback: Callable[[str], Any] | None = None,
        error_callback: Callable[[str], Any] | None = None,
        **kwargs,
    ):
        self._query_callback = [query_callback] if query_callback is not None else []
        self._reply_callback = [reply_callback] if reply_callback is not None else []
        self._error_callback = [error_callback] if error_callback is not None else []
        super().__init__(*args, **kwargs)

    def query_callback(self, msg: str):
        for callback in self._query_callback:
            callback(msg)

    def reply_callback(self, msg: str):
        for callback in self._reply_callback:
            callback(msg)

    def error_callback(self, msg: str):
        for callback in self._error_callback:
            callback(msg)

    def add_query_callback(self, callback: Callable[[str], Any]):
        self._query_callback.append(callback)

    def add_reply_callback(self, callback: Callable[[str], Any]):
        self._reply_callback.append(callback)

    def add_error_callback(self, callback: Callable[[str], Any]):
        self._error_callback.append(callback)

    def remove_query_callback(self, callback: Callable[[str], Any]):
        self._query_callback.remove(callback)

    def remove_reply_callback(self, callback: Callable[[str], Any]):
        self._reply_callback.remove(callback)

    def remove_error_callback(self, callback: Callable[[str], Any]):
        self._error_callback.remove(callback)

    @classmethod
    def list_ports(cls, show_fake: bool = False) -> list[ListPortInfo]:
        return list_ports(show_fake=show_fake)

    @classmethod
    def connect_COM(
        cls,
        options: COMConnectionOptions,
        *,
        timeout: float = 10.0,
        open_retry_times: int = 3,
        **kwargs,
    ) -> Result[Self, COMConnectionError]:
        logger.info(
            f"Connecting to ANC300 via serial at {options.port} with {timeout}s timeout and {open_retry_times} retries"
        )
        logger.debug(f"Connection options: {options}")

        try:
            if options.port == FAKE_ANC300_PORT:
                connection: IDeviceCommBackend = FakeANC300Backend(
                    conn=options.port,
                    timeout=timeout,
                    term_write="\r\n",
                )
            else:
                connection = new_backend(
                    asdict(options),
                    backend="serial",
                    timeout=timeout,
                    open_retry_times=open_retry_times,
                )
        except DeviceSerialError as e:
            logger.error(f"Serial error while opening backend: {e}")
            return Result.Err(COMConnectionError.SerialError(inner=e))
        except DeviceBackendError as e:
            if "timeout" in str(e).lower():
                logger.error(f"Timeout while opening backend: {e}")
                return Result.Err(COMConnectionError.TimedOut())
            logger.error(f"Backend error while opening backend: {e}")
            return Result.Err(COMConnectionError.Unknown(inner=e))
        except Exception as e:
            logger.error(f"Unexpected error while opening backend: {e}")
            return Result.Err(COMConnectionError.Unknown(inner=e))

        try:
            instance = cls(conn=connection, **kwargs)
        except AttocubeError as e:
            logger.error(f"ANC300 device error during init: {e}")
            return Result.Err(COMConnectionError.DeviceError(inner=e))
        except DeviceBackendError as e:
            if "timeout" in str(e).lower():
                logger.error(f"Timeout during ANC300 init: {e}")
                return Result.Err(COMConnectionError.TimedOut())
            logger.error(f"Backend error during ANC300 init: {e}")
            return Result.Err(COMConnectionError.Unknown(inner=e))
        except Exception as e:
            logger.error(f"Unexpected error during ANC300 init: {e}")
            return Result.Err(COMConnectionError.Unknown(inner=e))

        return Result.Ok(instance)

    @handle_errors
    def query(self, msg: str) -> str:
        self.instr.flush_read()
        self.query_callback(py3.as_str(msg))
        logger.info(render_command(msg, is_command=True))
        self.instr.write(msg)
        reply = self.instr.read_multichar_term(["ERROR", "OK"], remove_term=False)
        reply_text = py3.as_str(reply)
        self.reply_callback(reply_text)
        logger.info(render_command(reply_text, is_command=False))
        # self.instr.flush_read()
        if reply_text.upper().endswith("ERROR"):
            err = py3.as_str(reply_text)[:-5].strip()
            raise AttocubeError(err)
        return reply_text[:-2].strip()

    @handle_errors
    def get_device_info(self) -> tuple[str, str]:
        return super().get_device_info()

    @handle_errors
    def get_serial(self, axis: int) -> str:
        return super().get_axis_serial(axis=axis)

    @handle_errors
    def get_mode(self, axis: int) -> str:
        return super().get_mode(axis=axis)

    @handle_errors
    def set_mode(self, axis: int, mode: str):
        return super().set_mode(axis=axis, mode=mode)

    @handle_errors
    def get_voltage(self, axis: int) -> float:
        return super().get_voltage(axis=axis)

    @handle_errors
    def set_voltage(self, axis: int, voltage: float):
        return super().set_voltage(axis=axis, voltage=voltage)

    @handle_errors
    def get_offset(self, axis: int) -> float:
        return super().get_offset(axis=axis)

    @handle_errors
    def set_offset(self, axis: int, voltage: float):
        return super().set_offset(axis=axis, voltage=voltage)

    @handle_errors
    def get_frequency(self, axis: int) -> float:
        return super().get_frequency(axis=axis)

    @handle_errors
    def set_frequency(self, axis: int, freq: float):
        return super().set_frequency(axis=axis, freq=freq)

    @handle_errors
    def get_capacitance(self, axis: int, measure: bool = False) -> float | Literal["?"]:
        if measure:
            self._wip.measure_capacitance(axis,wait=True)
        reply=self.query("getc {}".format(axis))
        if "= ?" in reply:
            return "?"
        return self._parse_float_reply(reply,"capacitance","nF")

    @handle_errors
    def get_filter(self, axis: int) -> str:
        return self._get_filter(axis=axis)

    def _get_filter(self, axis: int) -> str:
        reply = self.query(f"getfil {axis}")
        return self._parse_string_reply(reply, "filter")

    @handle_errors
    def set_filter(self, axis: int, filter_: str) -> str:
        return self._set_filter(axis=axis, filter_=filter_)

    def _set_filter(self, axis: int, filter_: str) -> str:
        self.query(f"setfil {axis} {filter_}")
        return self._get_filter(axis=axis)

    @handle_errors
    def step(self, axis: int, steps: int | Literal["c+", "c-"]):
        if steps == "c+":
            logger.info(f"Starting continuous stepping upwards on ANC300 axis {axis}")
            self.jog(axis=axis, direction="+")
        elif steps == "c-":
            logger.info(f"Starting continuous stepping downwards on ANC300 axis {axis}")
            self.jog(axis=axis, direction="-")
        else:
            logger.info(
                f"Stepping ANC300 axis {axis} {abs(steps)} steps {'upwards' if steps > 0 else 'downwards'}"
            )
            self.move_by(axis=axis, steps=steps)

    @handle_errors
    def stop(self, axis: int):
        super().stop(axis=axis)

    @handle_errors
    def get_external_input_modes(
        self, axis: int
    ) -> tuple[Annotated[bool, "AC-In"], Annotated[bool, "DC-In"]]:
        return super().get_external_input_modes(axis=axis)

    @handle_errors
    def set_external_input_modes(
        self, axis: int, acin: Optional[bool], dcin: Optional[bool]
    ):
        return super().set_external_input_modes(axis=axis, acin=acin, dcin=dcin)
