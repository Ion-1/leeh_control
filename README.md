# ANC300 dashboard
This project is a dashboard for easier interfacing with the ANC300 over a USB connection.


## Usage

### Run from source
Install [uv](https://github.com/astral-sh/uv).

Ensure you have the ANC300 USB driver installed.

> [!IMPORTANT]
> Until pylablib-lightweight updates to 1.4.4, the program will crash if it can not find `ftd2xx.dll`.
> Within your virtual environment (`.venv` in project root), in `Lib\site-packages\pylablib\core\devio\comm_backend.py` on line 994 add `AttributeError` to the `except` block.

In the project root, run:
```bash
uv run python -m leeh_control
```

Optionally, add a path for the configuration file (default is `./config.toml`):
```bash
uv run python -m leeh_control -c /path/to/config.toml
```

#### Creating an executable
```bash
uv run pyinstaller leeh_control_interface.spec
```
