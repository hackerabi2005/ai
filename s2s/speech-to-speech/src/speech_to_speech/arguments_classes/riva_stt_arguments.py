from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RivaSTTHandlerArguments:
    """Connection settings for NVIDIA NIM Riva ASR (gRPC and NVCF HTTP)."""

    riva_stt_server: str = field(
        default="grpc.nvcf.nvidia.com:443",
        metadata={"help": "Riva gRPC server URI. Default is 'grpc.nvcf.nvidia.com:443'."},
    )
    riva_stt_use_ssl: bool = field(
        default=True,
        metadata={"help": "Use SSL for Riva gRPC connection. Default is True."},
    )
    riva_stt_function_id: str = field(
        default="1598d209-5e27-4d3c-8079-4751568b1081",
        metadata={"help": "NVCF function ID for Parakeet CTC 1.1B ASR."},
    )
    riva_stt_api_key: Optional[str] = field(
        default=None,
        metadata={"help": "NVIDIA API key. Defaults to NVIDIA_API_KEY environment variable."},
    )
    riva_stt_language_code: str = field(
        default="en-US",
        metadata={"help": "BCP-47 language code for Riva ASR. Default is 'en-US'."},
    )
    riva_stt_word_time_offsets: bool = field(
        default=True,
        metadata={"help": "Enable word time offsets in ASR requests. Default is True."},
    )
    riva_stt_http_url: Optional[str] = field(
        default="https://1598d209-5e27-4d3c-8079-4751568b1081.invocation.api.nvcf.nvidia.com/v1/audio/transcriptions",
        metadata={
            "help": "Optional NVCF HTTP transcription endpoint URL; set to empty string to force gRPC."
        },
    )
    riva_stt_use_grpc: bool = field(
        default=False,
        metadata={
            "help": "Use gRPC (riva.client.ASRService) instead of the NVCF HTTP endpoint. "
            "Default is False (uses HTTP with gRPC support available)."
        },
    )
    riva_stt_timeout: float = field(
        default=60.0,
        metadata={"help": "Request timeout in seconds. Default is 60.0."},
    )
    riva_stt_streaming: bool = field(
        default=True,
        metadata={
            "help": "Stream microphone audio chunks live over Riva gRPC when riva_stt_use_grpc is enabled."
        },
    )
