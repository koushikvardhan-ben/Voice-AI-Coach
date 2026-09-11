# QuantumGandiva AI Assesment · Sales Coach

A local, standalone real-estate calling workspace. A human agent calls a real phone from the browser; the AI listens to both sides, suggests a specific next move, and summarizes the conversation after hangup.

## Workspace features

- **Agents:** create, edit, and delete buyer/vendor coaching profiles; configure instructions and transcription language; attach property knowledge; inspect the coaching flow.
- **Live call:** outbound Twilio dialer, microphone mute, hangup, customer-leg call status, elapsed time, speaker-separated streaming transcript, stage/sentiment/temperature, and actionable coaching beside the transcript.
- **Knowledge base:** import `.txt` / `.md` or paste notes; inspect and delete documents; attach them to profiles. A bounded local lexical retriever selects relevant passages for the live prompt.
- **Call history:** completed calls persist in SQLite, including transcript and structured summary. Search, filter by outcome, inspect, and export records.
- **Settings:** inspect whether required service configuration is present, reconnect the browser device, and read setup instructions. Secrets are never returned to the frontend.
- **Practice walkthrough:** a clearly labeled, scripted buyer conversation that demonstrates the UI without calling anyone or invoking an AI service. Practice calls are not saved and are **not** evidence that live telephony works.

The interface adapts the agent configuration, knowledge, call-log, and settings patterns from the supplied `Complete Voice Agents` project. See [reference mapping](docs/reference-mapping.md) for the assignment-specific scope.

## Run locally

Requirements: Python 3.13+, `uv`, Node 18+, npm, and a public HTTPS tunnel for live Twilio callbacks. Use only your available trial/free credits; this project does not provision or purchase services.

```bash
uv sync
cp .env.example .env
# Fill in backend configuration described below.
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open **http://127.0.0.1:5173/**. Without service credentials, the workspace and practice walkthrough still work when the backend is running. The live-call button remains unavailable until required configuration is present.

The frontend defaults to `http://localhost:8000`; override `VITE_API_BASE` / `VITE_WS_BASE` using `frontend/.env.example` when needed. The default backend CORS configuration supports both `localhost:5173` and `127.0.0.1:5173`.

### Configure real calling

Set these backend `.env` values:

| Variable | Purpose |
| --- | --- |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Account credential reserved for telephony integrations |
| `TWILIO_API_KEY`, `TWILIO_API_SECRET` | Voice API key pair used to sign browser access tokens |
| `TWILIO_TWIML_APP_SID` | TwiML application used for outbound browser calls |
| `TWILIO_PHONE_NUMBER` | Twilio trial caller ID in E.164 format |
| `DEEPGRAM_API_KEY` | Streaming transcription access |
| `GROQ_API_KEY` | Live coaching and post-call summarization |
| `PUBLIC_BASE_URL` | Public tunnel host, for example `your-host.ngrok-free.app` |

1. Run `ngrok http 8000` or an equivalent tunnel.
2. Set `PUBLIC_BASE_URL` to the tunnel host. Restart the backend after editing `.env`.
3. Configure the TwiML application's **Voice Request URL** to `https://<tunnel-host>/twiml/voice`, method **POST**.
4. Verify your own test destination number in the Twilio trial console.
5. Select an agent, enter the verified destination including country code, allow microphone access, and click **Start call**.
6. Answer on the real phone. Verify that the two speakers are correctly labeled, watch the next-move panel, and hang up to generate and save the summary.

A new tunnel URL requires updating both the backend setting and the TwiML app. Settings checks indicate configuration presence, not successful provider authentication. Account restrictions, credits, and number permissions must be verified with the live demonstration.

## Services and architecture

