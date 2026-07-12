# TTS Plugin Architecture — Final Specification

## 1. Core Domain

Zero dependencies. Pure business logic.

### 1.1 Engine

Factory for sessions. Stateless. Thread-safe for createSession().

```
interface Engine:
  createSession() -> EngineSession
  dispose() -> void
```

**createSession() contract**:
- Returns: EngineSession
- Raises: EngineError on failure
- Ownership: Transfers to caller
- Thread-safe: Yes

**dispose() contract**:
- Releases engine resources
- Caller must ensure all sessions created by this engine are disposed before calling dispose()
- Disposing an engine while any session is still alive violates the API contract; behavior is undefined
- Idempotent: Safe to call multiple times
- Never raises: Catches and logs internally
- After dispose(): All methods except dispose() raise EngineError

### 1.2 EngineSession

Owns mutable execution state isolated from other concurrent work. NOT thread-safe.

```
interface EngineSession:
  synthesize(request: SynthesisRequest) -> SynthesizedAudio
  dispose() -> void
```

**synthesize() contract**:
- Returns: SynthesizedAudio
- Raises: EngineError on failure (session remains usable)
- Thread-safe: No

**dispose() contract**:
- Releases session resources
- Idempotent: Safe to call multiple times
- Never raises: Catches and logs internally
- After dispose(): All methods except dispose() raise EngineError

### 1.3 SynthesisRequest

Immutable value object.

```
SynthesisRequest:
  text: string
  voice: VoiceSelection
  parameters: ParameterValues
  format: AudioFormat
```

### 1.4 SynthesizedAudio

Immutable value object.

```
SynthesizedAudio:
  data: bytes
  format: AudioFormat
  duration: Duration
```

### 1.5 VoiceSelection

Immutable value object. Opaque to engine.

```
VoiceSelection:
  source: string
  key: string
  payload: any = None  # Optional; required for clone/blend sources
```

### 1.6 ParameterValues

Immutable value object. Behaves like Mapping[str, Any].

```
ParameterValues:
  values: Mapping[str, Any]
```

### 1.7 AudioFormat

Immutable value object.

```
AudioFormat:
  mime: string
  extension: string
```

### 1.8 Duration

Immutable value object.

```
Duration:
  seconds: number
```

### 1.9 EngineConfig

Engine initialization settings only. No resource references.

```
EngineConfig:
  device: string    # "cpu", "cuda:0", etc.
  # Engine-specific settings (if any)
  # Unknown keys are ignored (no error)
```

---

## 2. Error Hierarchy

Typed exceptions. Engines raise EngineError or subtypes. Never raw exceptions.

```
EngineError (base)
├── ModelNotFoundError
├── ModelLoadError
├── NetworkError
├── InvalidInputError
├── ConfigurationError
├── CancelledError
└── InternalError
```

**Contract**:
- synthesize() raises EngineError on failure, session remains usable
- dispose() never raises (catches and logs internally)
- create_engine() raises EngineError on failure, cleans up partially created resources
- createSession() raises EngineError on failure, no partially initialized session returned
- cancel() causes synthesize() to raise CancelledError

---

## 3. Capability Interfaces (Optional)

Engines implement only what they support. Capabilities are additive.

### 3.1 VoiceLister

```
interface VoiceLister:
  listVoices(sourceId: string) -> list[VoiceManifest]
```

### 3.2 PreviewGenerator

```
interface PreviewGenerator:
  generatePreview(voice: VoiceSelection, text: string) -> SynthesizedAudio
```

### 3.3 ModelRequirements

Static at plugin level, not engine level. Host reads before creating engine.

```
MODEL_REQUIREMENTS = list[ModelManifest]
```

### 3.4 StreamingSynthesizer

Optional capability of EngineSession, not Engine.

```
interface StreamingSynthesizer:
  synthesizeStream(request: SynthesisRequest) -> Iterator[bytes]
```

**Iterator contract**:
- Yields audio chunks as they become available
- Raises CancelledError if cancel() is called during iteration
- Raises EngineError on synthesis failure
- Iterator exhaustion = synthesis complete
- Session remains usable after iterator completes

### 3.5 CancelableSession

Optional capability for engines that support cancellation.

```
interface CancelableSession:
  cancel() -> void
```

**cancel() contract**:
- Cancels in-progress synthesize()
- synthesize() raises CancelledError (subtype of EngineError)
- EngineSession remains usable after cancellation (unless implementation documents otherwise)

---

## 4. Plugin Manifest

Static metadata. Immutable. No dependencies.

### 4.1 PluginManifest

```
PluginManifest:
  id: string
  name: string
  version: string
  api_version: string  # semver format: MAJOR.MINOR
  description: string
  author: string
  capabilities: list[string]
  requires: RequirementManifest
  engine: EngineManifest
```

