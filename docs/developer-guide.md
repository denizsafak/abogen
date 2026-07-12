# TTS Plugin Architecture — Architectural Reference

This document describes the **stable architectural contracts** of the TTS Plugin Architecture. It documents invariants that only change when the architecture itself changes.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Application                         │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ Plugin      │  │ HostContext  │  │ Plugin Discovery       │  │
│  │ Manager     │──│ (config_dir, │  │ (plugin directories)   │  │
│  │             │  │  logger,     │  │                        │  │
│  │ - discover  │  │  http_client)│  └────────────────────────┘  │
│  │ - validate  │  └──────────────┘            │                 │
│  │ - activate  │                              ▼                 │
│  │ - dispose   │  ┌─────────────────────────────────────────┐   │
│  └──────┬──────┘  │              Plugin Package             │   │
│         │         │  ┌──────────────┐ ┌─────────────────┐   │   │
│         ▼         │  │ PLUGIN_      │ │ MODEL_          │   │   │
│  ┌────────────┐   │  │ MANIFEST     │ │ REQUIREMENTS    │   │   │
│  │   Engine   │◄──┤  │ create_engine│ │                 │   │   │
│  └──────┬─────┘   │  └──────────────┘ └─────────────────┘   │   │
│         │         └─────────────────────────────────────────┘   │
│         │ createSession()                                       │
│         ▼                                                       │
│  ┌─────────────┐                                                │
│  │EngineSession│                                                │
│  └──────┬──────┘                                                │
│         │ synthesize()                                          │
│         ▼                                                       │
│  ┌────────────────┐                                             │
│  │SynthesizedAudio│                                             │
│  └────────────────┘                                             │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | Responsibility |
|-----------|----------------|
| **PluginManifest** | Static metadata: id, name, version, api_version, capabilities, engine manifest |
| **EngineManifest** | Voice sources, parameters, audio formats |
| **HostContext** | Minimal host services: config_dir, logger, http_client |
| **Engine** | Stateless factory for sessions; thread-safe `createSession()` |
| **EngineSession** | Owns mutable execution state; not thread-safe |
| **PluginManager** | Discovers, validates, and manages plugin lifecycle |
| **Capabilities** | Optional interfaces: VoiceLister, PreviewGenerator, StreamingSynthesizer, CancelableSession |

---

## 2. Ownership Model

### Engine Ownership
```
PluginManager.create_engine() → Engine
```
- **PluginManager** creates and caches engines
- **Caller** receives `Engine` instance
- **Caller** must dispose all sessions **before** disposing engine
- **Engine.dispose()** releases engine resources
- After `Engine.dispose()`: all methods except `dispose()` raise `EngineError`

### Session Ownership
```
Engine.createSession() → EngineSession
```
- **Engine** creates session
- **Ownership transfers to caller** immediately
- **Caller** is responsible for `session.dispose()`
- **Engine does NOT track sessions** — no registry, no callbacks
- After `session.dispose()`: all methods except `dispose()` raise `EngineError`

### Disposal Order (Invariant)
```python
# Correct
engine = manager.create_engine("id")
session = engine.createSession()
try:
    audio = session.synthesize(request)
finally:
    session.dispose()      # 1. Sessions FIRST
engine.dispose()           # 2. Then engine

# INCORRECT — violates contract (undefined behavior)
engine.dispose()
session.synthesize(request)  # EngineError
```

---

## 3. Lifecycle State Machine

```
DISCOVERY
  PluginManager.discover(plugin_dirs)
  → Loads PLUGIN_MANIFEST, MODEL_REQUIREMENTS
  → Validates api_version (major must match)
  → Validates declared capabilities are implemented

MODEL_DOWNLOAD (if MODEL_REQUIREMENTS non-empty)
  Host reads MODEL_REQUIREMENTS
  Downloads/caches models
  Resolves model_path

ACTIVATION
  create_engine(context, model_path, config)
  → Atomic: succeeds fully or raises EngineError
  → Returns Engine

SESSION_CREATION
  engine.createSession() → EngineSession
  → Ownership transfers to caller
  → Raises EngineError on failure
  → Never returns partial session

SYNTHESIS
  session.synthesize(request)
  → Returns SynthesizedAudio
  → Raises EngineError on failure
  → Session remains usable after error

SESSION_DISPOSAL
  session.dispose()
  → Idempotent, never raises
  → After: all methods raise EngineError

DEACTIVATION
  engine.dispose()
  → Caller MUST dispose all sessions first
  → Idempotent, never raises
  → After: all methods raise EngineError
```

---

## 4. Protocol Contracts

