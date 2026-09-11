"""Two independent streaming STT connections with bounded audio buffering.

Twilio receives no network backpressure from Deepgram: send() only enqueues.
Audio collected during startup/reconnection is retained up to a small bound;
long outages are reported instead of hiding gaps or replaying minutes of audio.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from urllib.parse import urlencode

import websockets
from app.config import settings
from app.models import Speaker, notice_event
from app.services.transcript import TrackTranscriber

log = logging.getLogger("deepgram")
DG_BASE = "wss://api.deepgram.com/v1/listen"
BYTES_PER_SECOND = 8000  # mono 8 kHz, one mu-law byte per sample


class DeepgramTrack:
    def __init__(self, speaker: Speaker, transcriber: TrackTranscriber,
                 language: str | None = None, keyterms: list[str] | None = None) -> None:
        self.language = language or settings.deepgram_language
        self.speaker = speaker
        self.transcriber = transcriber
        self.keyterms = keyterms or []
        self._ws = None
        self._closed = False
        self._finishing = False
        self._queue: asyncio.Queue[tuple[bytes, float]] = asyncio.Queue()
        self._queued_bytes = 0
        self._max_bytes = int(BYTES_PER_SECOND * settings.stt_audio_buffer_seconds)
        self._dropped_bytes = 0
        self._gap_reported = False
        self._last_gap_status = 0.0
        self._done = asyncio.Event()
        self._running = False
        self._send_lock = asyncio.Lock()
        self._first_audio_at: float | None = None
        self._first_result = True
        self._sent_bytes = 0
        self._audio_clock = deque(maxlen=3000)
        self._result_age_ms: int | None = None
        self._last_metrics_at = 0.0

    def _url(self) -> str:
        params = {
            'model': settings.deepgram_model, 'language': self.language,
            'encoding': 'mulaw', 'sample_rate': 8000, 'channels': 1,
            'interim_results': 'true', 'punctuate': 'true',
            'smart_format': str(settings.stt_smart_format).lower(),
            'no_delay': 'true', 'endpointing': settings.stt_endpointing_ms,
            'utterance_end_ms': 1000, 'vad_events': 'true',
        }
        if settings.deepgram_model.startswith('nova-3') and self.keyterms:
            params['keyterm'] = self.keyterms
        return f"{DG_BASE}?{urlencode(params, doseq=True)}"

    def _status(self, state: str) -> None:
        event = {
            'type': 'stt_status', 'speaker': self.speaker.value,
            'state': state, 'language': self.language,
            'buffered_ms': round(self._queued_bytes / 8),
            'dropped_ms': round(self._dropped_bytes / 8),
            'result_age_ms': self._result_age_ms,
        }
        self.transcriber.session.stt_state[self.speaker.value] = event
        self.transcriber.session.push(event)

    def _report_gap(self, count: int) -> None:
        self._dropped_bytes += count
        if not self._gap_reported:
            self._gap_reported = True
            self.transcriber.session.push(notice_event('warn',
                f"{self.speaker.value.capitalize()} transcription lost some audio during a connection interruption. There may be a gap in the transcript."))
        if time.monotonic() - self._last_gap_status >= 1:
            self._last_gap_status = time.monotonic()
            self._status('degraded')

    async def _connect(self) -> None:
        started = time.monotonic()
        self._sent_bytes = 0
        self._audio_clock.clear()
        self._result_age_ms = None
        self._ws = await websockets.connect(
            self._url(), additional_headers={'Authorization': f'Token {settings.deepgram_api_key}'},
            open_timeout=5, close_timeout=1, ping_interval=20, ping_timeout=10,
            max_size=2 ** 20, compression=None)
        log.info('deepgram[%s] ready language=%s connect_ms=%d',
                 self.speaker.value, self.language, (time.monotonic() - started) * 1000)
        self._status('streaming')

    async def _write(self, ws, payload) -> None:
        # Serialize control frames and audio on the same socket.
        async with self._send_lock:
            await asyncio.wait_for(ws.send(payload), timeout=2)

    async def _send_loop(self, ws) -> None:
        while True:
            audio, received_at = await self._queue.get()
            self._queued_bytes -= len(audio)
            try:
                await self._write(ws, audio)
                self._sent_bytes += len(audio)
                self._audio_clock.append((self._sent_bytes / BYTES_PER_SECOND, received_at))
            except (Exception, asyncio.CancelledError):
                # Delivery of an in-flight failed write is ambiguous: don't replay
                # it into a new stream and risk duplicated speech.
                self._report_gap(len(audio))
                raise
            finally:
                self._queue.task_done()

    async def _receive_loop(self, ws) -> None:
        async for message in ws:
            if not isinstance(message, (bytes, bytearray)):
                self._handle(json.loads(message))

    async def run(self) -> None:
        self._running = True
        self._done.clear()
        backoff = .25
        try:
            if not settings.deepgram_api_key:
                self._status('error')
                self.transcriber.session.push(notice_event('error', 'Transcription is unavailable: DEEPGRAM_API_KEY is missing.'))
                return
            while not self._closed and not self._finishing:
                self._status('connecting' if self._ws is None else 'reconnecting')
                jobs = []
                try:
                    await self._connect()
                    if self._closed or self._finishing:
                        break
                    ws = self._ws
                    jobs = [asyncio.create_task(self._send_loop(ws)),
                            asyncio.create_task(self._receive_loop(ws))]
                    completed, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                    for task in completed:
                        task.result()
                    backoff = .25
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Avoid logging the request URI/headers (credentials and future vocabulary).
                    log.warning('deepgram[%s] connection failed (%s)', self.speaker.value, type(exc).__name__)
                    status = getattr(getattr(exc, 'response', None), 'status_code', None)
                    if status in (400, 401, 402, 403):
                        self._status('error')
                        self.transcriber.session.push(notice_event('error',
                            f'Transcription rejected for {self.speaker.value} (HTTP {status}). Check Deepgram credentials, credits, model and language.'))
                        break
                finally:
                    for task in jobs:
                        task.cancel()
                    if jobs:
                        await asyncio.gather(*jobs, return_exceptions=True)
                    if self._ws:
                        await self._ws.close()
                    # A new connection is a new recognition stream. End the old
                    # utterance, retaining its confirmed words, clearing partials.
                    self.transcriber.on_utterance_end()
                if not self._closed and not self._finishing:
                    self._status('reconnecting')
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 2)
        finally:
            self._closed = True
            self._running = False
            self._done.set()

    def _handle(self, data: dict) -> None:
        if data.get('type') == 'Results':
            alternative = ((data.get('channel') or {}).get('alternatives') or [{}])[0]
            text = alternative.get('transcript', '')
            if text and isinstance(data.get('start'), (int, float)) and isinstance(data.get('duration'), (int, float)):
                segment_end = data['start'] + data['duration']
                # Map provider audio time back to when that packet reached our
                # server, including local queue wait. Initial ringing/silence is
                # not counted as recognition latency. Reset mapping on reconnect.
                received_at = next((received for end, received in self._audio_clock if end + .001 >= segment_end), None)
                if received_at is not None:
                    self._result_age_ms = max(0, round((time.monotonic() - received_at) * 1000))
                    if time.monotonic() - self._last_metrics_at >= 1:
                        self._last_metrics_at = time.monotonic()
                        self._status('streaming')
                        log.info('deepgram[%s] result_age_ms=%s buffered_ms=%d dropped_ms=%d',
                                 self.speaker.value, self._result_age_ms, self._queued_bytes / 8, self._dropped_bytes / 8)
            if text and self._first_result:
                self._first_result = False
                log.info('deepgram[%s] first_text_ms=%d (includes initial silence)',
                         self.speaker.value, (time.monotonic() - (self._first_audio_at or time.monotonic())) * 1000)
            self.transcriber.on_results(text, bool(data.get('is_final')), bool(data.get('speech_final')))
        elif data.get('type') == 'UtteranceEnd':
            self.transcriber.on_utterance_end()
        elif data.get('type') == 'Error':
            raise RuntimeError('Deepgram reported a stream error')

    async def send(self, audio: bytes) -> None:
        # Deliberately no await: neither speaker can block the media receiver.
        if not audio or self._finishing or self._closed:
            return
        if self._first_audio_at is None:
            self._first_audio_at = time.monotonic()
        dropped = 0
        if len(audio) > self._max_bytes:
            dropped += len(audio) - self._max_bytes
            audio = audio[-self._max_bytes:]
        while self._queued_bytes + len(audio) > self._max_bytes:
            old, _ = self._queue.get_nowait()
            self._queue.task_done()
            self._queued_bytes -= len(old)
            dropped += len(old)
        self._queue.put_nowait((audio, time.monotonic()))
        self._queued_bytes += len(audio)
        if dropped:
            self._report_gap(dropped)

    async def keep_alive(self) -> None:
        if self._ws is None or self._closed or self._finishing or self._queued_bytes:
            return
        try:
            await self._write(self._ws, json.dumps({'type': 'KeepAlive'}))
        except Exception:
            await self._ws.close()

    async def finish(self) -> None:
        if self._finishing:
            return
        self._finishing = True
        try:
            # Let queued audio reach the provider before CloseStream. Keep the
            # receiver alive to consume trailing finals, rather than closing early.
            if self._running and self._ws is not None:
                await asyncio.wait_for(self._queue.join(), timeout=.8)
                await self._write(self._ws, json.dumps({'type': 'CloseStream'}))
                await asyncio.wait_for(self._done.wait(), timeout=1.5)
        except Exception:
            log.warning('deepgram[%s] final flush incomplete', self.speaker.value)
            self.transcriber.session.push(notice_event('warn',
                f'Final {self.speaker.value} transcription could not finish. The last words may be missing.'))
        finally:
            self._closed = True
            if self._ws:
                await self._ws.close()
            self.transcriber.on_utterance_end()
            self._status('stopped')