**api_version contract**:
- Format: semver (MAJOR.MINOR)
- Compatibility: Host rejects plugin if major version differs
- Minor version: backward compatible, Host accepts higher minor

### 4.2 EngineManifest

```
EngineManifest:
  voiceSources: list[VoiceSourceManifest]
  parameters: list[ParameterManifest]
  audioFormats: list[AudioFormatManifest]
```

### 4.3 VoiceSourceManifest

```
VoiceSourceManifest:
  id: string
  name: string
  type: string    # "list", "speaker_id", "clone", "blend", "generate", "none"
  config: any
```

### 4.4 VoiceManifest

```
VoiceManifest:
  id: string
  name: string
  tags: list[string]
```

### 4.5 ParameterManifest

```
ParameterManifest:
  id: string
  name: string
  description: string
  type: string    # "float", "int", "string", "boolean", "enum"
  default: any
  min: number (optional)
  max: number (optional)
  step: number (optional)
  options: list[EnumOption] (optional)
  unit: string (optional)
  group: string (optional)
```

### 4.6 AudioFormatManifest

```
AudioFormatManifest:
  mime: string
  extension: string
```

### 4.7 EnumOption

```
EnumOption:
  value: string
  label: string
```

### 4.8 RequirementManifest

```
RequirementManifest:
  gpu: GpuRequirement (optional)
  memory: number (optional)
  internet: boolean (optional)
```

### 4.9 GpuRequirement

```
GpuRequirement:
  required: boolean
  type: string (optional)
  memory: number (optional)
```

### 4.10 ModelManifest

```
ModelManifest:
  id: string
  name: string
  size: string
```

---

## 5. Host Services

### 5.1 HostContext

Minimal. 3 fields maximum. No business logic.

```
HostContext:
  config_dir: Path      # For API keys, preferences
  logger: Logger        # For logging
  http_client: HttpClient  # For network requests
```

---

## 6. Plugin Contract

### 6.1 Plugin Exports

```python
# plugins/kokoro/__init__.py

PLUGIN_MANIFEST = PluginManifest(...)
MODEL_REQUIREMENTS = [...]  # Static at plugin level

def create_engine(
  context: HostContext,
  model_path: Path | None,
  config: EngineConfig
) -> Engine:
  """Create engine. Atomic: succeeds fully or raises and cleans up."""
  ...
```

### 6.2 create_engine() Contract

- Parameters:
  - context: HostContext (host services)
  - model_path: Path | None (resolved model path, or None for cloud/no-model engines)
  - config: EngineConfig (engine initialization settings)
- Returns: Engine
- Raises: EngineError on failure
- Atomic: Succeeds fully or cleans up and raises
- Thread-safe: Can be called from any thread

---

## 7. Object Lifecycle

### 7.1 Engine Lifecycle

```
1. DISCOVERY
   Host scans plugin directories
   Loads PLUGIN_MANIFEST and MODEL_REQUIREMENTS

2. MODEL DOWNLOAD (if MODEL_REQUIREMENTS non-empty)
   Host reads MODEL_REQUIREMENTS
   Downloads/caches required models
   Resolves model_path for create_engine()

3. ACTIVATION
   Host calls create_engine(context, model_path, config)
   Engine created, ready to use
   Raises EngineError on failure

4. SESSION CREATION
   Client calls engine.createSession()
   Returns EngineSession
   Ownership transfers to caller
   Raises EngineError on failure
   No partially initialized session returned

5. SYNTHESIS
   Client calls session.synthesize(request)
   Returns SynthesizedAudio
   Raises EngineError on failure (session remains usable)

6. SESSION DISPOSAL
   Client calls session.dispose()
   Releases session resources

7. DEACTIVATION
   Client calls engine.dispose()
   Caller must ensure all sessions are disposed first
   Disposing engine while sessions are alive is undefined behavior
   Releases engine resources
```

### 7.2 EngineSession Lifecycle

```
1. CREATION
   Created by Engine.createSession()
   Ownership transfers to caller
   Raises EngineError on failure

2. USAGE
   Client calls synthesize() one or more times
   Each call returns SynthesizedAudio or raises EngineError
   Session remains usable after synthesize() failure
   If CancelableSession: cancel() causes synthesize() to raise CancelledError
   If StreamingSynthesizer: iterator raises CancelledError on cancel(), EngineError on failure

3. DISPOSAL
   Client calls dispose()
   Releases session resources
   After dispose(), all methods except dispose() raise EngineError
```

### 7.3 Ownership Rules

- Engine.createSession() transfers ownership of the returned session to the caller
- Caller is responsible for disposing all sessions before disposing the engine
- Engine does not track sessions; it has no lifecycle registry
- Disposing an engine while any session is still alive violates the API contract; behavior is undefined
- This design avoids coupling, synchronization overhead, and lifecycle registry complexity

