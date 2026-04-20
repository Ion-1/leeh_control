import sys
import logging

from leeh_control.app import App


if __name__ == "__main__":
    logging.captureWarnings(True)
    logging.basicConfig(level=logging.DEBUG)
    App()
