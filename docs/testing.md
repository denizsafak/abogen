# Testing Guide

This document describes the testing strategy for Abogen's Plugin Architecture.

## Test Categories

### 1. Contract Tests (`tests/contracts/`)

**Purpose**: Verify that every plugin satisfies the architectural contract. These tests ensure the Plugin Architecture's invariants are maintained.

**What They Guarantee**:
- Every plugin exports `PLUGIN_MANIFEST`, `MODEL_REQUIREMENTS`, `create_engine`
- `create_engine` is atomic (succeeds fully or raises and cleans up)
- `Engine.createSession()` returns valid `EngineSession`, transfers ownership
- `Engine.dispose()` is idempotent, never raises
- After `dispose()`, all methods raise `EngineError`
- `EngineSession.synthesize()` returns `SynthesizedAudio` or raises `EngineError` (session remains usable)
- `EngineSession.dispose()` is idempotent, never raises
- Capability interfaces (`VoiceLister`, `PreviewGenerator`, etc.) are correctly implemented
- Plugin Loader discovers, validates, and loads plugins correctly
- Plugin Manager creates, caches, and disposes engines correctly
- Value objects are immutable and have correct equality semantics
- Error hierarchy is preserved (`EngineError` base with subtypes)

**Why They Exist**:
- Provide **compile-time-like guarantees** for a dynamic plugin system
- Enable **safe plugin ecosystem** — host can trust any loaded plugin
- Catch **architectural violations** early (missing dispose, wrong return types, etc.)
- Document the **contract** in executable form

**What Every New Plugin Must Pass**:
```bash
pytest tests/contracts/ -v
# All tests must pass
```

**Running Contract Tests**:
```bash
# All contract tests
pytest tests/contracts/

# Specific contract
pytest tests/contracts/test_engine_contract.py

# With coverage
pytest tests/contracts/ --cov=abogen.tts_plugin
```

---

### 2. Behavioral Tests (`tests/test_behavioral_regression.py`)

**Purpose**: Verify external user-facing behavior using only public API. These tests are **not coupled to internal implementation**.

**What They Test**:
- Synthesis with various inputs (short, long, empty, unicode, mixed scripts)
- Voice selection and listing
- Parameter handling (speed, etc.)
- Error scenarios (unknown plugin, disposal, etc.)
- Resource cleanup (dispose idempotency, no leaks)
- Pipeline utility (`create_pipeline`)

**Why They Test Public Behavior Only**:
- **Refactoring safety**: Internal changes don't break tests
- **Real-world usage**: Tests match how consumers actually use the API
- **Plugin agnostic**: Parametrized across Kokoro, SuperTonic, and mock plugins
- **Regression detection**: Catch behavioral regressions regardless of implementation

**What They Don't Test**:
- Internal class structure
- Private methods
- Implementation details (how audio is generated, model loading internals)

**Running Behavioral Tests**:
```bash
# All behavioral tests
pytest tests/test_behavioral_regression.py -v

# With specific plugin (if installed)
pytest tests/test_behavioral_regression.py -v -k "kokoro"
```

---

### 3. Unit Tests (`tests/`)

**Purpose**: Test individual modules in isolation.

**Examples**:
- `test_book_parser.py` — EPUB/PDF/text parsing
- `test_text_normalization.py` — Text preprocessing
- `test_chunk_helpers.py` — Text chunking logic
- `test_voice_cache.py` — Voice caching

---

### 4. Integration Tests

**Purpose**: Test cross-component interactions.

**Examples**:
- `test_kokoro_plugin.py` — Full Kokoro plugin integration
- `test_supertonic_plugin.py` — Full SuperTonic plugin integration
- `test_conversion_series.py` — End-to-end conversion pipeline

---

## Test Architecture

```
tests/
├── contracts/           # Contract tests (architectural compliance)
│   ├── conftest.py      # Shared fixtures (FakeEngine, FakeSession)
│   ├── test_manifest_contract.py
│   ├── test_plugin_contract.py
│   ├── test_engine_contract.py
│   ├── test_session_contract.py
│   ├── test_capabilities_contract.py
│   ├── test_loader_contract.py
│   ├── test_plugin_manager_contract.py
│   ├── test_types_contract.py
│   ├── test_errors_contract.py
│   ├── test_host_context_contract.py
│   └── test_integration.py
├── test_behavioral_regression.py  # Behavioral tests (public API)
├── test_kokoro_plugin.py          # Kokoro integration
├── test_supertonic_plugin.py      # SuperTonic integration
└── ...                            # Other unit/integration tests
```

---

## Adding Tests for a New Plugin

### Contract Tests (Required)

Create `tests/contracts/test_your_plugin.py`:

```python
"""Contract tests for YourPlugin — verifies architectural compliance."""

from pathlib import Path
from abogen.tts_plugin.loader import load_plugin_from_dir
from abogen.tts_plugin.manifest import PluginManifest
from abogen.tts_plugin.engine import Engine

def test_your_plugin_loads():
    result = load_plugin_from_dir(Path("plugins/your_tts"))
    assert result.success
    assert isinstance(result.manifest, PluginManifest)
    assert result.manifest.id == "your_tts"
    assert callable(result.create_engine)

def test_your_plugin_creates_engine():
    result = load_plugin_from_dir(Path("plugins/your_tts"))
    # ... create HostContext, EngineConfig
    engine = result.create_engine(ctx, None, EngineConfig(device="cpu"))
    assert isinstance(engine, Engine)
    engine.dispose()

def test_your_plugin_capabilities():
    """If plugin declares capabilities, verify they're implemented."""
    result = load_plugin_from_dir(Path("plugins/your_tts"))
    # Check VoiceLister, PreviewGenerator, etc.
    ...
```

### Behavioral Tests (Recommended)

Add parametrized tests to `tests/test_behavioral_regression.py`:

```python
# In _plugin_ids list, add your plugin
_plugin_ids = ["kokoro", "supertonic", "your_tts"]
_plugin_engines["your_tts"] = _YourMockEngine
_plugin_default_voices["your_tts"] = "voice1"
_plugin_all_voices["your_tts"] = ["voice1", "voice2"]
```

All existing behavioral tests will automatically run against your plugin.

---

## Continuous Integration

```yaml
# .github/workflows/test.yml
- name: Contract Tests
  run: pytest tests/contracts/ -v

- name: Behavioral Tests
  run: pytest tests/test_behavioral_regression.py -v

- name: Unit & Integration Tests
  run: pytest tests/ -v --ignore=tests/test_behavioral_regression.py
```

---

## Test Design Principles

### Contract Tests
- **No mocks** for the system under test (test real plugin loading)
- **Strict assertions** on types and behavior
- **Document architecture** in test names and docstrings
- **Fail fast** on architectural violations

### Behavioral Tests
- **Only public API** (`create_pipeline`, `Engine`, `EngineSession`, `PluginManager`)
- **Parametrized** across plugins
- **Realistic scenarios** (long text, unicode, mixed scripts)
- **No implementation coupling** (test behavior, not internals)

### General
- **Fast**: Unit tests < 1s, Contract tests < 5s, Behavioral < 30s
- **Isolated**: No shared state between tests
- **Deterministic**: Same input → same output
- **Descriptive names**: `test_<component>_<scenario>_<expected>`