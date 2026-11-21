from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, fields
from importlib import import_module
from queue import Queue
from threading import Event
from typing import Any, Literal

from speech_to_speech.arguments_classes.chat_completions_language_model_arguments import (
    ChatCompletionsLanguageModelHandlerArguments,
)
from speech_to_speech.arguments_classes.openai_stt_arguments import OpenAICompatibleSTTHandlerArguments
from speech_to_speech.arguments_classes.riva_stt_arguments import RivaSTTHandlerArguments
from speech_to_speech.arguments_classes.riva_tts_arguments import RivaTTSHandlerArguments
from speech_to_speech.pipeline.cancel_scope import CancelScope
from speech_to_speech.pipeline.speculative_turns import SpeculativeTurnTracker

BackendKind = Literal["stt", "llm", "tts"]
BackendConfig = dict[str, Any]

logger = logging.getLogger(__name__)


@dataclass
class EmptyBackendArguments:
    """Argument placeholder for a backend with no backend-specific options."""


@dataclass(frozen=True)
class BackendCapabilities:
    """Construction details that affect stage composition, not backend selection."""

    bypasses_transcription_notifier: bool = False
    supports_audio_input: bool = False
    supports_llm_proxy: bool = False
    streams_audio_chunks: bool = False


@dataclass(frozen=True)
class HandlerContext:
    """Pipeline-local state made available to every registered factory."""

    stop_event: Event
    queue_in: Queue[Any]
    queue_out: Queue[Any]
    text_output_queue: Queue[Any]
    should_listen: Event
    cancel_scope: CancelScope
    speculative_turns: SpeculativeTurnTracker
    pipeline_index: int
    sample_rate: int
    enable_live_transcription: bool
    live_transcription_update_interval: float
    detect_llm_output_language: bool = False


HandlerFactory = Callable[[HandlerContext, Mapping[str, Any]], Any]
ConfigNormalizer = Callable[[Any], BackendConfig]


@dataclass(frozen=True)
class BackendSpec:
    """Static construction metadata for one built-in backend."""

    name: str
    kind: BackendKind
    config_type: type[Any]
    create_handler: HandlerFactory
    config_prefix: str | None = None
    normalize_config: ConfigNormalizer | None = None
    required_extra: str | None = None
    capabilities: BackendCapabilities = field(default_factory=BackendCapabilities)

    def normalize(self, config: Any) -> BackendConfig:
        if not isinstance(config, self.config_type):
            raise TypeError(f"Backend {self.name!r} expects {self.config_type.__name__}, got {type(config).__name__}.")
        normalizer = self.normalize_config
        if normalizer is not None:
            return normalizer(config)
        return normalize_dataclass_config(config, self.config_prefix)


@dataclass(frozen=True)
class BackendSelection:
    """A selected registry entry and its normalized configuration."""

    spec: BackendSpec
    config: BackendConfig

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def kind(self) -> BackendKind:
        return self.spec.kind

    def copy_for_pipeline(self) -> BackendSelection:
        return BackendSelection(self.spec, deepcopy(self.config))


def normalize_dataclass_config(config: Any, prefix: str | None = None) -> BackendConfig:
    """Return handler kwargs without mutating the parsed argument dataclass."""

    normalized: BackendConfig = {}
    generation: BackendConfig = {}
    marker = f"{prefix}_" if prefix else None

    for config_field in fields(config):
        name = config_field.name
        value = deepcopy(getattr(config, name))
        if marker and name.startswith(marker):
            name = name[len(marker) :]
        if name == "gen_kwargs" and isinstance(value, Mapping):
            generation.update(value)
        elif name.startswith("gen_"):
            generation[name[len("gen_") :]] = value
        else:
            normalized[name] = value

    normalized["gen_kwargs"] = generation
    return normalized


def build_backend_registry(kind: BackendKind, specs: Iterable[BackendSpec]) -> dict[str, BackendSpec]:
    """Build an explicit registry and reject ambiguous entries eagerly."""

    registry: dict[str, BackendSpec] = {}
    for spec in specs:
        if spec.kind != kind:
            raise ValueError(f"Backend {spec.name!r} has kind {spec.kind!r}; expected {kind!r}.")
        if spec.name in registry:
            raise ValueError(f"Duplicate {kind} backend name: {spec.name!r}.")
        registry[spec.name] = spec
    return registry


