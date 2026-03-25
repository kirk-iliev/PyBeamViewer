# PyBeamViewer

A PyQt GUI application for real-time beam visualization and analysis using EPICS PV (Process Variable) data.

## Features

- Real-time beam image display and analysis
- Integration with EPICS control systems
- Interactive data visualization with pyqtgraph
- Configurable PV (Process Variable) settings
- MVC architecture for clean code organization

## Requirements

- Python 3.8+
- PyQt6
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

## Configuration

Edit `config.json` to configure PV names and other settings. The application supports multiple PV prefixes via the `active_prefix` field.

## Project Structure

- `main.py` — Application entry point
- `gui.py` — PyQt6 GUI components
- `state.py` — Application state management
- `controller.py` — MVC controller
- `analysis.py` — Data analysis functions
- `analysis_worker.py` — Background worker for analysis
- `epics_layer.py` — EPICS integration
- `config.py` — Configuration management
- `config.json` — Configuration file
