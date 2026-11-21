from dataclasses import dataclass, field
from typing import Optional

from speech_to_speech.arguments_classes.responses_api_language_model_arguments import (
    ResponsesApiLanguageModelHandlerArguments,
)


@dataclass
class ChatCompletionsLanguageModelHandlerArguments(ResponsesApiLanguageModelHandlerArguments):
    """Arguments for the ``chat-completions`` LLM backend.

    Inherits the OpenAI-compatible connection fields from the Responses-API
    arguments (``responses_api_base_url`` / ``responses_api_api_key`` /
    ``responses_api_stream`` / ``responses_api_disable_thinking``) so the same
    CLI flags and launcher env vars drive both backends. Defaults target the
    NVIDIA NIM Chat Completions endpoint with ``nvidia/nemotron-3-ultra-550b-a55b``.
    """

    model_name: str = field(
        default="nvidia/nemotron-3-ultra-550b-a55b",
        metadata={
            "help": "The model to use with the OpenAI-compatible Chat Completions API. "
            "Default is 'nvidia/nemotron-3-ultra-550b-a55b'."
        },
    )
    responses_api_base_url: Optional[str] = field(
        default="https://integrate.api.nvidia.com/v1",
        metadata={
            "help": "Base URL for the OpenAI-compatible Chat Completions endpoint. "
            "Default is 'https://integrate.api.nvidia.com/v1'."
        },
    )
    responses_api_disable_thinking: bool = field(
        default=False,
        metadata={
            "help": "Disable provider-side thinking/reasoning when supported by the OpenAI-compatible backend. "
            "Default is False (enables thinking on NVIDIA NIM)."
        },
    )
    responses_api_reasoning_effort: Optional[str] = field(
        default=None,
        metadata={
            "help": "Provider-specific reasoning level sent as extra_body={'reasoning_effort': <value>} on the "
            "Chat Completions request. Use to disable reasoning on providers where "
            "chat_template_kwargs.enable_thinking is ignored (e.g. 'none' / 'low'). When unset, falls back to "
            "the disable_thinking behaviour (chat_template_kwargs.enable_thinking). Default is None."
        },
    )
    responses_api_gen_temperature: Optional[float] = field(
        default=1.0,
        metadata={"help": "Sampling temperature for Chat Completions requests. Default is 1.0."},
    )
    responses_api_gen_top_p: Optional[float] = field(
        default=0.95,
        metadata={"help": "Top-p nucleus sampling for Chat Completions requests. Default is 0.95."},
    )
    responses_api_gen_max_tokens: Optional[int] = field(
        default=16384,
        metadata={"help": "Max completion tokens for Chat Completions requests. Default is 16384."},
    )
