"""Auto-discovery tests for TTS plugins.

This package contains generic tests that automatically run for every plugin
in the plugins/ directory. Tests verify:
- Manifest structure
- Engine creation and dispose contract
- Capability implementation

Plugin-specific tests remain in tests/test_<plugin>_plugin.py for
integration with real dependencies (e.g., KPipeline for Kokoro).
"""