"""Publish partial words immediately and upsert confirmed segments without waiting
for silence. Only provider-confirmed text enters the saved transcript/LLM context.
"""
from __future__ import annotations

import uuid
from typing import Callable
from app.models import Speaker, TranscriptTurn, transcript_event
from app.services.session import CallSession


class TrackTranscriber:
    def __init__(self, session: CallSession, speaker: Speaker,
                 on_final: Callable[[TranscriptTurn], None] | None = None) -> None:
        self.session = session
        self.speaker = speaker
        self.on_final = on_final
        self._active_turn: TranscriptTurn | None = None
        self._interim = ""

    def on_results(self, transcript: str, is_final: bool, speech_final: bool) -> None:
        text = transcript.strip()
        if is_final:
            if text:
                if self._active_turn is None:
                    self._active_turn = TranscriptTurn(
                        id=uuid.uuid4().hex, speaker=self.speaker, text=text,
                        is_final=True, seq=self.session.next_seq(), revision=1)
                    self.session.append_final(self._active_turn)
                else:
                    self._active_turn.text += " " + text
                    self._active_turn.revision += 1
                self.session.push(transcript_event(self._active_turn))
                if self.on_final is not None and not self.session.closing:
                    self.on_final(self._active_turn)
            self._emit_interim("")
        else:
            # Never repeat already-confirmed words in the partial line.
            self._emit_interim(text)
        if speech_final:
            self.on_utterance_end()

    def on_utterance_end(self) -> None:
        self._active_turn = None
        self._emit_interim("")

    def _emit_interim(self, text: str) -> None:
        if text == self._interim:
            return
        self._interim = text
        if text:
            self.session.interim[self.speaker] = text
        else:
            self.session.interim.pop(self.speaker, None)
        # Empty events explicitly clear stale partials in the browser.
        self.session.push(transcript_event(TranscriptTurn(
            id=f"interim-{self.speaker.value}", speaker=self.speaker,
            text=text, is_final=False, seq=0)))
