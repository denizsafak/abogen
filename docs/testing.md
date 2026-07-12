# Testing Guide

This document describes the testing strategy for Abogen's Plugin Architecture.

## Test Categories

### 0. Auto-Discovery Plugin Tests (`tests/plugins/`)

**Purpose**: Automatically test every plugin in `plugins/` directory without manual test creation. These tests use discovery to find all plugins and run generic tests against each one.

**What They Test**:
- **Manifest structure**: Required fields, API version format, voices field
- **Engine lifecycle**: `create_engine`, `dispose` idempotency, post-dispose behavior
- **Capability implementation**: Declared capabilities are implemented (e.g., `voice_list` → `VoiceLister`)

**How Auto-Discovery Works**:
```python
# tests/plugins/conftest.py
@pytest.fixture(scope="module")
def plugin_ids(plugins_dir: Path) -> list[str]:
    """Discovers all plugin directories with __init__.py"""
    return [item.name for item in plugins_dir.iterdir() 
            if item.is_dir() and (item / "__init__.py").exists()]
```

**Test Structure**:
```
tests/plugins/
├── conftest.py              # Fixtures: plugin_ids, loaded_plugin, host_context
└── test_all_plugins.py      # Generic tests for every plugin
    ├── TestAllPluginsManifest
    ├── TestAllPluginsEngine
    └── TestAllPluginsCapabilities
```

**Running Auto-Discovery Tests**:
```bash
# Test all plugins automatically
pytest tests/plugins/ -v

# Test specific plugin
pytest tests/plugins/ -v -k "kokoro"

# See which plugins were discovered
pytest tests/plugins/ --collect-only
```

**Adding a New Plugin**:
1. Create plugin directory: `plugins/my_plugin/`
2. Add `__init__.py` with `PLUGIN_MANIFEST`, `MODEL_REQUIREMENTS`, `create_engine`
3. Run `pytest tests/plugins/` — tests automatically discover and test your plugin!

**When to Add Plugin-Specific Tests**:
Auto-discovery tests cover generic contract validation. Create plugin-specific tests in `tests/test_<plugin>_plugin.py` for:
- Integration with real dependencies (e.g., KPipeline for Kokoro)
- Specific voice IDs and behavior
- Plugin-specific parameters and features

---

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

### 4. Unit Tests (`tests/`)

**Purpose**: Test individual modules in isolation.

**Examples**:
- `test_book_parser.py` — EPUB/PDF/text parsing
- `test_text_normalization.py` — Text preprocessing
- `test_chunk_helpers.py` — Text chunking logic
- `test_voice_cache.py` — Voice caching

---

### 5. Integration Tests

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

### Auto-Discovery Tests (Automatic!)

**No manual test creation required!** When you add a new plugin to `plugins/`:

1. Create plugin directory: `plugins/my_plugin/`
2. Add `__init__.py` with required exports:
   ```python
   PLUGIN_MANIFEST = PluginManifest(...)
   MODEL_REQUIREMENTS = [...]
   def create_engine(...): ...
   ```
3. Run `pytest tests/plugins/` — auto-discovery tests automatically find and test your plugin!

**What's Tested Automatically**:
- Manifest structure and required fields
- API version compatibility
- Engine creation and dispose contract
- Capability implementation (if declared)

### Plugin-Specific Tests (Optional)

Create `tests/test_my_plugin_plugin.py` for:
- Integration with real backend (e.g., KPipeline for Kokoro)
- Specific voice IDs and behavior
- Plugin-specific parameters and features

### Contract Tests (Deprecated for New Plugins)

**Note**: Auto-discovery tests (`tests/plugins/`) now cover contract validation for all plugins. Manual contract tests in `tests/contracts/` are only needed for testing internal architecture components.

### Behavioral Tests (Recommended)

Add parametrized tests to `tests/test_behavioral_regression.py`:

```python
# In _plugin_ids list, add your plugin
_plugin_ids = ["kokoro", "supertonic", "my_plugin"]
_plugin_engines["my_plugin"] = _YourMockEngine
_plugin_default_voices["my_plugin"] = "voice1"
_plugin_all_voices["my_plugin"] = ["voice1", "voice2"]
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