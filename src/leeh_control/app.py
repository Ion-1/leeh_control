import logging

from functools import cache
from itertools import zip_longest
from typing import Optional

from PySide6.QtCore import QFileSystemWatcher, Slot
from PySide6.QtWidgets import QApplication
from tomlkit import dumps

from .config import parse_config, AxisConfig, difference
from .state import AppState
from .ui.main_window import MainWindow

logger = logging.getLogger(__name__)


class App(QApplication):
    def __init__(self, config_path: Optional[str] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        config_file, config = parse_config(config_path)
        self.state = AppState(config_file=config_file, config=config)

        self.config_watcher = QFileSystemWatcher(self)
        if config_file is not None:
            self.config_watcher.addPath(str(config_file.absolute()))
        self.config_watcher.fileChanged.connect(self.on_config_changed)

        self.main_window = MainWindow(self.state)
        self.main_window.show()

        self.exec()

    @Slot(str)
    def on_config_changed(self, _path: str):
        logger.info("Config file changed, reloading...")

        old_config = self.state.config
        new_config = parse_config(self.state.config_file)[1]
        logger.debug(f"{old_config=} {new_config=}")

        diff = difference(old_config.unwrap(), new_config.unwrap())
        logger.info(f"Config diff: {diff}")

        if not any(diff):
            return

        self.state.config.clear()
        self.state.config.update(new_config)

        emitted = set()
        for first, *rest in diff:
            if not first == "axes":
                continue

            if len(rest) < 2:
                continue

            serial, key, *_ = rest
            signal = getattr(self.axis_config(serial).signals, key, None)
            logger.info(f"Emitting signal {key} for {serial}")
            if signal is not None and key not in emitted:
                signal.emit()
                emitted.add(key)

    @cache
    def axis_config(self, serial: str) -> AxisConfig:
        return AxisConfig(self.state.config, serial, self._persist_config)

    def _persist_config(self):
        if self.state.config_file is None:
            return
        try:
            self.state.config_file.write_text(
                dumps(self.state.config.unwrap()), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Error while writing config file: {e}")
