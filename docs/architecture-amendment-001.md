# Architecture Amendment #1: EngineConfig — `lang_code` field

**Date:** 2026-07-12
**Status:** Accepted
**PR:** #12 (Normalize Pipeline Public API)

## Summary

Add `lang_code: str = "a"` to `EngineConfig` and update its definition to clarify the architectural contract.

## Background

During migration from the old `KokoroBackend` to the Plugin Architecture, the `lang_code` parameter became a dead argument. The old backend read it from `**kwargs` and passed it to `KPipeline(lang_code=...)`. The new `KokoroPlugin.create_engine()` hardcodes `lang_code="a"`, ignoring the config entirely. Callers continued passing `lang_code` to `create_pipeline()`, unaware it had no effect.

This is a functional regression relative to the pre-Plugin Architecture behavior.

## Decision

### 1. Updated EngineConfig definition

**Before:**
```
Immutable value object for engine initialization settings.
Contains only engine-specific settings, no resource references.
```

**After:**
```
Immutable configuration of an Engine instance.
Contains parameters that define how a particular Engine instance is
created and that remain constant throughout the lifetime of that Engine.
Plugin implementations may ignore fields that are not applicable to them.
```

### 2. New field

```python
@dataclass(frozen=True)
class EngineConfig:
    device: str = "cpu"
    lang_code: str = "a"
```

### 3. Architectural rules

- **Fields in EngineConfig are optional unless explicitly required by a plugin.**
- **Plugins MUST ignore unsupported EngineConfig fields.**
- **All parameters that may vary between individual synthesis requests must remain in `SynthesisRequest.parameters`.**

## Rationale

Analysis of real TTS engines (Kokoro, Piper, XTTS, Coqui, StyleTTS2, Fish Speech) confirmed:

| Parameter type | Where it belongs | Example |
|---------------|-----------------|---------|
| Engine instance config (immutable) | `EngineConfig` | `device`, `lang_code` |
| Synthesis parameters (per-request) | `SynthesisRequest.parameters` | `speed`, `split_pattern`, `total_steps` |

`lang_code` determines the engine's behavior at creation time and cannot be changed during the engine's lifetime. It is not a synthesis parameter.

## Impact on existing plugins

| Plugin | `device` | `lang_code` | Notes |
|--------|----------|-------------|-------|
| Kokoro | Reads ✓ | Reads ✓ (was hardcoded, now from config) | Regression fixed |
| SuperTonic | Ignores | Ignores | No change — no language concept |
| Future plugins | May read | May ignore | Field-ignoring rule applies |

## Contract tests added

```python
class TestEngineConfigContract:
    def test_default_lang_code(self)       # EngineConfig().lang_code == "a"
    def test_custom_lang_code(self)        # EngineConfig(lang_code="j").lang_code == "j"
    def test_immutability_lang_code(self)  # frozen — cannot reassign
    def test_plugins_may_ignore_irrelevant_fields(self)  # field-ignoring rule
    def test_engine_config_contains_engine_instance_configuration(self)  # definition
```

## Files changed

| File | Change |
|------|--------|
| `abogen/tts_plugin/types.py` | Updated docstring, added `lang_code: str = "a"` |
| `plugins/kokoro/__init__.py` | Reads `config.lang_code` instead of hardcoded `"a"` |
| `abogen/tts_plugin/utils.py` | `create_pipeline()` passes `lang_code` to `EngineConfig` |
| `tests/contracts/test_types_contract.py` | 5 new contract tests |
| `tests/contracts/test_plugin_manager_contract.py` | Updated assertion for `lang_code` |
| `tests/test_behavioral_regression.py` | Updated `test_engine_config_defaults` |
