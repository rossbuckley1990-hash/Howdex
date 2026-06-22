from howdex import Howdex

CASES = {
    "refund_agent": [
        {"tool": "issue_refund", "arguments": {"customer_id": "cus_123", "amount": 42.50}},
        {"tool": "send_email", "arguments": {"to": "customer@example.com", "subject": "Refund confirmed"}},
    ],
    "travel_agent": [
        {"tool": "book_flight", "arguments": {"traveller": "Ross", "from": "MAN", "to": "JFK"}},
        {"tool": "send_email", "arguments": {"to": "ross@example.com", "subject": "Flight booked"}},
    ],
    "data_agent": [
        {"tool": "run_regression", "arguments": {"dataset": "sales.csv", "target": "revenue"}},
        {"tool": "send_email", "arguments": {"to": "analyst@example.com", "subject": "Regression complete"}},
    ],
}

for name, steps in CASES.items():
    db = f".probe_{name}.db"
    memory = Howdex(path=db, embedder="hashing")

    for i in range(4):
        memory.start_session(f"{name}_task")
        for step in steps:
            memory.log_step(step, "success")
        memory.end_session("success")

    procedures = memory.learn(min_samples=3)

    print("\n" + "=" * 80)
    print(name)
    print("=" * 80)
    print("procedures:", len(procedures))
    for p in procedures:
        print("task:", p.task_signature)
        print("confidence:", p.confidence)
        print("steps:", [s.get("canonical_name") for s in p.steps])
