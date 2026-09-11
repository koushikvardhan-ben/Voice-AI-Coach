export const practiceTurns = [
  ["agent", "Hi, thanks for enquiring about the three-bedroom apartment. What stood out to you about the property?"],
  ["customer", "The location is ideal for our daughter's school. We're looking to move in the next three months."],
  ["agent", "That makes sense. Have you set a budget, and will you be financing the purchase?"],
  ["customer", "Our budget is around ₹85 lakh. We've spoken to the bank, but this apartment is listed at ₹92 lakh. That's a stretch."],
  ["agent", "I understand. Let's look at the total cost and what flexibility there might be, without making any promises on price."],
  ["customer", "We'd still like to see it. My partner is free on Saturday afternoon. Could we arrange a viewing?"],
  ["agent", "I'll check the owner's availability for Saturday and send you a confirmation with the full cost breakdown."],
  ["customer", "Perfect. Please send that to me so we can review it together."],
];
export const practiceCoach = [
  { stage: "opening", sentiment: "neutral", temperature: 45, next_move: "Ask what prompted the enquiry and which location or property features matter most.", rationale: "Start with the buyer's priorities before presenting the property." },
  { stage: "discovery", sentiment: "warm", temperature: 72, next_move: "Acknowledge the school requirement, then ask about budget and financing readiness.", rationale: "A school catchment and a three-month move give you a concrete motivation and timeline." },
  { stage: "discovery", sentiment: "warm", temperature: 72, next_move: "Give the buyer room to explain their budget and whether their financing is approved.", rationale: "Financing readiness has not yet been established." },
  { stage: "objection_handling", sentiment: "neutral", temperature: 53, next_move: "Acknowledge the ₹7 lakh gap. Clarify whether ₹85 lakh includes all purchase costs before exploring alternatives.", rationale: "The concern is affordability. Speaking to a bank does not establish loan approval." },
  { stage: "objection_handling", sentiment: "warm", temperature: 65, next_move: "Offer a verified cost breakdown and ask if viewing the property would help them assess the value.", rationale: "Address the cost uncertainty without promising a discount." },
  { stage: "closing", sentiment: "hot", temperature: 88, next_move: "Confirm their preferred time on Saturday and who will attend. Check owner availability before booking.", rationale: "The buyer volunteered a viewing and included their partner, a strong readiness signal." },
  { stage: "closing", sentiment: "hot", temperature: 88, next_move: "Confirm where to send the viewing details and cost breakdown, and agree when you will follow up.", rationale: "Turn the proposed viewing into a clear next step with an owner and a deadline." },
  { stage: "closing", sentiment: "hot", temperature: 90, next_move: "Recap: check Saturday availability, send the cost breakdown, and confirm the viewing with both buyers.", rationale: "The buyer agreed to the follow-up. The viewing is pending owner confirmation." },
];
export const practiceSummary = {
  outcome: "progressed",
  key_points: ["Buyer needs a three-bedroom apartment near their daughter's school within three months.", "Budget is approximately ₹85 lakh; the asking price is ₹92 lakh.", "Buyer has spoken to a bank; loan approval is not confirmed."],
  objections: ["₹7 lakh gap between stated budget and asking price; total purchase costs need clarification."],
  commitments: ["Agent will check owner availability for Saturday afternoon and send a cost breakdown.", "Buyer and partner intend to attend a viewing, subject to confirmation."],
  next_steps: ["Check Saturday availability with the owner.", "Send the verified cost breakdown and confirm a viewing time.", "Clarify whether the budget includes taxes and other purchase costs."],
};
