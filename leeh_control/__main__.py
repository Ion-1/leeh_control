import sys
import logging
import argparse

from leeh_control.app import App


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-backend", action="store_true")
    namespace = parser.parse_args(sys.argv[1:])

    logging.captureWarnings(True)
    logging.basicConfig(level=logging.DEBUG)

    App(show_fake=namespace.fake_backend).exec()
