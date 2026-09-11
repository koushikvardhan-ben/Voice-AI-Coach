# Live demonstration guide

## Prepare

1. Start the backend, frontend, and public tunnel using the README.
2. Verify your own test phone number in the Twilio trial console.
3. Check service configuration in Settings; make a short test call before presenting.
4. In Agents, choose Buyer discovery and save a focused instruction such as: “When price is raised, clarify the total budget before proposing a viewing. Never promise a discount.”
5. Add a short, clearly fictional demonstration property note in Knowledge base. Attach it to the profile and save.
6. Confirm microphone access and speaker labels using two distinct utterances: “I am the agent” in the browser, “I am the customer” on the phone.

## Demonstrate the required flow

- Dial the verified number; point out dialing, ringing, and connected status.
- Customer: “We're looking for a three-bedroom home near our daughter's school. We need to move within three months.”
- Agent: ask about budget and funding. Observe discovery coaching.
- Customer: “Our budget is ₹85 lakh but this one is ₹92 lakh. That's too much.”
- Show the grounded next move. Check that it acknowledges the budget gap without promising a price change.
- Customer: “My partner is available Saturday afternoon. Could we see it?”
- Show the viewing-related suggestion. Clarify that the owner's availability must be checked.
- Hang up. Show key points, objections, commitments and next steps.
- Open Call history and review the saved record. Export the transcript or summary if requested by the evaluator.

Live suggestions may differ from the examples; evaluate whether they are grounded in what was actually said. Do not present these sample utterances or practice-mode outputs as measured model performance.

## Explain the design

- Two separate audio tracks provide deterministic speaker attribution.
- Customer final utterances trigger a debounced, bounded-context coaching request.
- Saved preferences and relevant property passages are snapshotted for the call.
- The browser waits for its WebSocket before connecting Twilio.
- Customer-leg callbacks determine connected status, rather than confusing the browser leg's acceptance with the customer's answer.
- Finished calls persist to SQLite; summary delivery still proceeds if persistence fails.

If a provider or trial restriction blocks the real call, identify the exact blocker and use the assignment's clarification route. Practice mode is useful for demonstrating layout, but it does not replace the primary deliverable.
