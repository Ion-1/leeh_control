from collections import namedtuple
from collections.abc import Mapping
import os
import sys
import inspect
import logging

from enum import Enum
from pathlib import Path
from typing import Optional, TypedDict, MutableMapping, Callable, Any

from PySide6.QtCore import Signal, QObject
from rust_enum import Result
from tomlkit import TOMLDocument, parse, dumps


logger = logging.getLogger(__name__)


if getattr(sys, "frozen", False):
    logger.info("Running in a PyInstaller bundle")
    app_path = Path(sys.executable).parent
else:
    logger.info("Running in a source tree; using cwd for fallback")
    app_path = Path(os.getcwd())


class ConfigParseError(Enum):
    ExistenceException = "Config file does not exist"
    PermissionException = "Permission error while reading config file"
    OSError = "OS error while reading config file"
    ParsingError = "Error while parsing config file"


def _parse_config(config_file: Path) -> Result[TOMLDocument, ConfigParseError]:
    if not config_file.is_file():
        logger.error("Config file does not exist / is not a file")
        return Result.Err(ConfigParseError.ExistenceException)
    try:
        config_bytes = config_file.read_bytes()
    except PermissionError as e:
        logger.error(f"Permission error while reading config file: {e}")
        return Result.Err(ConfigParseError.PermissionException)
    except OSError as e:
        logger.error(f"OS error while reading config file: {e}")
        return Result.Err(ConfigParseError.OSError)
    try:
        return Result.Ok(parse(config_bytes))
    except Exception as e:
        logger.error(f"Error while parsing config file: {e}")
    return Result.Err(ConfigParseError.ParsingError)


default_config = TOMLDocument()


def parse_config(config_path: Optional[str] | Path) -> tuple[Path | None, TOMLDocument]:
    """
    Try to get a config from config_path.
    If no config_path is specified / trying to get the config fails, fallback to the default config.
    If there is nothing at the fallback, we use the default config and try to write it to the fallback.
    If parsing the fallback fails, we return None for the path with the default config.
    It is up to the application to notify the user that any configuration will be lost.
    """
    default_path = app_path / "config.toml"

    if config_path is not None:
        config_file = Path(config_path)
        logger.info(f"Trying to get config from {config_file}")
        config = _parse_config(config_file).map(lambda c: (config_file, c))
        if config.is_ok():
            return config.unwrap()
    else:
        logger.info("No config path specified, falling back to default config")

    logger.warning(f"Falling back to default config at {default_path}")

    config = _parse_config(default_path).map(lambda c: (default_path, c))
    if config.is_ok():
        return config.unwrap()

    error = config.unwrap_err()
    logger.error("Error while getting config from fallback")

    if error == ConfigParseError.ExistenceException:
        logger.warning(
            "Attempting to write default config to fallback\nNOTE: If this is your first time running the app, this may be expected behavior"
        )
        try:
            default_path.write_text(dumps(default_config))
            return default_path, default_config
        except Exception as e:
            logger.error(f"Error while writing default config to fallback: {e}")

    logger.warning(
        "Running with volatile config, please check your config file and ensure it is readable and parsable"
    )
    return None, default_config


class Limits[T](TypedDict):
    bottom: T
    top: T


class WaitOnWrite[T, K, V](MutableMapping[K, V]):
    """Act like an empty dict if the parent dict is not yet populated with the key."""

    _parent: MutableMapping[T, MutableMapping[K, V]]
    _key: T

    @property
    def _pdict(self):
        return self._parent.get(self._key, {})

    def __init__(self, parent: MutableMapping[T, MutableMapping[K, V]], key: T):
        self._parent = parent
        self._key = key

    def __getitem__(self, key):
        return self._pdict[key]

    def __setitem__(self, key, value):
        if self._key not in self._parent:
            self._parent[self._key] = {}
        self._parent[self._key][key] = value

    def __delitem__(self, key, /):
        self._pdict.pop(key)

    def __iter__(self):
        return iter(self._pdict)

    def __len__(self):
        return len(self._pdict)


def attrib_signals(cls: type) -> type:
    """Create a signal for each non-private static attribute of the class."""
    attribs = []
    for attr in inspect.getmembers_static(cls, lambda a: not inspect.isroutine(a)):
        if attr[0].startswith("_"):
            continue
        attribs.append(attr[0])
    type.__setattr__(
        cls,
        "_signal_type",
        type(cls.__name__ + "Signals", (QObject,), {k: Signal() for k in attribs}),
    )
    return cls


@attrib_signals
class AxisConfig:
    """
    Proxy-object holding the configuration options for an axis.
    Stands between UI and TOMLDocument.
    Emits a signal when an option is changed through the proxy.
    Any change is immediately persisted to the config file.
    Setting a value to None removes the key from the config file.
    """

    _signals: QObject
    _signal_type: type[QObject]
    name: str | None = None
    offset_lim: Limits[float] = Limits(bottom=0, top=100)
    freq_lim: Limits[int] = Limits(bottom=0, top=1000)
    step_V_lim: Limits[float] = Limits(bottom=0, top=60)
    up: str | None = None
    down: str | None = None

    def __init__(
        self, app_config: TOMLDocument, serial: str, persist: Callable[[], Any]
    ):
        super().__init__()

        object.__setattr__(self, "_signals", type(self)._signal_type())

        axes = WaitOnWrite(app_config, "axes")
        self._config = WaitOnWrite(axes, serial)
        self._persist = persist

    def __getattribute__(self, item):
        config = object.__getattribute__(self, "_config")
        if (val := config.get(item)) is None:
            return object.__getattribute__(self, item)
        return val

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return

        config = object.__getattribute__(self, "_config")
        persist = object.__getattribute__(self, "_persist")

        if value is None:
            config.pop(name, None)
        else:
            config[name] = value
        persist()
        signal = getattr(self._signals, name, None)
        if signal is not None:
            signal.emit()

    @property
    def signals(self) -> QObject:
        return self._signals

_MISSING = object()

class Diff(namedtuple("Diff", ["added", "modified", "removed"])):
    def __iter__(self):
        yield from self.added + self.modified + self.removed
    def prepend(self, prefix: str):
        return Diff(
            added=[(prefix, *item) for item in self.added],
            modified=[(prefix, *item) for item in self.modified],
            removed=[(prefix, *item) for item in self.removed],
        )
    def extend(self, other: Diff):
        return Diff(
            added=self.added + other.added,
            modified=self.modified + other.modified,
            removed=self.removed + other.removed,
        )

def difference(old: Mapping, new: Mapping) -> Diff:
    diffs = Diff(added=[], modified=[], removed=[])
    for key in set(old.keys()) | set(new.keys()):
        if (av := old.get(key, _MISSING)) is _MISSING:
            diffs.added.append((key,))
        elif (bv := new.get(key, _MISSING)) is _MISSING:
            diffs.removed.append((key,))
        elif isinstance(av, Mapping) and isinstance(bv, Mapping):
            sub_diffs = difference(av, bv)
            diffs = diffs.extend(sub_diffs.prepend(key))
        elif av != bv:
            diffs.modified.append((key,))
    return diffs
