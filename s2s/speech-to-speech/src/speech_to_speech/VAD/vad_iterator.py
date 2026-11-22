from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

# Bound noise history while idle, independently of the utterance-end delay.
_MODEL_RESET_IDLE_MS = 500


def find_silero_onnx_path() -> Path | None:
    """Locate the cached silero_vad.onnx model without importing torch."""
    candidates: list[Path] = []
    torch_home = os.environ.get("TORCH_HOME")
    if torch_home:
        candidates.append(Path(torch_home).expanduser() / "hub")
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        candidates.append(Path(xdg_cache).expanduser() / "torch" / "hub")
    candidates.append(Path.home() / ".cache" / "torch" / "hub")
    for hub_dir in candidates:
        onnx_path = hub_dir / "snakers4_silero-vad_master" / "src" / "silero_vad" / "data" / "silero_vad.onnx"
        if onnx_path.is_file():
            return onnx_path
    return None


class SileroOnnxModel:
    """Pure-NumPy ONNX Runtime wrapper for Silero VAD (avoids importing PyTorch)."""

    _is_onnx_silero = True

    def __init__(self, path: str | Path) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        providers = (
            ["CPUExecutionProvider"] if "CPUExecutionProvider" in ort.get_available_providers() else None
        )
        self.session = ort.InferenceSession(str(path), providers=providers, sess_options=opts)
        self.sample_rates = [8000, 16000]
        self.reset_states()

    def reset_states(self, batch_size: int = 1) -> None:
        self._state = np.zeros((2, batch_size, 128), dtype=np.float32)
        self._context = np.empty((0, 0), dtype=np.float32)
        self._last_sr = 0
        self._last_batch_size = 0

    def _validate_input(self, x: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
        if x.ndim == 1:
            x = x[np.newaxis, :]
        if x.ndim > 2:
            raise ValueError(f"Too many dimensions for input audio chunk {x.ndim}")
        if sr != 16000 and (sr % 16000 == 0):
            x = x[:, :: (sr // 16000)]
            sr = 16000
        if sr not in self.sample_rates:
            raise ValueError(f"Supported sampling rates: {self.sample_rates} (or multiple of 16000)")
        if sr / x.shape[1] > 31.25:
            raise ValueError("Input audio chunk is too short")
        return x, sr

    def __call__(self, x: Any, sr: int) -> np.ndarray:
        arr = x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x, dtype=np.float32)
        if arr.dtype != np.float32:
            arr = arr.astype(np.float32, copy=False)
        arr, sr = self._validate_input(arr, sr)
        num_samples = 512 if sr == 16000 else 256
        if arr.shape[-1] != num_samples:
            raise ValueError(
                f"Provided number of samples is {arr.shape[-1]} "
                f"(Supported values: 256 for 8000 sample rate, 512 for 16000)"
            )
        batch_size = arr.shape[0]
        context_size = 64 if sr == 16000 else 32
        if not self._last_batch_size or self._last_sr != sr or self._last_batch_size != batch_size:
            self.reset_states(batch_size)
        if self._context.size == 0:
            self._context = np.zeros((batch_size, context_size), dtype=np.float32)

        inp = np.concatenate((self._context, arr), axis=1)
        out, state = self.session.run(
            None,
            {
                "input": inp,
                "state": self._state,
                "sr": np.array(sr, dtype=np.int64),
            },
        )
        self._state = state
        self._context = inp[..., -context_size:]
        self._last_sr = sr
        self._last_batch_size = batch_size
        return out


def _to_numpy_chunk(x: Any) -> np.ndarray:
    if isinstance(x, np.ndarray):
        return x.astype(np.float32, copy=False)
    if hasattr(x, "detach"):
        return x.detach().cpu().numpy().astype(np.float32, copy=False)
    return np.asarray(x, dtype=np.float32)


class VADIterator:
    def __init__(
        self,
        model: Any,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_silence_duration_ms: int = 300,
        speech_pad_ms: int = 30,
    ) -> None:
        """
        Mainly taken from https://github.com/snakers4/silero-vad
        Class for stream imitation
        """

        self.model = model
        self._is_onnx = bool(getattr(model, "_is_onnx_silero", False))
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        self.buffer: list[np.ndarray] = []
        self.prefix_buffer: list[np.ndarray] = []
        self.active_speech_samples = 0
        self.last_utterance_active_speech_samples = 0
        self._pre_speech_buffer: deque[np.ndarray] = deque()
        self._pre_speech_samples = 0

        if sampling_rate not in [8000, 16000]:
            raise ValueError("VADIterator does not support sampling rates other than [8000, 16000]")

        self.min_silence_samples = int(sampling_rate * min_silence_duration_ms / 1000)
        self.speech_pad_samples = int(sampling_rate * speech_pad_ms / 1000)
        self._model_reset_idle_samples = int(sampling_rate * _MODEL_RESET_IDLE_MS / 1000)
        self.reset_states()

    def reset_states(self) -> None:
        self.model.reset_states()
        self._model_idle_samples = 0
        self.triggered = False
        self.temp_end = 0
        self.last_speech_end_sample: int | None = None
        self.current_sample = 0
        self.buffer = []
        self.prefix_buffer = []
        self.active_speech_samples = 0
        self.last_utterance_active_speech_samples = 0
        self._pre_speech_buffer.clear()
        self._pre_speech_samples = 0

    def _num_samples(self, chunk: np.ndarray) -> int:
        return len(chunk[0]) if chunk.ndim == 2 else len(chunk)

    def _trim_pre_speech_buffer(self) -> None:
        while (
            self.speech_pad_samples > 0
            and self._pre_speech_buffer
            and self._pre_speech_samples > self.speech_pad_samples
        ):
            first = self._pre_speech_buffer[0]
            first_samples = self._num_samples(first)
            excess = self._pre_speech_samples - self.speech_pad_samples

            if excess >= first_samples:
                self._pre_speech_buffer.popleft()
                self._pre_speech_samples -= first_samples
                continue

            if first.ndim == 2:
                self._pre_speech_buffer[0] = first[:, excess:]
            else:
                self._pre_speech_buffer[0] = first[excess:]
            self._pre_speech_samples -= excess

    def _remember_pre_speech(self, chunk: np.ndarray) -> None:
        if self.speech_pad_samples <= 0:
            self._pre_speech_buffer.clear()
            self._pre_speech_samples = 0
            return

        self._pre_speech_buffer.append(chunk)
        self._pre_speech_samples += self._num_samples(chunk)
        self._trim_pre_speech_buffer()

    def _speech_buffer(self) -> list[np.ndarray]:
        if not self.prefix_buffer:
            return list(self.buffer)
        return [*self.prefix_buffer, *self.buffer]

    def speech_buffer(self) -> list[np.ndarray]:
        return self._speech_buffer()

    def __call__(self, x: Any) -> list[np.ndarray] | None:
        chunk = _to_numpy_chunk(x)
        window_size_samples = len(chunk[0]) if chunk.ndim == 2 else len(chunk)
        self.current_sample += window_size_samples

        if self._is_onnx:
            speech_prob = float(self.model(chunk, self.sampling_rate).item())
        else:
            import torch

            with torch.no_grad():
                tensor_in = x if torch.is_tensor(x) else torch.from_numpy(chunk)
                speech_prob = float(self.model(tensor_in, self.sampling_rate).item())

        if (speech_prob >= self.threshold) and not self.triggered:
            self._model_idle_samples = 0
            self.triggered = True
            self.prefix_buffer = list(self._pre_speech_buffer)
            self._pre_speech_buffer.clear()
            self._pre_speech_samples = 0
            self.buffer.append(chunk)
            self.active_speech_samples = window_size_samples
            self.last_utterance_active_speech_samples = 0
            return None

        if not self.triggered:
            self._remember_pre_speech(chunk)
            if speech_prob < self.threshold - 0.15:
                self._model_idle_samples += window_size_samples
                if self._model_idle_samples >= self._model_reset_idle_samples:
                    # Reset inference history only: padding and the session
                    # sample clock must survive for the next speech segment.
                    self.model.reset_states()
                    self._model_idle_samples = 0
            else:
                self._model_idle_samples = 0
            return None

        if self.triggered:
            self.buffer.append(chunk)
            if speech_prob >= self.threshold - 0.15:
                self.active_speech_samples += window_size_samples
                if self.temp_end:
                    self.temp_end = 0
                    return None

            if speech_prob < self.threshold - 0.15:
                if not self.temp_end:
                    self.temp_end = self.current_sample
                if self.current_sample - self.temp_end < self.min_silence_samples:
                    return None

                # End of speech: keep the final low-confidence chunks that were
                # observed before VAD decided the utterance was done.
                self.last_speech_end_sample = self.temp_end - window_size_samples
                self.temp_end = 0
                self.triggered = False
                spoken_utterance = self.speech_buffer()
                self.last_utterance_active_speech_samples = self.active_speech_samples
                self.active_speech_samples = 0
                self.buffer = []
                self.prefix_buffer = []
                self.model.reset_states()
                self._model_idle_samples = 0
                return spoken_utterance

        return None
