from pathlib import Path
import sys
import logging
import argparse

from leeh_control.app import App


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity")
    parser.add_argument(
        "-c", "--config", type=str, default=None, help="Path to the config file (default: config.toml)"
    )
    parser.add_argument("--fake-backend", action="store_true", help="Use fake backend")
    namespace = parser.parse_args(sys.argv[1:])

    logging.captureWarnings(True)
    logging.basicConfig(level=logging.DEBUG)

    if namespace.config is not None:
        try:
            config_path = Path(namespace.config).resolve()
        except OSError as e:
            parser.error(f"Invalid config path: {e}")
    else:
        config_path = None

    App(show_fake=namespace.fake_backend, config_path=config_path).exec()
