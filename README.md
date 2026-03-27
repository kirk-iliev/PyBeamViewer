# PyBeamViewer

A PyQt5 GUI application for real-time beam profile visualization and Gaussian analysis using EPICS (Experimental Physics and Industrial Control System) camera data. The application uses an MVC architecture with multi-threaded workers to keep the GUI responsive during data acquisition and image processing.

## Features

- Real-time beam profile image display with interactive ROI (region of interest) selection
- Automatic Gaussian fitting with pixel and calibrated µm measurements
- Full and ROI (cropped) projections with fit overlays
- Integration with EPICS control systems via caproto
- Interactive data visualization with pyqtgraph (dark/light themes)
- Configurable PV (Process Variable) settings and multiple prefix support
- Clean MVC architecture with thread-safe state management
- Comprehensive test suite (pytest with coverage reporting)

## Requirements

- Python 3.11+
- PyQt5
- pyqtgraph
- numpy
- scipy
- caproto

## Installation

1. Clone the repository:
```bash
git clone https://github.com/kirk-iliev/PyBeamViewer.git
cd PyBeamViewer
```

2. Create a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Run the application:
```bash
python main.py
```

Alternatively, if installed as a package:
```bash
pybeamviewer
```

## Configuration

Edit `config/config.json` to configure EPICS connection settings, PV names, and display preferences. The application supports multiple PV prefixes via the `active_prefix` field and allows runtime prefix switching through the GUI.

## Project Structure

```
PyBeamViewer/
├── main.py                 — Application entry point
├── pyproject.toml          — Project metadata and dependencies
├── requirements.txt        — Runtime and dev dependencies
├── config.json             — Configuration file
│
├── core/                   — Core application logic
│   ├── state.py           — Thread-safe application state (Model)
│   ├── controller.py       — MVC controller orchestrating data pipeline
│   ├── epics_layer.py      — EPICS connection and PV subscription
│   └── *_worker.py         — Background threads for EPICS I/O and analysis
│
├── gui/                    — Qt GUI components (View)
│   ├── window.py           — Main application window
│   ├── control_panel.py    — Settings and controls UI
│   ├── image_pane.py       — Image display widgets
│   ├── projection_plot.py   — Projection graph widgets
│   ├── overlay_state.py    — ROI overlay state management
│   ├── dialogs.py          — Dialog windows
│   └── theme.py            — Dark/light theme configuration
│
├── analysis/               — Data analysis functions
│   ├── analysis.py         — Gaussian fitting and projections
│   ├── calibration.py      — Pixel-to-physical unit calibration
│   ├── analysis_worker.py  — Background analysis processing
│   └── __init__.py
│
├── config/                 — Configuration management
│   ├── config.py           — Config loading and parsing
│   ├── config.json         — Default configuration
│   └── __init__.py
│
└── tests/                  — Test suite (pytest)
    ├── test_*.py           — Unit and integration tests
    └── conftest.py         — Pytest fixtures and configuration
```

## Development

### Running Tests

```bash
pytest                    # Run all tests with coverage
pytest tests/test_gui_smoke.py  # Run specific test file
pytest -v                # Verbose output
```

### Development Dependencies

Install development dependencies for testing, type checking, and linting:
```bash
pip install -e ".[dev]"
```

### Code Quality Tools

- **Type checking:** `mypy`
- **Linting & formatting:** `ruff`
- **Testing:** `pytest` with `pytest-qt` for GUI testing
