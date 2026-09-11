# Live coaching updates

The previous scheduler canceled its existing debounce task for every customer final.
That same task also awaited the LLM, so later speech could cancel a request already
generating an answer. Continuous speech could repeatedly reset the timer or cancel
generation. A 12-second request interval added further delay. Invalid model output
could silently reuse the previous suggestion, and the UI timestamp omitted seconds.

## Current behavior

- The first confirmed customer context starts a fixed 500 ms coalescing window.
  More speech does not restart it. Subsequent agent speech also triggers coaching,
  allowing the coach to recognize that the agent has already asked its question.
- One worker owns all coaching requests for a call. It finishes its current request
  while additional speech marks the conversation dirty. Its next request snapshots
  the newest confirmed transcript, rather than replaying a backlog of turns.
- Requests start at least four seconds apart and have an eight-second deadline.
  A failed request gets one automatic retry without further speech. Rate limits
  respect Retry-After (15 seconds if absent); new speech cannot erase that backoff.
  SDK automatic retries are disabled so the application controls this behavior.
- The prompt includes the previous action and explicitly checks whether the agent
  already asked it or the customer answered it. It reevaluates stage based on the
  conversation, including land details and price expectations as discovery. A still
  relevant action can remain the same; text is not changed just to look active.
- Invalid, empty, or truncated responses are reported as failed updates. They never
  masquerade as a fresh default card or refresh the old card's timestamp. The server
  owns timestamps and source revisions. Older reconnect events cannot overwrite newer
  suggestions or generation status.
- The panel shows queued, preparing, provider rate-limit and error states, plus update
  age in seconds. On hangup, it labels the last suggestion as historical.

The configured Groq GPT-OSS model uses low reasoning effort. Its completion allowance
is at least 1,024 tokens because that allowance includes reasoning as well as the JSON
answer; the old 350-token cap risked truncation. Other models retain the configured
output allowance and are not sent a GPT-OSS-specific reasoning option. See
[Groq's completion parameters](https://console.groq.com/docs/api-reference) and
[SDK timeouts and retries](https://github.com/groq/groq-python).

## Validation

Run `uv run python -m unittest discover -s tests -v`,
`node --test frontend/tests/*.test.js`, and `npm run build --prefix frontend`.
Regression tests simulate continuous speech during generation, agent follow-ups,
timeouts, rate limits, hangup cancellation, incomplete JSON, and stale browser replay.
These tests use fake model responses and no provider credits.

Restart the backend and refresh the frontend **between calls**. In a verified-number
call, first describe land size and amenities, then give a price, then raise a pricing
objection. Check that the card progresses from discovery to the latest issue and
does not repeat questions the agent has already asked. Watch the generation status
and update age; backend logs contain `coach updated`, source revision and request
`latency_ms`. Four seconds is a request-spacing floor, not a guaranteed full update
latency. Actual timing and semantic quality still depend on model/network conditions
and available provider quota.
