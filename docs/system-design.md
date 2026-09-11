# System Design

How the prototype is built today, and how it would evolve into a production
real-time call-intelligence platform.

---

## 1. Prototype architecture

Single FastAPI service (HTTP + WebSockets) + a single React page. Active call state is in-memory, one call at a time. Coaching profiles, knowledge documents, and completed transcript/summary records persist in local SQLite.

```
┌──────────────────────────── Browser (React + Vite) ────────────────────────────┐
│  Agent workspace · Dialer · Transcript · Coach · History              │
│  @twilio/voice-sdk Device            useCall() hook (Device + WS + state)         │
└───────┬───────────────────────────────────────────────────┬─────────────────────┘
        │ GET /api/token                                      │ WS /ws/{callId}
        │ device.connect({PhoneNumber, CallId, AgentId})                        │ (status/transcript/
        ▼                                                     │  coach/summary)
   ┌─────────────┐   TwiML request (POST /twiml/voice)   ┌────┴───────────────────────┐
   │   Twilio    │ ────────────────────────────────────▶ │        FastAPI backend      │
   │   Voice     │   <Start><Stream both_tracks>          │                             │
   │             │   <Dial callerId>{To}</Dial>           │  routes/  token, twiml      │
   │  bridges    │ ◀──────────────────────────────────── │  ws/      media, browser    │
   │  agent ↔    │                                        │  services/                  │
   │  customer   │   WS /media/{callId} (mu-law/8k,       │    session (in-mem registry)│
   │             │ ───both tracks──────────────────────▶  │    deepgram_client ×2       │
   └─────┬───────┘                                        │    transcript (assembly)    │
         │ PSTN                                           │    coach (debounce+Groq)    │
         ▼                                                │    summary · lifecycle · llm│
   Customer's phone (verified)                            └───────┬───────────┬─────────┘
                                                                  │           │
                                                    Deepgram /v1/listen   Groq chat
                                                    (2 streams: agent,    (coach + summary,
                                                     customer)             JSON mode)
```

### Request/data flow

1. Browser fetches a **Voice Access Token** (`/api/token`), registers a Twilio `Device`.
2. On **Dial**: browser mints a `callId`, opens **`/ws/{callId}`** (so the session
   exists first), then `device.connect({PhoneNumber, CallId, AgentId})`.
3. Twilio calls **`/twiml/voice`**; backend returns `<Start><Stream track="both_tracks">`
   (with the `callId` as a `<Parameter>`) + `<Dial>` to the customer.
4. Twilio bridges the two humans and forks both legs to **`/media/{callId}`**.
   `inbound`=agent, `outbound`=customer → **speaker labels without diarization**.
5. Each track streams to its own **Deepgram** socket; interim/`speech_final` events
   become clean turns, pushed to the browser over `/ws`.
6. Confirmed speech from either speaker queues the **coach**, once customer context exists; Groq returns coach JSON
   → pushed to `/ws`.
7. Hang-up (media `stop` / dialed-leg status callback / socket drop) → idempotent
   **teardown** → Groq **summary** → flushed to `/ws` → tasks cancelled, session dropped.

### Key design choices

- **Passive coach, not a bot**: the AI never joins the audio path, so `<Start><Stream>`
  (a copy) is used, not `<Connect><Stream>` (which replaces a leg). No TTS.
- **`callId` correlation** across three independent connections (browser WS, TwiML
  stream, media WS), created lazily under a lock by whichever arrives first.
- **One writer to the browser**: a single send-loop drains a bounded per-call queue;
  under pressure only disposable *interim* transcripts are dropped.
- **Coaching scheduling** lives in `coach.py`: fixed initial 0.5-second coalescing window,
  four-second minimum request spacing, eight-second deadline, small transcript window
  and a model-maintained running summary. New speech never cancels an in-flight request.
  Requests run serially with provider rate-limit backoff; faster scheduling does not
  guarantee a fixed update latency under account quotas.
- **Provider seams**: `LLMClient` Protocol wraps Groq; Deepgram is reached via a thin
  `DeepgramTrack`; Twilio TwiML/token are isolated in `routes/`. Each is swappable.

### Concurrency model (per call)

`asyncio` tasks: the media receive loop (decode + forward only), two Deepgram receive
loops (with reconnect), a keep-alive tick, the browser send-loop, and short-lived coach
debounce tasks. All are tracked on the session and cancelled at teardown.

---

## 2. Production evolution

The prototype is intentionally a single process with in-memory state. Productionising
means removing the "one process, one call" assumptions without changing the core flow.