### Engine (Protocol)
```python
@runtime_checkable
class Engine(Protocol):
    def createSession(self) -> EngineSession:
        """Create a new session. Thread-safe. Transfers ownership."""
        ...

    def dispose(self) -> None:
        """Release engine resources.
        Caller must dispose all sessions first.
        Idempotent, never raises.
        After: all methods except dispose() raise EngineError."""
        ...
```

### EngineSession (Protocol)
```python
@runtime_checkable
class EngineSession(Protocol):
    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        """Synthesize audio.
        Returns SynthesizedAudio or raises EngineError.
        Session remains usable after error."""
        ...

    def dispose(self) -> None:
        """Release session resources.
        Idempotent, never raises.
        After: all methods except dispose() raise EngineError."""
        ...
```

### Capability Protocols (Optional)
- **VoiceLister**: `listVoices(source_id: str) -> list[VoiceManifest]`
- **PreviewGenerator**: `generatePreview(voice: VoiceSelection, text: str) -> SynthesizedAudio`
- **StreamingSynthesizer**: `synthesizeStream(request: SynthesisRequest) -> Iterator[bytes]`
- **CancelableSession**: `cancel() -> None` (causes in-flight synthesize to raise `CancelledError`)

---

## 5. Error Semantics

```
EngineError (base)
├── ModelNotFoundError      # Required model not found
├── ModelLoadError          # Model failed to load
├── NetworkError            # Network operation failed
├── InvalidInputError       # Request validation failed
├── ConfigurationError      # Invalid configuration
├── CancelledError          # Operation cancelled via CancelableSession
└── InternalError           # Unexpected internal failure
```

### When Each Is Raised
| Error | Raised By | Conditions |
|-------|-----------|------------|
| `ModelNotFoundError` | `create_engine()` | Required model not found at `model_path` |
| `ModelLoadError` | `create_engine()` | Model exists but fails to load |
| `NetworkError` | `synthesize()`, `create_engine()` | Network call fails (cloud engines) |
| `InvalidInputError` | `synthesize()` | Request validation fails (empty text, invalid voice, etc.) |
| `ConfigurationError` | `create_engine()` | Config values invalid for this engine |
| `CancelledError` | `synthesize()`, `synthesizeStream()` | `CancelableSession.cancel()` called |
| `InternalError` | Any | Unexpected internal failure (bug) |

### Dispose Contract
- `dispose()` is **idempotent** and **never raises**
- After `dispose()`: all methods except `dispose()` raise `EngineError`
- Engine: caller must dispose all sessions first; violating this is undefined behavior

---

## 6. Capabilities

| Capability | Interface | Enables |
|------------|-----------|---------|
| `voice_list` | `VoiceLister` | `listVoices(source_id)` — enumerate available voices |
| `preview` | `PreviewGenerator` | `generatePreview(voice, text)` — preview without session |
| `streaming` | `StreamingSynthesizer` | `synthesizeStream(request)` — chunked audio output |
| `cancel` | `CancelableSession` | `cancel()` — interrupt in-flight synthesis |

Plugins declare capabilities in `PluginManifest.capabilities`. Host validates at load time.

---

## 7. Contract Tests

**Location**: `tests/contracts/`

**Purpose**: Verify every plugin satisfies the architectural contracts.

**Guarantees**:
- Required exports exist (`PLUGIN_MANIFEST`, `MODEL_REQUIREMENTS`, `create_engine`)
- `create_engine` is atomic
- `Engine.createSession()` transfers ownership, never returns partial
- `dispose()` is idempotent on Engine and EngineSession
- After `dispose()`, methods raise `EngineError`
- `synthesize()` raises typed `EngineError` subtypes, session remains usable
- Declared capabilities are actually implemented
- Plugin loader validates manifest, api_version, capabilities

**Run**: `pytest tests/contracts/ -v`

---

## 8. Behavioral Tests

**Location**: `tests/test_behavioral_regression.py`

**Purpose**: Verify user-facing behavior via public API only (`create_pipeline`, `Engine`, `EngineSession`, `PluginManager`).

**Scope**:
- Synthesis with various inputs (short, long, empty, unicode, mixed scripts)
- Voice selection and listing
- Parameter handling (speed, etc.)
- Error scenarios (unknown plugin, disposal, etc.)
- Resource cleanup (dispose idempotency, no leaks)
- Pipeline utility (`create_pipeline`)

**Run**: `pytest tests/test_behavioral_regression.py -v`

---

## 9. Reference

- **Architecture Spec**: `docs/architecture-final-v2.md`
- **Amendment (lang_code)**: `docs/architecture-amendment-001.md`
- **Migration Roadmap**: `docs/migration-roadmap.md`
- **Plugin Examples**: `plugins/kokoro/`, `plugins/supertonic/`
- **Protocol Definitions**: `abogen/tts_plugin/engine.py`, `abogen/tts_plugin/capabilities.py`
