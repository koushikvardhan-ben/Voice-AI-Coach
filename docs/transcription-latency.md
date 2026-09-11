# Live transcription: fixes and verification

## What was found in the code

1. `DeepgramTrack.send()` silently returned when its socket was not yet connected. That discarded words during startup and reconnects.
2. The Twilio receive loop awaited network writes to each provider socket. A slow agent stream could delay reception and forwarding of customer audio too.
3. Confirmed segments stayed in a local buffer until `speech_final` or `UtteranceEnd`. This delayed canonical transcript/coaching updates even when the provider had already confirmed text. Interim text was supported, so this was not the only possible source of display lag.
4. At hangup, the provider socket was closed immediately after sending `CloseStream`, without waiting for the trailing final results.
5. The browser did not reconnect its live-update channel. Transcript following used smooth scrolling on frequent updates.

## Current behavior

- Recognition connections open during dialing, before the first Media Streams packet arrives. This removes the provider handshake from the first-speech path when dialing gives it enough time to complete.
- Incoming mu-law / 8 kHz / mono audio enters separate per-speaker queues. Their senders and receivers run concurrently. No transcoding or batch STT is introduced.
- Up to two seconds of audio per track is retained while a connection opens or reconnects. The oldest queued audio is dropped after that bound so a long outage cannot build an ever-growing delay. Gaps are reported. An ambiguously failed write is not replayed, avoiding duplicated words.
- Partial words appear immediately when Deepgram provides them. Every `is_final` segment enters the canonical transcript immediately. Later confirmed segments within that utterance replace the same row with a higher revision. Older queued events cannot overwrite a newer replay snapshot.
- Endpointing defaults to 200 ms. This controls silence detection, **not a guarantee of 200 ms end-to-end latency**. Utterance-end detection remains at 1,000 ms, but no longer gates confirmed transcript publication.
- Smart formatting defaults off; punctuation remains on. The previous configuration already used `no_delay=true`, so formatting is a tuning choice rather than proof of the observed delay's cause.
- Both streams drain in parallel at hangup. Receivers remain alive for trailing final results within a bounded timeout. An incomplete final flush produces a notice.
- Each speaker's STT connection state is visible in the transcript panel. Browser event sockets retry up to five times and replay saved in-memory turns and partials after reconnecting.
- The frontend follows new words without scrolling animation. Customer-leg callbacks remain the server's answer-status authority. A guarded SDK ringing-without-early-media → accept transition updates the frontend sooner when available; late ringing callbacks cannot regress an already connected call.

## Accuracy settings

Select the actual language in the **saved agent profile**. It takes precedence over `DEEPGRAM_LANGUAGE`:

| Spoken conversation | Profile language |
| --- | --- |
| English with an Indian accent | `en-IN` |
| Hindi mixed with English | `multi` |
| Predominantly Hindi | `hi` |

