# Merchant Settlement and Dispute Agent

An AI agent for a payments company, built for the Paytm Build for India AI Hackathon. It does two jobs for small shops:

1. **Payout check.** A shop sells ₹20,000 but only ₹17,000 reaches the bank. The agent adds up the day's records, explains every rupee of the gap in plain words, and raises a support ticket if something is actually wrong.
2. **Dispute agent.** When a customer disputes a payment, the shop has a deadline to send proof. The agent collects the proof and replies on its own, but only if 7 safety checks all pass. Anything unclear goes to a person, earliest deadline first.

The two jobs are one pipeline: when a payout check finds a chargeback, it hands it to the dispute agent.

**All data is made up. Paytm systems and support tickets are simulated. Fee rates are demo values, not Paytm pricing.**

## The app

Four tabs:

- **Payout check.** Pick a shop and a day. You get one plain answer first, then the numbers, then where the money went.
- **Disputes.** The queue in deadline order, and for each dispute the customer's claim, the 7 safety checks with ticks and crosses, and the drafted reply or the note for the person who picks it up.
- **Results.** How well both jobs work on the test data, the trick cases, and what is not tested yet.
- **Audit log.** Every step the agent took, for every payout day and dispute.

## The 7 safety checks

The agent replies on its own only if every one of these passes. An AI model can only say no to a reply, never force one through.

1. The evidence checklist is complete.
2. The amount is under the limit (₹5,000 in this demo).
3. There is enough time before the deadline for a person to step in (48 hours in this demo).
4. The records agree with each other and with the dispute.
5. Every claim in the reply cites a record that exists.
6. The customer's own text contains nothing that tries to instruct the agent.
7. The AI model raises no objection.

The ₹5,000 limit and the 48-hour buffer are demo choices, not Paytm rules.

## Results

Every number below was measured by running the code on the made-up data, with the offline stand-in (no AI model) on 21 Nov 2026. The app shows the same figures with their labels.

**Payout check:** 84 shop-days, 18 with a planted error.
- 18 of 18 errors caught.
- 0 false alarms on the 66 clean days.
- The amount owed was worked out correctly on all 18.
- 13 chargebacks were handed to the dispute agent: 3 replied to, 10 sent to a person.

**Dispute agent:** 57 disputes.
- 20 replied to by the agent, 37 handed to a person.
- 0 of the 20 replies were wrong.

**Trick cases:** 32 cases built to find gaps in my own rules. I wrote down what I expected before running them. 6 are gaps and 2 are controls, 4 cases each.
- **All 24 gap cases got past the agent.** It replied when a person should have. Examples: the delivery proof is for a different address, the same proof is reused on another order, part of the money was already refunded.
- All 8 control cases were caught correctly.
- Every result matched my prediction, so these are known gaps, not surprises.

The zeros above only cover the situations the rules were written for. The trick cases show what happens outside them. The offline stand-in follows the rules, so these results describe the rules, not an AI model.

**One more measured result:** the check that every number in an explanation comes from the records rejected 5 of 16 honest sentences I wrote (for example "GST at 18%" or a rounded amount). It is strict by design, and it means a real AI model's text would be rejected more often than it should be.

## What is not tested yet

Nothing on this list has a number, because none can be honestly claimed yet. The Results tab lists each one with how to test it.

- How a real AI model (Gemini) behaves on the same cases, including the 24 gap cases.
- Whether "complete evidence" actually predicts a won dispute.
- How many escalations a real support team clears per day.
- Why shop owners would say an explanation did not make sense. There are no real users yet.
- Hindi and Tamil explanation quality. The app offers English only.
- Cost per case when a real model is used.
- How the app performs when hosted.
- How realistic the made-up scenario mix is.

## Run it on your computer (Windows Command Prompt)

```
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
streamlit run app.py
```

No API key is needed. With none set, the app runs entirely offline. It opens on a saved measurement that is only used while it is still true. If the rules, data or thresholds change, the app measures again from scratch.

To run the tests: `python -m pytest tests -q` (97 tests).

If you change the rules or thresholds, rebuild the saved measurement with `python snapshot.py`. A test fails until you do.

## How it is built

- **Payout pipeline:** reconcile the day, hand any chargeback to the dispute agent, look for errors, write the explanation, check every number in it, draft tickets.
- **Dispute pipeline:** read the notice, collect the records, assess the case, draft a reply, verify it, run the 7 checks, then reply or hand to a person.
- **AI model layer:** Gemini first, then Groq, then an offline stand-in, all on free tiers. Answers are cached.
- **Every figure in the app** is labelled **Measured** (with the mode and date that produced it), **Assumption** (with its source) or **Needs testing** (no number shown).
- **Stack:** Python 3.11, Streamlit, LangGraph, SQLite, pandas, pytest.

## Folders

- `app.py` and `screens/`: the app.
- `disputes/` and `payouts/`: the two pipelines and their metrics.
- `product/`: the assumptions, the not-tested list and the guardrail measures.
- `snapshot/` and `snapshot.py`: the saved measurement and the check that it is still true.
- `tests/`: the test suite.