```
                       ┌───────────── Load balancer / API gateway ─────────────┐
   Browser (many) ───▶ │  Auth (OIDC)  ·  rate limiting  ·  TLS                 │
                       └───────┬───────────────────────────────┬───────────────┘
                               ▼                                ▼
                    ┌───────────────────┐            ┌────────────────────────┐
                    │  API service (N)  │            │  Media/STT workers (N)  │
                    │  token, twiml,    │            │  Twilio Media Streams   │
                    │  browser WS       │            │  → Deepgram             │
                    └───────┬───────────┘            └───────────┬────────────┘
                            │      ┌─────────────────────────────┘
                            ▼      ▼
                   ┌──────────────────────┐   pub/sub (call events)   ┌──────────────┐
                   │  Redis / NATS        │◀─────────────────────────▶│ Coach workers│
                   │  session state + bus │                           │ (LLM calls)  │
                   └──────────┬───────────┘                           └──────────────┘
                              ▼
             ┌────────────────────────────┐     ┌──────────────────────────┐
             │ Postgres (calls, turns,     │     │ Object store (recordings) │
             │ summaries, users, orgs)     │     │ + analytics warehouse     │
             └────────────────────────────┘     └──────────────────────────┘
```

### What changes, and why

1. **Externalise session state** → Redis (or NATS KV). Any API node can serve a call's
   browser WS while a media worker handles its audio. A **pub/sub bus** carries
   transcript/coach/summary events between workers and the browser-facing node, so the
   `/media` producer and `/ws` consumer no longer need to be the same process.
2. **Scale out & separate concerns**: split the **API/WS tier** from **media/STT
   workers** (CPU/network-heavy) and **coach workers** (LLM-bound). Scale each on its
   own signal (concurrent calls vs LLM QPS).
3. **Multi-tenant + auth**: OIDC/SSO for agents, per-org isolation, per-agent Twilio
   identities, RBAC, and audit logging. Consent/recording notices per jurisdiction.
4. **Persistence & analytics**: Postgres for calls/turns/summaries/users; recordings to
   object storage; a warehouse for coaching-quality metrics, objection frequencies,
   stage-conversion funnels, and agent leaderboards. Feed this back into prompt tuning.
5. **LLM cost & reliability at scale**: move to paid Groq/other tiers with real quotas;
   add **prompt caching** for the static system prompt, **semantic batching**, a
   **fallback provider** behind the existing `LLMClient` seam, and per-org token budgets
   + backpressure. Consider a smaller fine-tuned model for stage/sentiment and a larger
   one only for `next_move`.
6. **STT robustness**: reconnect/failover, per-region Deepgram, on-the-fly language
   detection (Hinglish → `multi`), redaction of PII in transit, and a batch re-transcribe
   pass post-call for a cleaner archived transcript.
7. **Concurrency & isolation**: many simultaneous calls; per-call task supervision,
   circuit breakers around Deepgram/Groq, graceful shedding, and idempotent teardown
   already modelled here — promoted to a durable workflow (e.g. Temporal) so a crashed
   worker still finalizes the summary.
8. **Observability & quality**: structured logs, tracing (call as a span tree), metrics
   (STT lag, coach latency, 429 rate, tokens/call), plus a **human feedback loop** —
   agents thumbs-up/down each suggestion to build an evaluation set and drive prompt/model
   iteration.
9. **Telephony hardening**: leave the trial (verified-number limit, trial greeting),
   real DID provisioning, call recording with consent, DTMF/transfer, and possibly a
   carrier-agnostic media layer behind the current Twilio seam.

### What stays the same

The heart of the system carries straight over: **passive both-tracks forking for
free speaker separation**, **track-labelled streaming STT**, the **debounced,
window+running-summary coaching economy**, the **strict JSON coach/summary contracts**,
and the **provider seams** (`LLMClient`, `DeepgramTrack`, `routes/`). Production is
mostly about distributing state and adding tenancy, durability, and observability around
that same core.


## Workspace persistence and configuration

`app/db.py` stores JSON records in a local SQLite table keyed by record kind and ID. Profiles and knowledge survive restarts. Completed calls are saved before their summary is delivered, with a separate error path that still delivers the summary if saving fails. Browser recovery can fetch the saved call after the live event channel disconnects.

A profile and its attached notes are snapshotted when Twilio requests the dialing instructions. Edits during a call therefore do not alter that call's model context. Both STT tracks use the snapshot's language. A bounded lexical retriever selects short passages from the notes for each rolling coaching prompt. This avoids an embeddings service in the prototype, but needs relevance evaluation before production.

The SQLite store uses synchronous short operations. Large call histories and long transcript serialization would eventually block the event loop; the first storage change would move writes off the realtime worker and make finalization a durable, idempotent job. The present completed-call-only persistence cannot recover unfinished calls after a server crash.

The public tunnel should eventually expose only authenticated Twilio webhook/media routes. Before production, add request-signature verification, browser authentication, origin validation, call ownership checks, and authorization on transcript/history APIs. The current local prototype must not be published as an open workspace.