Keep the current English setting when the language is unknown rather than guessing. Nova-3 supports English (India), Hindi, and multilingual English/Hindi; see [Deepgram models and languages](https://developers.deepgram.com/docs/models-languages-overview).

For names that are consistently misheard, add a few exact spellings to **Names to recognize**, for example a locality or property name. These are optional Nova-3 [keyterm hints](https://developers.deepgram.com/docs/keyterm), not replacement text or a guarantee of recognition. Avoid a long generic vocabulary list. The UI/API bounds the hints to 20 entries, 40 characters per entry, and 200 characters total. Models other than Nova-3 do not receive this model-specific parameter.

Provider-confirmed text is retained as received. An LLM does not rewrite the live transcript, which would add delay and risk inventing speech. Telephone bandwidth, microphone noise, overlapping speech, accent and network conditions can still affect recognition.

## Configuration

```dotenv
STT_ENDPOINTING_MS=200
STT_AUDIO_BUFFER_SECONDS=2
STT_SMART_FORMAT=false
```

These values have safe defaults and can be overridden in the backend `.env`. Restart the backend after configuration/code changes and refresh the frontend between calls. Existing profiles retain their saved languages; no profile language or service credentials are changed automatically.

## Tests and actual-call check

```bash
uv run python -m unittest discover -s tests -v
node --test frontend/tests/*.test.js
npm run build --prefix frontend
```

The tests simulate delayed connection setup, a blocked speaker sender, bounded queue overflow, reconnection, trailing results at shutdown, partial/final handling, websocket replay, and delayed call-status events. They use fake sockets and no provider credits. They establish local pipeline behavior, **not a measured improvement in real-call word accuracy or end-to-end latency**.

To measure the actual service path:

1. Save the correct profile language and any short name hints.
2. Make your normal verified-number test call. Watch both STT status indicators; if one reconnects or reports unavailable, investigate that track's connection/authentication first.
3. Have each speaker read a short known sentence separately, including a price, locality, and appointment time. Check the displayed partial words before pausing, then the final words afterward.
4. Compare the reference sentence to the final transcript. Note substitutions, missing words and added words. Repeat the same utterances under the same microphone/network conditions before drawing an accuracy conclusion.
5. Verify that a short network interruption recovers, and that the final spoken sentence is included after hangup.

Backend logs include `connect_ms` for each STT handshake and `first_text_ms` from the first received audio frame. **The latter includes initial silence/ringback; it is not per-word STT latency.** No transcript text or API keys are added to these logs.

The transcript panel now also shows an approximate `text delay` from `result_age_ms`: the time between receipt of the last audio packet covered by a provider result and processing that result on the backend. It includes local buffering and provider/network processing, excludes initial ringing/silence, and does not include the phone-to-server path or browser rendering. It is a segment-boundary measurement, not a word-accuracy score or full mouth-to-screen measurement. `buffered_ms` and `dropped_ms` are also logged. Provider audio timestamps reset on reconnect, so their timing map resets too.

## Unexpected call endings and stream recovery

The previous media receiver called whole-call teardown whenever its audio WebSocket closed or received a `stop` event. This could mark a still-active telephone call ended and generate its summary prematurely. Media transport loss now preserves the call session and attempts to restore only the audio fork. It never updates the call's TwiML or sends a telephone hangup request. Actual terminal customer-leg callbacks, a Twilio SDK closed-call event, or a REST confirmation that the parent call ended drive finalization.

- The browser allows up to 30 seconds for Twilio signaling reconnection. Recoverable SDK errors display their error code and preserve call controls. The reconnect-device action is guarded while a call is active.
- Stream status callbacks and SDK connection events are retained in the saved call's `diagnostics`; `end_reason` records the finalization trigger, not an inference about which person hung up.
- Twilio status callbacks return immediately while STT flushing and summary generation run asynchronously. Summary generation has a 20-second deadline; a timeout still saves the confirmed transcript. Saved duration stops at the end event rather than including summary-generation time.
- An interrupted media stream gets up to three recovery attempts. Recovery uses `TWILIO_AUTH_TOKEN` to check the parent call and create a replacement `both_tracks` Stream. Audio during the outage cannot be recovered. If recovery fails, a visible notice leaves the call under the user's control. A backend restart loses in-memory state and cannot use this recovery path.
- Run real-call tests without backend auto-reload, and refresh the frontend only between calls:

  ```bash
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```

  `--reload` restarts the backend when Python files change; frontend HMR/page refresh can recreate the Twilio Device. Either is disruptive during a live call.

During the September 11 investigation, the latest Twilio call records contained `31921` (server-side Media Streams WebSocket close) five seconds before call completion, and `15003` (a warning HTTP response to the call progress callback). These establish a transport/callback problem; they do not identify which side ended the phone call. No phone call was placed as part of automated verification.

Provider references: [Media Streams stop events](https://www.twilio.com/docs/voice/media-streams/websocket-messages), [WebSocket close error 31921](https://www.twilio.com/docs/api/errors/31921), [callback warning 15003](https://www.twilio.com/docs/api/errors/15003), [SDK signaling reconnection timeout](https://www.twilio.com/docs/voice/sdks/javascript/twiliodevice), and [restarting a Stream through REST](https://www.twilio.com/docs/voice/api/stream-resource).

Relevant provider behavior: [interim versus finalized results](https://developers.deepgram.com/docs/understand-endpointing-interim-results), [utterance-end timing](https://developers.deepgram.com/docs/utterance-end), [smart formatting and no-delay](https://developers.deepgram.com/docs/smart-format), and [CloseStream final results](https://developers.deepgram.com/docs/close-stream).
