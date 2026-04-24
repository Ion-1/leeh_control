# ANC300 dashboard
This project is a dashboard for easier interfacing with the ANC300, using PySide6 and pylablib.

## Usage

### Run from source
Install [uv](https://github.com/astral-sh/uv).

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