def _optional_dependency_error(selection: BackendSelection, exc: BaseException) -> ImportError | None:
    extra = selection.spec.required_extra
    if extra is None:
        return None
    return ImportError(
        f"Backend {selection.name!r} ({selection.kind}) requires optional dependencies. "
        f'Install them with `pip install "speech-to-speech[{extra}]"`. '
        f"Original import error: {exc}"
    )


def create_backend_handler(selection: BackendSelection, context: HandlerContext) -> Any:
    """Construct a handler and turn lazy dependency failures into actionable errors."""

    try:
        return selection.spec.create_handler(context, selection.config)
    except ImportError as exc:
        dependency_error = _optional_dependency_error(selection, exc)
        if dependency_error is None:
            raise
        raise dependency_error from exc


def _load_handler(module_name: str, class_name: str) -> type[Any]:
    try:
        module = import_module(module_name)
    except RuntimeError as exc:
        raise ImportError(f"Could not import backend module {module_name!r}: {exc}") from exc
    return getattr(module, class_name)


def _simple_handler_factory(
    module_name: str,
    class_name: str,
    *,
    setup_should_listen: bool = False,
    attach_speculative_turns: bool = False,
    context_kwargs: bool = False,
    pass_assistant_language_flag: bool = False,
) -> HandlerFactory:
    def create(context: HandlerContext, config: Mapping[str, Any]) -> Any:
        handler_class = _load_handler(module_name, class_name)
        setup_kwargs = dict(config)
        if context_kwargs:
            setup_kwargs.update(
                cancel_scope=context.cancel_scope,
                speculative_turns=context.speculative_turns,
            )
        if pass_assistant_language_flag:
            setup_kwargs["detect_llm_output_language"] = context.detect_llm_output_language
        handler = handler_class(
            context.stop_event,
            queue_in=context.queue_in,
            queue_out=context.queue_out,
            setup_args=(context.should_listen,) if setup_should_listen else (),
            setup_kwargs=setup_kwargs,
        )
        if attach_speculative_turns:
            handler.speculative_turns = context.speculative_turns
        return handler

    return create


def _create_audio_input(context: HandlerContext, _config: Mapping[str, Any]) -> Any:
    handler_class = _load_handler("speech_to_speech.LLM.audio_input_notifier", "AudioInputNotifier")
    return handler_class(
        context.stop_event,
        queue_in=context.queue_in,
        queue_out=context.queue_out,
        setup_kwargs={
            "sample_rate": context.sample_rate,
            "speculative_turns": context.speculative_turns,
            "text_output_queue": context.text_output_queue,
        },
    )


STT_BACKENDS = build_backend_registry(
    "stt",
    [
        BackendSpec(
            "none",
            "stt",
            EmptyBackendArguments,
            _create_audio_input,
            capabilities=BackendCapabilities(bypasses_transcription_notifier=True),
        ),
        BackendSpec(
            "openai",
            "stt",
            OpenAICompatibleSTTHandlerArguments,
            _simple_handler_factory(
                "speech_to_speech.STT.openai_compatible_handler",
                "OpenAICompatibleSTTHandler",
                attach_speculative_turns=True,
            ),
            config_prefix="openai_stt",
        ),
        BackendSpec(
            "riva",
            "stt",
            RivaSTTHandlerArguments,
            _simple_handler_factory(
                "speech_to_speech.STT.riva_stt_handler",
                "RivaSTTHandler",
                attach_speculative_turns=True,
            ),
            config_prefix="riva_stt",
            capabilities=BackendCapabilities(streams_audio_chunks=True),
        ),
    ],
)

LLM_BACKENDS = build_backend_registry(
    "llm",
    [
        BackendSpec(
            "chat-completions",
            "llm",
            ChatCompletionsLanguageModelHandlerArguments,
            _simple_handler_factory(
                "speech_to_speech.LLM.chat_completions_language_model",
                "ChatCompletionsApiModelHandler",
                context_kwargs=True,
            ),
            config_prefix="responses_api",
            capabilities=BackendCapabilities(supports_audio_input=True, supports_llm_proxy=True),
        ),
    ],
)

TTS_BACKENDS = build_backend_registry(
    "tts",
    [
        BackendSpec(
            "riva",
            "tts",
            RivaTTSHandlerArguments,
            _simple_handler_factory(
                "speech_to_speech.TTS.riva_tts_handler",
                "RivaTTSHandler",
                setup_should_listen=True,
                context_kwargs=True,
                pass_assistant_language_flag=True,
            ),
            config_prefix="riva_tts",
        ),
    ],
)
