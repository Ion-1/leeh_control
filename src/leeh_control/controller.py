import functools
import logging

import serial.tools.list_ports as lpo

from typing import Self, Annotated, Literal, Optional, Callable

from rust_enum import Result, enum, Case
from pylablib.devices.Attocube.anc300 import ANC300 as PLL_ANC300, AttocubeError
from pylablib.core.devio.comm_backend import (
    new_backend,
    IDeviceCommBackend,
    DeviceBackendError,
    DeviceSerialError,
)
from dataclasses import dataclass, asdict
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


def list_ports() -> list[ListPortInfo]:
    ports: list[ListPortInfo] = lpo.comports()
    if __debug__:
        fake_port = ListPortInfo(FAKE_ANC300_PORT)
        fake_port.description = "Simulated ANC300 controller"
        ports.append(fake_port)
    logger.info(f"Listing available serial ports: {ports}")
    return ports


def log_errors[T, **P](func: Callable[P, T]) -> Callable[P, T]:
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return func(*args, **kwargs)
        except DeviceSerialError as e:
            logger.error(f"Serial error while querying: {e}")
            raise
        except AttocubeError as e:
            logger.error(f"Controller responded with ERROR to query: {e}")
            raise
        except DeviceBackendError as e:
            if "timeout" in str(e).lower():
                logger.error(f"Timeout during ANC300 query: {e}")
                raise
            logger.error(f"Backend error during ANC300 query: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during ANC300 query: {e}")
            raise
    return wrapper


@dataclass(slots=True)
class ANC300:
    inner: PLL_ANC300

    @classmethod
    def list_ports(cls) -> list[ListPortInfo]:
        return list_ports()

    @classmethod
    def connect_COM(
        cls,
        options: COMConnectionOptions,
        *,
        timeout: float = 10.0,
        open_retry_times: int = 3,
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
            instance = cls(inner=PLL_ANC300(connection))
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

    @property
    def axes(self) -> list[int]:
        return self.inner.get_all_axes()

    @log_errors
    def query_controller(self, query: str) -> str:
        logger.info(f"Querying ANC300 controller: {query}")
        return self.inner.query(query)

    @log_errors
    def get_device_info(self) -> tuple[str, str]:
        logger.info("Getting ANC300 device info")
        return self.inner.get_device_info()

    @log_errors
    def get_serial(self, axis: int) -> str:
        logger.info(f"Getting ANC300 axis {axis} serial number")
        return self.inner.get_axis_serial(axis=axis)

    @log_errors
    def get_mode(self, axis: int) -> str:
        logger.info(f"Getting ANC300 axis {axis} mode")
        return self.inner.get_mode(axis=axis)

    @log_errors
    def set_mode(self, axis: int, mode: str):
        logger.info(f"Setting ANC300 axis {axis} mode to {mode}")
        return self.inner.set_mode(axis=axis, mode=mode)

    @log_errors
    def get_voltage(self, axis: int) -> float:
        logger.info(f"Getting ANC300 axis {axis} voltage")
        return self.inner.get_voltage(axis=axis)

    @log_errors
    def set_voltage(self, axis: int, voltage: float):
        logger.info(f"Setting ANC300 axis {axis} voltage to {voltage}")
        return self.inner.set_voltage(axis=axis, voltage=voltage)

    @log_errors
    def get_offset(self, axis: int) -> float:
        logger.info(f"Getting ANC300 axis {axis} offset voltage")
        return self.inner.get_offset(axis=axis)

    @log_errors
    def set_offset(self, axis: int, voltage: float):
        logger.info(f"Setting ANC300 axis {axis} offset voltage to {voltage}")
        return self.inner.set_offset(axis=axis, voltage=voltage)

    @log_errors
    def get_frequency(self, axis: int) -> float:
        logger.info(f"Getting ANC300 axis {axis} frequency")
        return self.inner.get_frequency(axis=axis)

    @log_errors
    def set_frequency(self, axis: int, freq: float):
        logger.info(f"Setting ANC300 axis {axis} frequency to {freq}")
        return self.inner.set_frequency(axis=axis, freq=freq)

    @log_errors
    def get_capacitance(self, axis: int, measure: bool = False) -> float:
        logger.info(f"Getting ANC300 axis {axis} capacitance with measure={measure}")
        return self.inner.get_capacitance(axis=axis, measure=measure)

    @log_errors
    def get_filter(self, axis: int) -> str:
        logger.info(f"Getting ANC300 axis {axis} filter setting")
        return self._get_filter(axis=axis)

    def _get_filter(self, axis: int) -> str:
        reply = self.inner.query(f"getfil {axis}")
        return self.inner._parse_string_reply(reply, "filter")

    @log_errors
    def set_filter(self, axis: int, filter_: str) -> str:
        logger.info(f"Setting ANC300 axis {axis} filter to {filter}")
        return self._set_filter(axis=axis, filter_=filter_)

    def _set_filter(self, axis: int, filter_: str) -> str:
        self.inner.query(f"setfil {axis} {filter_}")
        return self._get_filter(axis=axis)

    @log_errors
    def step(self, axis: int, steps: int | Literal["c+", "c-"]):
        if steps == "c+":
            logger.info(f"Starting continuous stepping upwards on ANC300 axis {axis}")
            self.inner.jog(axis=axis, direction="+")
        elif steps == "c-":
            logger.info(f"Starting continuous stepping downwards on ANC300 axis {axis}")
            self.inner.jog(axis=axis, direction="-")
        else:
            logger.info(
                f"Stepping ANC300 axis {axis} {abs(steps)} steps {'upwards' if steps > 0 else 'downwards'}"
            )
            self.inner.move_by(axis=axis, steps=steps)

    @log_errors
    def stop(self, axis: int):
        logger.info(f"Stopping motion on ANC300 axis {axis}")
        self.inner.stop(axis=axis)

    @log_errors
    def get_external_input_modes(
        self, axis: int
    ) -> tuple[Annotated[bool, "AC-In"], Annotated[bool, "DC-In"]]:
        logger.info(f"Getting external input modes on ANC300 axis {axis}")
        return self.inner.get_external_input_modes(axis=axis)

    @log_errors
    def set_external_input_modes(
        self, axis: int, acin: Optional[bool], dcin: Optional[bool]
    ):
        logger.info(
            f"Setting external input modes on ANC300 axis {axis} to "
            f"{f'AC-IN={acin}' if acin is not None else ''}"
            f"{', ' if acin is not None and dcin is not None else ''}"
            f"{f'DC-IN={dcin}' if dcin is not None else ''}"
        )
        return self.inner.set_external_input_modes(axis=axis, acin=acin, dcin=dcin)
