"""Invalid plugin: missing PLUGIN_MANIFEST."""

from __future__ import annotations

# This plugin intentionally does NOT export PLUGIN_MANIFEST
MODEL_REQUIREMENTS: list = []


def create_engine(context, model_path, config):
    raise NotImplementedError("This plugin is invalid")
