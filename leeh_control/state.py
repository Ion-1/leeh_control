from pathlib import Path
from dataclasses import dataclass, field

from rust_enum import enum, Case
from tomlkit import TOMLDocument

from .controller import ANC300


@enum
class ControllerState:
    Disconnected = Case()
    Connected = Case(inner=ANC300)


@dataclass(slots=True, frozen=False, eq=False, repr=True, order=False)
class AppState:
    controller: ControllerState = field(default_factory=ControllerState.Disconnected)
    config_file: Path | None = field(default=None)
    config: TOMLDocument = field(default_factory=TOMLDocument)
