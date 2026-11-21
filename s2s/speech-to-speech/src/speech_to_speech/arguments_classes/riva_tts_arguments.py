from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RivaTTSHandlerArguments:
    """Connection and voice settings for NVIDIA NIM Riva TTS (gRPC)."""

    riva_tts_server: str = field(
        default="grpc.nvcf.nvidia.com:443",
        metadata={"help": "Riva gRPC server URI. Default is 'grpc.nvcf.nvidia.com:443'."},
    )
    riva_tts_use_ssl: bool = field(
        default=True,
        metadata={"help": "Use SSL for Riva gRPC connection. Default is True."},
    )
    riva_tts_function_id: str = field(
        default="ddacc747-1269-4fab-bfd9-8f593dead106",
        metadata={"help": "NVCF function ID for Chatterbox Multilingual TTS."},
    )
    riva_tts_api_key: Optional[str] = field(
        default=None,
        metadata={"help": "NVIDIA API key. Defaults to NVIDIA_API_KEY environment variable."},
    )
    riva_tts_language_code: str = field(
        default="en-US",
        metadata={"help": "BCP-47 language code for Riva TTS. Default is 'en-US'."},
    )
    riva_tts_voice: str = field(
        default="Chatterbox-Multilingual.en-US.Male",
        metadata={"help": "Voice name for Riva TTS. Default is 'Chatterbox-Multilingual.en-US.Male'."},
    )
    riva_tts_sample_rate: int = field(
        default=16000,
        metadata={"help": "Audio sample rate requested from Riva TTS. Default is 16000."},
    )
    riva_tts_blocksize: int = field(
        default=512,
        metadata={"help": "Pipeline output chunk size in 16 kHz samples. Default is 512."},
    )
