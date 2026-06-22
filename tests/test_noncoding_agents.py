from howdex import Howdex


def _learn_procedure(tmp_path, name, steps):
    memory = Howdex(path=str(tmp_path / f"{name}.db"), embedder="hashing")

    for _ in range(4):
        memory.start_session(f"{name}_task")
        for step in steps:
            memory.log_step(step, "success")
        memory.end_session("success")

    return memory.learn(min_samples=3)


def test_refund_agent_learns_structured_tool_procedure(tmp_path):
    procedures = _learn_procedure(
        tmp_path,
        "refund_agent",
        [
            {"tool": "issue_refund", "arguments": {"customer_id": "cus_123", "amount": 42.50}},
            {"tool": "send_email", "arguments": {"to": "customer@example.com", "subject": "Refund confirmed"}},
        ],
    )

    assert len(procedures) == 1
    assert [step["canonical_name"] for step in procedures[0].steps] == [
        "issue_refund",
        "send_email",
    ]
    assert procedures[0].confidence >= 0.95


def test_travel_agent_learns_structured_tool_procedure(tmp_path):
    procedures = _learn_procedure(
        tmp_path,
        "travel_agent",
        [
            {"tool": "book_flight", "arguments": {"traveller": "Ross", "from": "MAN", "to": "JFK"}},
            {"tool": "send_email", "arguments": {"to": "ross@example.com", "subject": "Flight booked"}},
        ],
    )

    assert len(procedures) == 1
    assert [step["canonical_name"] for step in procedures[0].steps] == [
        "book_flight",
        "send_email",
    ]
    assert procedures[0].confidence >= 0.95


def test_data_agent_learns_structured_tool_procedure(tmp_path):
    procedures = _learn_procedure(
        tmp_path,
        "data_agent",
        [
            {"tool": "run_regression", "arguments": {"dataset": "sales.csv", "target": "revenue"}},
            {"tool": "send_email", "arguments": {"to": "analyst@example.com", "subject": "Regression complete"}},
        ],
    )

    assert len(procedures) == 1
    assert [step["canonical_name"] for step in procedures[0].steps] == [
        "run_regression",
        "send_email",
    ]
    assert procedures[0].confidence >= 0.95