- **Twilio Voice + Media Streams:** bridges the browser and PSTN customer while `<Start><Stream track="both_tracks">` forks both audio tracks. On the parent browser leg, inbound is the agent and outbound is the customer. [Twilio stream documentation](https://www.twilio.com/docs/voice/twiml/stream).
- **Deepgram streaming:** one mu-law / 8 kHz stream per speaker, so attribution follows the audio track rather than probabilistic diarization. Both streams use the selected profile's language.
- **Groq:** structured JSON coaching and summary through a small provider abstraction. Once customer context exists, confirmed speech from either speaker queues an update. A single worker coalesces new speech without canceling generation: 0.5-second initial window, four-second minimum between requests, eight-second request deadline. Provider quotas are account/model dependent; rate limits pause requests and appear in the coach panel.
- **SQLite:** local profiles, knowledge documents, and completed calls in `data/workspace.sqlite3`. Set `WORKSPACE_DB_PATH` to choose another location. Live call state remains in memory.

```text
Browser + Twilio SDK ─── Twilio ─── customer's real phone
        │                  │
        │                  └── both audio tracks ── FastAPI ── Deepgram × 2
        │                                              │
        └── transcript / coach / summary WebSocket ─────┤
                                                       ├── Groq (rolling context)
                                                       └── SQLite (workspace + history)
```

## Project layout

```text
app/
  main.py, config.py, models.py   Application, configuration, event contracts
  db.py, calls.py                SQLite records, history, service readiness
  agents/router.py              Coaching profile CRUD
  rag/router.py, knowledge.py    Knowledge documents and bounded retrieval
  routes/token.py, twiml.py      Browser access token and outbound telephony
  ws/browser.py, media.py        Browser events and Twilio audio
  services/                     Session, STT, transcript, coach, summary, lifecycle
  prompts/                      Domain-aware coaching and summary prompts
frontend/src/
  App.jsx, styles.css            Responsive agent workspace and views
  state/useCall.js               Real calling, practice, event state, summary recovery
  lib/api.js, practice.js        API client and explicitly scripted practice content
  components/                   Original standalone panel components (retained)
docs/                           Research, architecture, scope mapping, demo guide
tests/test_workspace.py          Backend integration and lifecycle regression tests
```

### Workspace API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness |
| `GET /api/settings` | Redacted service configuration status |
| `GET, POST /api/agents` | List/create coaching profiles |
| `PUT, DELETE /api/agents/{id}` | Update/delete profiles |
| `GET, POST /api/knowledge` | List/add text documents |
| `DELETE /api/knowledge/{id}` | Delete and detach a document |
| `GET /api/calls`, `GET /api/calls/{id}` | Call summaries and full saved transcripts |
| `GET /api/token` | Browser Voice token |
| `POST /twiml/voice`, `POST /twiml/status` | Twilio webhooks |
| `WS /ws/{callId}`, `WS /media/{callId}` | Browser updates and audio input |

## Validation

```bash
uv run python -m unittest discover -s tests -v
npm run build --prefix frontend
node --test frontend/tests/*.test.js
```

Tests use a temporary SQLite database and mocked LLM responses; they do not consume credits or call phone numbers. They check CRUD/persistence, profile context, knowledge attachment/deletion, speaker separation, language selection, single-active-call enforcement, callback ordering, summary idempotence, and summary delivery after a database failure.

## Known limitations

- Live telephony must still be demonstrated with configured Twilio/Deepgram/Groq accounts and a verified test number. A build or passing mocked test is not that demonstration.
- This is a trusted local, single-user prototype. Workspace APIs and WebSockets do not yet require authentication; webhook signature validation and tunnel path restrictions are production work. Do not expose the full workspace as a public service.
- No inbound calling, IVR, autonomous AI speaker, bulk autodialing, multi-user support, CRM execution, or synthesized voice selection. The human makes the call and receives private coaching.
- Twilio trial accounts play a recorded announcement to the called party before the audio bridges, which adds roughly 2–3 seconds between the recipient answering and hearing the agent. This is a trial-account limitation (removed by upgrading Twilio), not an application delay. The announcement may also appear briefly in the transcript. Verify the speaker mapping on the actual test call before the demo.
- Transcription and coaching latency have a floor set by the network round-trip between this machine and the US-hosted providers (Twilio, Deepgram, Groq). Running locally from a distant region adds unavoidable delay; hosting the backend near the providers is the effective fix. The live transcript shows the measured per-speaker "text delay" so this can be observed.
- Call state and audio are not durable during an active call. Refreshing the page can end the browser call. A server crash can lose an unfinished call. Each speaker has an independent two-second audio buffer for startup/reconnection. Longer outages or ambiguous failed writes can still lose audio, with a visible notice.
- Completed calls are stored locally; no audio recording is made by this prototype. Exports contain conversation text and should be handled accordingly.
- Summary recovery polls saved history after disconnect. If processing fails or exceeds the recovery window, the UI reports the missing summary instead of fabricating one.
- Knowledge retrieval is bounded lexical matching, not embeddings; it may miss semantically related passages. Model output may still be incorrect and is guidance for the human agent.
- There is no guarantee that a particular provider's free credits or limits will support a given session length. Monitor your accounts and choose models/languages available to your account.

## Assignment documents

- [Domain research and prompt design](docs/domain-research-and-prompt-design.md)
- [Production system design](docs/system-design.md)
- [Reference feature mapping](docs/reference-mapping.md)
- [Live demonstration guide](docs/demo-guide.md)

Confidential candidate evaluation workspace. No external publication is part of this implementation.

## Live transcription tuning

See [transcription troubleshooting](docs/transcription-latency.md). Confirmed segments now update the transcript immediately using a stable ID and revision; the UI also displays provider partials as they arrive. The two audio senders operate independently, buffer short interruptions, and consume trailing finals at hangup. Browser update connections retry and restore confirmed turns after brief disconnects.

In **Agents → Agent**, choose the language actually spoken: **English · India** for English, **Hindi + English · Multilingual** for code-switching, or **Hindi** for predominantly Hindi. The saved profile overrides the backend default. Optional **Names to recognize** supplies short locality/property-name hints to Nova-3. Save changes before the next call.

After updating the code, restart the manually managed backend and refresh the frontend between calls. No server restart or phone call is performed by the regression tests.
