# Getting Started

Quickstart for developers working on Abogen.

## Prerequisites

- Python 3.10+
- Node.js 20+
- npm 10+
- Git
- Docker (optional)

## Installation

```bash
# Development install with all extras
pip install -e .[dev]

# Or with uv
uv pip install -e .[dev]
```

## Running the Application

```bash
# Desktop GUI
abogen

# Web UI
abogen-web

# CLI
abogen-cli
```

## Project Structure

```
abogen/
├── pyqt/         - PyQt6 desktop GUI
├── webui/        - Flask web UI
├── tts_plugin/   - Plugin Architecture (Engine, EngineSession, Manifest)
└── plugins/      - Built-in plugins (kokoro, supertonic)
tests/
├── contracts/    - Contract compliance tests
└── ...
```

## Testing

```bash
# All tests
pytest

# Contract tests (architectural compliance)
pytest tests/contracts/

# Behavioral regression tests
pytest tests/test_behavioral_regression.py
```

## Architecture

See [Developer Guide](developer-guide.md) for Plugin Architecture details:
- Engine / EngineSession lifecycle
- Plugin contract (PLUGIN_MANIFEST, create_engine)
- Adding new plugins
- Capability interfaces
