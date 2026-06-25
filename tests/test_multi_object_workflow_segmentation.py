from howdex import Howdex


def test_multi_object_refund_workflow_stays_whole(tmp_path):
    memory = Howdex(path=str(tmp_path / "refund_workflow.db"), embedder="hashing")

    steps = [
        {
            "tool": "lookup_order",
            "arguments": {
                "order_id": "ord_123",
            },
        },
        {
            "tool": "check_refund_eligibility",
            "arguments": {
                "order_id": "ord_123",
                "customer_id": "cus_123",
            },
        },
        {
            "tool": "issue_refund",
            "arguments": {
                "payment_id": "pay_123",
                "amount": 42.50,
            },
        },
        {
            "tool": "send_email",
            "arguments": {
                "to": "customer@example.com",
                "subject": "Refund confirmed",
            },
        },
    ]

    for _ in range(4):
        memory.start_session("refund_customer_order")
        for step in steps:
            memory.log_tool_call(step["tool"], step["arguments"], "success")
        memory.end_session("success")

    procedures = memory.learn(min_samples=3)

    assert len(procedures) >= 1

    learned_step_names = [
        step["canonical_name"]
        for procedure in procedures
        for step in procedure.steps
    ]

    assert "lookup_order" in learned_step_names
    assert "check_refund_eligibility" in learned_step_names
    assert "issue_refund" in learned_step_names
    assert "send_email" in learned_step_names

    full_workflow = [
        step["canonical_name"]
        for step in procedures[0].steps
    ]

    assert full_workflow == [
        "lookup_order",
        "check_refund_eligibility",
        "issue_refund",
        "send_email",
    ]


def test_multi_object_travel_workflow_stays_whole(tmp_path):
    memory = Howdex(path=str(tmp_path / "travel_workflow.db"), embedder="hashing")

    steps = [
        {
            "tool": "search_flights",
            "arguments": {
                "from": "MAN",
                "to": "JFK",
                "date": "2026-09-01",
            },
        },
        {
            "tool": "book_flight",
            "arguments": {
                "flight_id": "flight_123",
                "traveller": "Ross",
            },
        },
        {
            "tool": "reserve_hotel",
            "arguments": {
                "hotel_id": "hotel_456",
                "guest": "Ross",
            },
        },
        {
            "tool": "send_email",
            "arguments": {
                "to": "ross@example.com",
                "subject": "Trip confirmed",
            },
        },
    ]

    for _ in range(4):
        memory.start_session("book_customer_trip")
        for step in steps:
            memory.log_tool_call(step["tool"], step["arguments"], "success")
        memory.end_session("success")

    procedures = memory.learn(min_samples=3)

    assert len(procedures) >= 1

    assert [step["canonical_name"] for step in procedures[0].steps] == [
        "search_flights",
        "book_flight",
        "reserve_hotel",
        "send_email",
    ]


def test_multi_object_fulfillment_workflow_stays_whole(tmp_path):
    memory = Howdex(path=str(tmp_path / "fulfillment_workflow.db"), embedder="hashing")

    steps = [
        {
            "tool": "check_inventory",
            "arguments": {
                "sku": "SKU-123",
            },
        },
        {
            "tool": "reserve_stock",
            "arguments": {
                "sku": "SKU-123",
                "warehouse_id": "WH-1",
            },
        },
        {
            "tool": "create_shipment",
            "arguments": {
                "order_id": "ord_123",
                "warehouse_id": "WH-1",
            },
        },
        {
            "tool": "notify_customer",
            "arguments": {
                "customer_id": "cus_123",
                "message": "Your order has shipped",
            },
        },
    ]

    for _ in range(4):
        memory.start_session("fulfill_customer_order")
        for step in steps:
            memory.log_tool_call(step["tool"], step["arguments"], "success")
        memory.end_session("success")

    procedures = memory.learn(min_samples=3)

    assert len(procedures) >= 1

    assert [step["canonical_name"] for step in procedures[0].steps] == [
        "check_inventory",
        "reserve_stock",
        "create_shipment",
        "notify_customer",
    ]