### 7.4 Concurrent Operations

**Engine.dispose() concurrent with Engine.createSession()**:
- createSession() must either succeed with fully initialized EngineSession or raise EngineError
- Partially initialized EngineSession must never be returned
- After dispose() completes, subsequent createSession() calls must raise EngineError

**EngineSession.dispose() concurrent with EngineSession.synthesize()**:
- Not thread-safe. Caller must ensure synthesize() completes before dispose().

**EngineSession.dispose() concurrent with StreamingSynthesizer.synthesizeStream()**:
- Not thread-safe. Caller must ensure stream iteration completes before dispose().

---

## 8. Thread Safety Contract

| Component | Thread-safe | Notes |
|-----------|-------------|-------|
| Engine | Yes | createSession() can be called from any thread |
| EngineSession | No | synthesize() must be called from one thread at a time |
| HostContext | Yes | Provides shared services |
| VoiceSelection | Yes | Immutable value object |
| ParameterValues | Yes | Immutable value object |
| AudioFormat | Yes | Immutable value object |
| EngineConfig | Yes | Immutable value object |

---

## 9. dispose() Contract

**General rules**:
- Calling dispose() multiple times is safe (no-op on second call)
- dispose() never raises exceptions (catches and logs internally)
- After dispose(), all methods except dispose() raise EngineError

**Engine.dispose()**:
- Caller must ensure all sessions are disposed first
- Disposing engine while sessions are alive violates API contract; behavior is undefined
- Releases engine resources

**EngineSession.dispose()**:
- Releases session resources

---

## 10. Dependency Rules

```
Core Domain (Engine, EngineSession, Value Objects)
  -> No dependencies

Plugin Manifest (PluginManifest, ModelManifest, etc.)
  -> No dependencies

Host Context (HostContext)
  -> Depends on: Core Domain (for types)

Plugin Implementation
  -> Depends on: Core Domain, Host Context

Host
  -> Depends on: Core Domain, Plugin Manifest
```

**Forbidden**:
- Core Domain -> anything else
- Plugin Manifest -> anything else
- Plugin Implementation -> Host (only receives HostContext)
- Host -> Plugin Implementation (only via create_engine function)

---

## 11. Architectural Invariants

