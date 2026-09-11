# Reference adaptation

The provided local `Complete Voice Agents` frontend was reviewed alongside its agent, telephony, knowledge, call-log, and campaign modules. Its dark navy surfaces, lavender/mint accents, persistent sidebar, agent list/detail configuration, and workspace settings informed this implementation. No separate ElevenLabs screenshot was present in the conversation; this is an adaptation, not a verified pixel match.

[ElevenLabs' agent platform overview](https://elevenlabs.io/docs/eleven-agents/overview) describes configuration, deployment, and monitoring as related agent workflows. This workspace uses that organization for the assignment's **human sales coach** context.

| Reference capability | Sales Coach implementation |
| --- | --- |
| Agent manager | Persisted buyer/vendor profile creation, editing, deletion, search, filtering |
| Persona/system prompt | Saved coaching preferences supplement the domain-aware system prompt |
| Language configuration | Selected language passed to both streaming STT tracks |
| Knowledge collections and ingestion | Text/Markdown documents attached to agents; bounded passage retrieval |
| Calling/testing interface | Real outbound browser calling plus a separate scripted practice walkthrough |
| Call logs/transcripts | Searchable persistent history, outcome filtering, full transcript/summary review, exports |
| Settings and connection checks | Redacted service configuration checks and browser-device reconnect |
| Stage/sentiment/next move | Live coaching beside the streaming transcript |
| Post-call intelligence | Key points, objections, commitments, next steps and outcome |
| Autonomous synthesized agent voices | Human speech carries the conversation; the AI is silent as required by the assignment |
| Campaign autodialing, CRM tools, inbound routing | Outside this prototype's one-call-at-a-time assignment scope; not implemented or represented as working features |
| Developer lab | The Settings view exposes configuration status; backend OpenAPI at `/docs` exposes the actual API |

Backend code stays in a single FastAPI service. New `agents/`, `rag/`, `calls.py`, and `db.py` modules follow the reference's separation of concerns while retaining the existing project's `routes/`, `ws/`, `services/`, and `prompts/` modules.

## What remains to validate

The production frontend build and backend tests are runnable without providers. The actual live demonstration needs configured service accounts, a public tunnel, microphone permission, and a verified destination number. Scripted practice does not validate STT or LLM output.
