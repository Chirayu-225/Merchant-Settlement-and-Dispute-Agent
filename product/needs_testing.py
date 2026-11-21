"""Things this project cannot honestly claim yet. The app shows this list, and any figure
that depends on one of these items either carries its Assumption label or shows no number.

status:
  flagged          nothing measured; no number is shown anywhere
  partly measured  a narrower question was measured offline; what it cannot answer is stated
"""

NEEDS_TESTING = [
    {"id": "number_check_false_rejections",
     "title": "Number-check false rejections on legitimate figures",
     "status": "partly measured",
     "what": "How often the number check rejects an honest sentence.",
     "measured_so_far": "Offline, on a hand-written probe set of legitimate sentences "
                        "(the Results tab shows the live result and which probes fail).",
     "still_flagged": "How often real model text is rejected. That needs Gemini output on real "
                      "explanation requests, in English, Hindi and Tamil.",
     "how_to_test": "Run compare_modes.py with a Gemini key and read 'llm texts rejected by number check'."},
    {"id": "gemini_vs_offline",
     "title": "Gemini versus the offline stand-in on the same cases",
     "status": "flagged",
     "what": "Whether decisions, assessments and explanations differ on identical inputs, "
             "including the six adversarial gaps.",
     "measured_so_far": "Nothing. Every number in this app so far comes from the offline stand-in, "
                        "which mirrors the rules and ignores statement text.",
     "still_flagged": "All of it. The adversarial results show the rules only.",
     "how_to_test": "python compare_modes.py (needs GEMINI_API_KEY). It writes data/mode_comparison.json."},
    {"id": "complete_evidence_proxy",
     "title": "'Complete evidence' as a proxy for winning",
     "status": "flagged",
     "what": "The north star proxy counts rupees contested on time with complete evidence. Whether "
             "complete evidence predicts a won dispute is unknown.",
     "measured_so_far": "Nothing. On synthetic data the label and the check agree by construction.",
     "still_flagged": "The link between the proxy and real outcomes, which arrive weeks later.",
     "how_to_test": "Needs real disputes with outcomes. Compare win rate for complete versus incomplete evidence."},
    {"id": "support_capacity",
     "title": "Support capacity per day",
     "status": "flagged",
     "what": "How many escalated disputes a support team really clears per day. It decides how "
             "many escalations miss their deadline.",
     "measured_so_far": "Nothing. It is written down as a guess in product/assumptions.py.",
     "still_flagged": "The real number, and whether it is constant across a day and a week.",
     "how_to_test": "Ask a support team, or time ten real cases end to end."},
    {"id": "feedback_reasons",
     "title": "Why shop owners say an explanation did not make sense",
     "status": "flagged",
     "what": "The mix of reasons behind 'no': number looks wrong, too long, confusing term.",
     "measured_so_far": "Nothing. There are no real users. The button works and stores answers "
                        "(tests/test_product_events.py), but demo clicks are not user data.",
     "still_flagged": "All of it.",
     "how_to_test": "Put the Payout check tab in front of five real shop owners and read the reasons."},
    {"id": "offline_deploy_no_keys",
     "title": "Offline deploy with no keys",
     "status": "partly measured",
     "what": "Whether the app works when hosted with no API keys.",
     "measured_so_far": "The app boots from a fresh folder with no keys and all four tabs render "
                        "without errors (tests/test_boot.py).",
     "still_flagged": "The hosted environment itself: package install, a writable database path, "
                      "cold-start time and memory on Streamlit Community Cloud.",
     "how_to_test": "Deploy it, open the link in a private window, and click through all four tabs."},
    {"id": "llm_cost_per_case",
     "title": "LLM cost per case",
     "status": "flagged",
     "what": "Tokens and rupees per dispute and per payout explanation.",
     "measured_so_far": "Model calls per case (zero offline). The gateway does not record tokens.",
     "still_flagged": "Cost. No figure is shown.",
     "how_to_test": "Add token counts to the gateway, run a Gemini batch, multiply by the current price."},
    {"id": "merchant_behaviour",
     "title": "Merchant deflection and recovery capture",
     "status": "flagged",
     "what": "Whether owners who see the explanation stop raising tickets on clean days and raise "
             "them on error days.",
     "measured_so_far": "Nothing. The metrics are defined and unit-tested on synthetic events only.",
     "still_flagged": "All of it. No funnel numbers are shown anywhere.",
     "how_to_test": "Ship to real merchants with the events in product/events.py switched on."},
    {"id": "vernacular_quality",
     "title": "Hindi and Tamil explanation quality",
     "status": "flagged",
     "what": "Whether model-written Hindi and Tamil are correct and natural.",
     "measured_so_far": "Nothing. The number check was probed with Devanagari and Tamil digits only.",
     "still_flagged": "Wording quality. Needs a native speaker's review.",
     "how_to_test": "Run compare_modes.py with a Gemini key and have a native speaker read the output."},
    {"id": "scenario_mix",
     "title": "Realism of the synthetic scenario mix",
     "status": "flagged",
     "what": "The share of disputes that are clean, missing evidence and so on is the generator's choice.",
     "measured_so_far": "Nothing. Per-day and per-100 figures inherit this mix.",
     "still_flagged": "The real mix.",
     "how_to_test": "Compare with the real distribution of dispute reasons and evidence quality."},
]

REQUIRED_IDS = {"number_check_false_rejections", "gemini_vs_offline", "complete_evidence_proxy",
                "support_capacity", "feedback_reasons", "offline_deploy_no_keys"}
