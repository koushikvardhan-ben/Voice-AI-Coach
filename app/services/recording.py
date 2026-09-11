"""Record both call legs to a single stereo WAV (agent left, customer right).

Twilio streams each track as 8 kHz mono G.711 mu-law. We decode to PCM16 with a
lookup table (``audioop`` was removed in Python 3.13) and place every frame on a
shared timeline using Twilio's per-frame timestamp, so a dropped/reconnected
media socket leaves a silent gap instead of desynchronising the two speakers.
Only telephony-confirmed audio is fed in (the media handler gates pre-answer
ringback/greeting), so recordings start at the real conversation.
"""
from __future__ import annotations

import array
import logging
import os
import sys
import wave

from app.config import settings
from app.models import Speaker

log = logging.getLogger("recording")

SAMPLE_RATE = 8000
BYTES_PER_SAMPLE = 2  # PCM16


def _build_ulaw_table() -> list[int]:
    """G.711 mu-law byte -> signed 16-bit PCM (Sun reference implementation)."""
    table = []
    for byte in range(256):
        u = ~byte & 0xFF
        t = ((u & 0x0F) << 3) + 0x84
        t <<= (u & 0x70) >> 4
        table.append((0x84 - t) if (u & 0x80) else (t - 0x84))
    return table


_ULAW_TO_PCM = _build_ulaw_table()


def _decode(ulaw: bytes) -> bytes:
    samples = array.array("h", (_ULAW_TO_PCM[b] for b in ulaw))
    if sys.byteorder == "big":  # WAV is little-endian
        samples.byteswap()
    return samples.tobytes()


class CallRecorder:
    """Accumulate both mu-law tracks into aligned PCM16 channels."""

    def __init__(self) -> None:
        self._channel: dict[Speaker, bytearray] = {
            Speaker.AGENT: bytearray(), Speaker.CUSTOMER: bytearray()}
        self._base_ms = 0.0          # start of the current stream on the global timeline
        self._stream_start_ms: float | None = None  # first timestamp in the current stream
        self._end_ms = 0.0           # furthest position written so far (ms)
        self._frames = 0

    def new_stream(self) -> None:
        """A Twilio 'start': continue after existing audio; its clock resets to 0."""
        self._base_ms = self._end_ms
        self._stream_start_ms = None

    def add(self, speaker: Speaker, timestamp_ms: float, ulaw: bytes) -> None:
        if not ulaw or speaker not in self._channel:
            return
        if self._stream_start_ms is None:
            self._stream_start_ms = timestamp_ms
        pos_ms = self._base_ms + max(0.0, timestamp_ms - self._stream_start_ms)
        pcm = _decode(ulaw)
        buf = self._channel[speaker]
        start = int(pos_ms / 1000 * SAMPLE_RATE) * BYTES_PER_SAMPLE
        if len(buf) < start:                       # pad the gap with silence
            buf.extend(b"\x00" * (start - len(buf)))
        buf[start:start + len(pcm)] = pcm          # place (overwrite/extend)
        self._end_ms = max(self._end_ms, pos_ms + len(pcm) / BYTES_PER_SAMPLE / SAMPLE_RATE * 1000)
        self._frames += 1

    def has_audio(self) -> bool:
        return self._frames > 0

    def write_wav(self, path: str) -> None:
        left = self._channel[Speaker.AGENT]
        right = self._channel[Speaker.CUSTOMER]
        n = max(len(left), len(right))
        left = left + b"\x00" * (n - len(left))
        right = right + b"\x00" * (n - len(right))
        # Interleave L/R int16 frames without a numpy dependency.
        stereo = bytearray(2 * n)
        stereo[0::4] = left[0::2]
        stereo[1::4] = left[1::2]
        stereo[2::4] = right[0::2]
        stereo[3::4] = right[1::2]
        with wave.open(path, "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(BYTES_PER_SAMPLE)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(stereo)


def recording_path(call_id: str) -> str:
    return os.path.join(settings.recordings_dir, f"{call_id}.wav")


def save_recording(session) -> str | None:
    """Persist the call's stereo WAV; return its path, or None if nothing captured."""
    recorder = getattr(session, "recorder", None)
    if recorder is None or not recorder.has_audio():
        return None
    os.makedirs(settings.recordings_dir, exist_ok=True)
    path = recording_path(session.call_id)
    recorder.write_wav(path)
    log.info("recording saved call_id=%s path=%s", session.call_id, path)
    return path