1. Core Domain has zero dependencies
2. Plugins receive HostContext at creation, not via global state
3. Model requirements are static (plugin level), not dynamic (engine level)
4. Host validates capability implementation at load time: each capability declared in PluginManifest.capabilities must be implemented by the exported object via the corresponding interface
5. synthesize() raises typed exceptions, not returns Result
6. dispose() is idempotent and never raises
7. No global state, no service locator
8. VoiceSelection and ParameterValues are opaque to engine
9. Display information comes from VoiceManifest
10. HostContext is minimal (3 fields max)
11. EngineConfig contains only engine settings, not resource references
12. EngineSession owns mutable execution state isolated from other concurrent work
13. Engine.createSession() transfers ownership to caller
14. Caller must dispose all sessions before disposing engine
15. After dispose(), all methods except dispose() raise EngineError
16. create_engine() is atomic (all-or-nothing)
17. Garbage collection without dispose() may leak (documented)
18. Capabilities are additive (new capabilities don't break old plugins)
19. api_version enables compatibility checking
20. createSession() returns fully initialized session or raises, never partial
21. cancel() causes synthesize() to raise CancelledError
22. EngineSession remains usable after cancellation
23. Engine does not track sessions; no lifecycle registry

---

## 12. Validation Examples

### 12.1 Kokoro

```python
PLUGIN_MANIFEST = PluginManifest(
  id="kokoro",
  api_version="1.0",
  capabilities=["voice_list", "preview", "voice_blend"],
  engine=EngineManifest(
    voiceSources=[
      VoiceSourceManifest(id="builtin", type="list", config={"voices": [...]}),
      VoiceSourceManifest(id="formula", type="blend", config={"syntax": "{a}*0.5+{b}*0.5"}),
    ],
    parameters=[ParameterManifest(id="speed", type="float", default=1.0, min=0.5, max=2.0)],
    audioFormats=[AudioFormatManifest(mime="audio/wav", extension="wav")],
  ),
)

MODEL_REQUIREMENTS = []

def create_engine(context: HostContext, model_path: Path | None, config: EngineConfig) -> Engine:
  model = load_kokoro(model_path)
  return KokoroEngine(model, config.device)
```

### 12.2 SuperTonic

```python
PLUGIN_MANIFEST = PluginManifest(
  id="supertonic",
  api_version="1.0",
  capabilities=["voice_list", "preview"],
  engine=EngineManifest(
    voiceSources=[VoiceSourceManifest(id="builtin", type="list", config={"voices": [...]})],
    parameters=[
      ParameterManifest(id="speed", type="float", default=1.0, min=0.5, max=2.0),
      ParameterManifest(id="steps", type="int", default=20, min=5, max=50),
    ],
    audioFormats=[AudioFormatManifest(mime="audio/wav", extension="wav")],
  ),
)

MODEL_REQUIREMENTS = []

def create_engine(context: HostContext, model_path: Path | None, config: EngineConfig) -> Engine:
  model = load_supertonic(model_path)
  return SuperTonicEngine(model, config.device)
```

### 12.3 ElevenLabs

```python
PLUGIN_MANIFEST = PluginManifest(
  id="elevenlabs",
  api_version="1.0",
  capabilities=["voice_list"],
  requires=RequirementManifest(internet=True),
  engine=EngineManifest(
    voiceSources=[VoiceSourceManifest(id="cloud", type="list", config={"speakers": [...]})],
    parameters=[ParameterManifest(id="stability", type="float", default=0.5, min=0.0, max=1.0)],
    audioFormats=[AudioFormatManifest(mime="audio/mpeg", extension="mp3")],
  ),
)

MODEL_REQUIREMENTS = []

def create_engine(context: HostContext, model_path: Path | None, config: EngineConfig) -> Engine:
  api_key = (context.config_dir / "elevenlabs_key").read_text()
  return ElevenLabsEngine(api_key)
```

### 12.4 Piper

```python
PLUGIN_MANIFEST = PluginManifest(
  id="piper",
  api_version="1.0",
  capabilities=[],
  engine=EngineManifest(
    voiceSources=[VoiceSourceManifest(id="downloadable", type="list", config={"models": [...]})],
    parameters=[ParameterManifest(id="speed", type="float", default=1.0, min=0.5, max=2.0)],
    audioFormats=[AudioFormatManifest(mime="audio/wav", extension="wav")],
  ),
)

MODEL_REQUIREMENTS = [
  ModelManifest(id="en_US-lessac-medium", name="English Lessac Medium", size="100MB"),
]

def create_engine(context: HostContext, model_path: Path | None, config: EngineConfig) -> Engine:
  return PiperEngine(model_path, config.device)
```

### 12.5 XTTS (with streaming and cancellation)

```python
PLUGIN_MANIFEST = PluginManifest(
  id="xtts",
  api_version="1.0",
  capabilities=["voice_list", "preview", "voice_clone", "streaming", "cancel"],
  requires=RequirementManifest(gpu=GpuRequirement(required=True, type="cuda")),
  engine=EngineManifest(
    voiceSources=[
      VoiceSourceManifest(id="speakers", type="speaker_id", config={"speakers": [...]}),
      VoiceSourceManifest(id="clone", type="clone", config={"requiresAudio": True, "maxDuration": 30}),
    ],
    parameters=[ParameterManifest(id="temperature", type="float", default=0.7, min=0.1, max=1.0)],
    audioFormats=[AudioFormatManifest(mime="audio/wav", extension="wav")],
  ),
)

MODEL_REQUIREMENTS = [
  ModelManifest(id="xtts_v2", name="XTTS v2", size="2GB"),
]

def create_engine(context: HostContext, model_path: Path | None, config: EngineConfig) -> Engine:
  return XTTSEngine(model_path, config.device)
```

XTTS session implements: EngineSession, StreamingSynthesizer, CancelableSession.

---

## 13. Summary of All Decisions

| Aspect | Decision |
|--------|----------|
| Engine | Factory, stateless, thread-safe for createSession() |
| EngineSession | Owns mutable execution state, not thread-safe |
| EngineSession ownership | Caller owns (transferred from createSession) |
| Engine session tracking | None; engine does not track sessions |
| StreamingSynthesizer | Optional capability of EngineSession |
| CancelableSession | Optional capability, cancel() raises CancelledError |
| dispose() | Idempotent, never raises |
| Engine.dispose() | Caller must dispose sessions first; undefined if violated |
| createSession() | Raises EngineError on failure, no partial sessions |
| create_engine() | Atomic, takes context, model_path, config |
| EngineConfig | Engine settings only, no resource references |
| model_path | Separate argument, not in EngineConfig |
| MODEL_REQUIREMENTS | Static at plugin level |
| HostContext | Minimal (3 fields) |
| Error handling | Typed exceptions (EngineError hierarchy) |
| Thread safety | Documented per component |
| Capabilities | Additive, optional interfaces |
| API versioning | api_version in manifest |
| Concurrent dispose/createSession | Fully initialized session or EngineError |
| Concurrent dispose/synthesizeStream | Not thread-safe; caller must complete iteration first |
