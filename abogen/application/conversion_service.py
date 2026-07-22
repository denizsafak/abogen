"""ConversionService — main orchestrator for the conversion flow.

Ties together planner, executor, and finalizers into a single entry point.
Both UIs (PyQt, WebUI) call ConversionService.run() to execute a conversion.

Responsibilities:
- Prepare TTSContext (normalization settings, pronunciation rules)
- Build ConversionPlan via planner
- Execute conversion via executor
- Handle lifecycle (cleanup, error handling)
- Return ConversionResult

The service NEVER imports from PyQt or WebUI.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from abogen.application.conversion_executor import execute_conversion
from abogen.application.conversion_models import ConversionPlan
from abogen.application.conversion_planner import build_conversion_plan
from abogen.application.conversion_ports import (
    ConversionEvents,
    PipelineProvider,
    VoiceResolver,
)
from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_result import ConversionResult
from abogen.domain.enums import SubtitleMode
from abogen.domain.normalization import TTSContext
from abogen.domain.split_pattern import get_split_pattern


def run_conversion(
    request: ConversionRequest,
    events: ConversionEvents,
    pipeline_provider: PipelineProvider,
    voice_resolver: VoiceResolver,
) -> ConversionResult:
    """Execute a conversion request and return the result.

    This is the single entry point for both UIs. It orchestrates:
    1. TTS context preparation
    2. Conversion planning
    3. Conversion execution
    4. Resource cleanup

    Args:
        request: Normalized conversion request
        events: UI-specific callbacks (log, progress, check_cancelled)
        pipeline_provider: Provides TTS backends
        voice_resolver: Resolves voice specs into loaded voices

    Returns:
        ConversionResult with paths and markers

    Raises:
        ConversionCancelled: If conversion was cancelled
        ValueError: If request is invalid
        Exception: On TTS or I/O errors
    """
    try:
        # Stage 1: Prepare TTS context
        events.log("Preparing conversion pipeline")
        tts_context = _prepare_tts_context(request, events)

        # Stage 2: Build conversion plan
        events.log("Building conversion plan")
        plan = build_conversion_plan(request)

        # Stage 3: Execute conversion
        events.log("Starting conversion")
        result = execute_conversion(
            plan=plan,
            events=events,
            pipeline_provider=pipeline_provider,
            voice_resolver=voice_resolver,
            tts_context=tts_context,
        )

        # Stage 4: Finalize
        events.log("Conversion complete")
        return result

    except Exception as e:
        events.log(f"Conversion failed: {e}", level="error")
        raise


def _prepare_tts_context(
    request: ConversionRequest,
    events: ConversionEvents,
) -> TTSContext:
    """Prepare TTSContext with normalization settings.

    This compiles pronunciation/heteronym rules and creates the
    normalization context used during conversion.

    Args:
        request: Conversion request with override settings
        events: For logging warnings about missing features

    Returns:
        TTSContext ready for text normalization
    """
    from abogen.domain.normalization import (
        build_apostrophe_config,
        get_runtime_settings,
    )
    from abogen.domain.pronunciation import (
        compile_heteronym_sentence_rules,
        compile_pronunciation_rules,
        merge_pronunciation_overrides,
    )

    # Get runtime normalization settings
    normalization_settings = get_runtime_settings()

    # Build apostrophe config
    apostrophe_config = build_apostrophe_config(
        settings=normalization_settings,
    )

    # Check for num2words availability
    if apostrophe_config.convert_numbers:
        try:
            import num2words  # noqa: F401
        except ImportError:
            events.log(
                "Number normalization is enabled but 'num2words' library is not available. "
                "Numbers will NOT be converted to words.",
                level="warning",
            )

    # Compute split pattern
    split_pattern = get_split_pattern(
        request.language or Language.EN_US,
        request.subtitle_mode or SubtitleMode.DISABLED,
    )

    # Merge pronunciation overrides (manual + pronunciation)
    # Create a mock job-like object for merge_pronunciation_overrides
    class _MockJob:
        def __init__(self, req):
            self.pronunciation_overrides = req.pronunciation_overrides
            self.manual_overrides = req.manual_overrides
            self.heteronym_overrides = req.heteronym_overrides

    merged_overrides = merge_pronunciation_overrides(_MockJob(request))

    # Compile rules
    pronunciation_rules = compile_pronunciation_rules(merged_overrides)
    heteronym_rules = compile_heteronym_sentence_rules(request.heteronym_overrides)

    if heteronym_rules:
        events.log(
            f"Applying {len(heteronym_rules)} heteronym override(s) during conversion.",
            level="debug",
        )
    if pronunciation_rules:
        events.log(
            f"Applying {len(pronunciation_rules)} pronunciation override(s) during conversion.",
            level="debug",
        )

    return TTSContext(
        split_pattern=split_pattern,
        pronunciation_rules=pronunciation_rules,
        heteronym_rules=heteronym_rules,
        normalization_overrides=request.normalization_overrides,
    )
