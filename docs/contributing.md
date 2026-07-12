# Contributing to Abogen

We welcome contributions to Abogen!

## How to Contribute

1. Fork the repository
2. Create a branch for your feature
3. Make your changes
4. Write tests
5. Submit a pull request

## Code Standards

- Follow PEP 8 for Python
- Use TypeScript for JavaScript
- Type hints required for new Python code
- Document complex logic with comments

## Plugin Architecture

When contributing TTS engines, implement the **Plugin Architecture** contract.

See [Developer Guide](developer-guide.md#5-adding-a-new-plugin) for:
- Required exports (`PLUGIN_MANIFEST`, `MODEL_REQUIREMENTS`, `create_engine`)
- Engine / EngineSession contracts
- Capability interfaces (`VoiceLister`, `PreviewGenerator`, etc.)
- Step-by-step plugin creation guide

## Testing

```bash
# All tests
pytest

# Contract tests (architectural compliance)
pytest tests/contracts/

# Behavioral regression tests
pytest tests/test_behavioral_regression.py
```

## Documentation

- Update relevant docs in `docs/` when changing architecture or APIs
- Add docstrings to all public functions/classes
- Follow existing documentation style

## Pull Request Checklist

- [ ] Tests pass (`pytest`)
- [ ] Code follows style guide (`ruff check`, `ruff format`)
- [ ] Documentation updated
- [ ] No legacy architecture references (`TTSBackend`, `register_backend`, `TTSBackendRegistry`)
- [ ] Uses new Plugin Architecture patterns
