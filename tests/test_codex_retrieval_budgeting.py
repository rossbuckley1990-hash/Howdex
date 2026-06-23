from __future__ import annotations

from howdex.core.guidance import (
    GuidanceBudget,
    render_agent_guidance,
    select_guidance_procedures,
)


def _proc(
    ident: str,
    *,
    title: str,
    category: str,
    facts: list[str],
    status: str = "candidate",
    confidence: float = 0.8,
    score: float | None = None,
    compatibility: dict | None = None,
):
    payload = {
        "category": category,
        "confidence": confidence,
        "id": ident,
        "learned_facts": facts,
        "status": status,
        "tags": [category, *title.casefold().split()],
        "task_signature": title,
        "title": title,
        "verification": [
            "Run the real verifier before marking done.",
        ],
    }
    if score is not None:
        payload["score"] = score
    if compatibility is not None:
        payload["compatibility"] = compatibility
    return payload


def _docker_proc(ident: str, **overrides):
    return _proc(
        ident,
        title=overrides.pop("title", "Docker Compose health recovery"),
        category=overrides.pop("category", "docker/config/health"),
        facts=overrides.pop(
            "facts",
            [
                "Inspect docker-compose.yml and runtime.env.",
                "Align HEALTH_MODE with the required health policy.",
                "Recreate the Docker Compose service before verifying health.",
                "Verify /health returns HTTP 200.",
            ],
        ),
        **overrides,
    )


def test_max_procedures_respected():
    candidates = [
        _docker_proc(
            f"docker-{index}",
            title=f"Docker health recovery {index}",
            facts=[
                f"Inspect docker-compose.yml service {index}.",
                f"Verify /health returns HTTP 200 for service {index}.",
            ],
        )
        for index in range(5)
    ]

    selection = select_guidance_procedures(
        "Docker health recovery",
        candidates,
        GuidanceBudget(
            diversity_by_category=False,
            max_procedures=2,
            min_relevance_score=0.01,
        ),
    )

    assert len(selection.selected) == 2
    assert selection.omitted_count == 3
    assert any("max_procedures" in item.reason for item in selection.excluded)


def test_max_guidance_chars_respected():
    candidates = [
        _docker_proc(
            "docker-large",
            facts=[
                "Inspect docker-compose.yml and runtime.env. " * 30,
                "Verify /health returns HTTP 200. " * 30,
            ],
        ),
        _docker_proc(
            "docker-small",
            title="Docker health quick verifier",
            facts=["Verify /health returns HTTP 200."],
        ),
    ]
    budget = GuidanceBudget(
        max_procedures=2,
        max_guidance_chars=1_200,
        min_relevance_score=0.01,
    )

    selection = select_guidance_procedures(
        "Docker health recovery",
        candidates,
        budget,
    )
    guidance = render_agent_guidance(
        candidates,
        objective="Docker health recovery",
        retrieval_budget=budget,
        max_chars=10_000,
    )

    assert selection.context_budget_used <= 1_200
    assert len(guidance) <= 1_200


def test_verified_beats_candidate_when_relevance_is_close():
    candidate = _docker_proc(
        "candidate",
        title="Docker Compose health recovery candidate",
        status="candidate",
        score=0.80,
    )
    verified = _docker_proc(
        "verified",
        title="Docker Compose health recovery verified",
        status="verified",
        score=0.78,
    )

    selection = select_guidance_procedures(
        "Docker Compose health recovery",
        [candidate, verified],
        GuidanceBudget(max_procedures=1, min_relevance_score=0.01),
    )

    assert selection.selected[0]["id"] == "verified"


def test_stale_and_incompatible_suppressed_by_default():
    current = {
        "as_of": "2026-06-23",
        "ecosystem": "devops",
        "tool": "docker compose",
        "version": "2.27.0",
    }
    fresh = _docker_proc(
        "fresh",
        compatibility={
            "ecosystem": "devops",
            "last_verified_at": "2026-06-01",
            "stale_after_days": 60,
            "tool": "docker compose",
            "version_range": ">=2 <3",
        },
    )
    stale = _docker_proc(
        "stale",
        compatibility={
            "ecosystem": "devops",
            "last_verified_at": "2026-01-01",
            "stale_after_days": 30,
            "tool": "docker compose",
            "version_range": ">=2 <3",
        },
    )
    incompatible = _docker_proc(
        "incompatible",
        compatibility={
            "ecosystem": "devops",
            "known_incompatible_versions": ["2.x"],
            "last_verified_at": "2026-06-01",
            "stale_after_days": 60,
            "tool": "docker compose",
            "version_range": ">=2 <3",
        },
    )

    selection = select_guidance_procedures(
        "Docker Compose health recovery",
        [stale, incompatible, fresh],
        GuidanceBudget(
            current_environment=current,
            max_procedures=3,
            min_relevance_score=0.01,
        ),
    )

    assert [item["id"] for item in selection.selected] == ["fresh"]
    assert {item.procedure_id for item in selection.excluded} >= {
        "stale",
        "incompatible",
    }
    assert any("stale procedure suppressed" in item.reason for item in selection.excluded)
    assert any("incompatible procedure suppressed" in item.reason for item in selection.excluded)


def test_irrelevant_categories_excluded():
    docker = _docker_proc("docker")
    crypto = _proc(
        "crypto",
        title="OpenSSL SHA256 reverse seed decryption",
        category="crypto/hash/openssl",
        facts=[
            "Calculate the SHA256 hex digest.",
            "Decrypt vault.enc with OpenSSL AES-256-CBC and PBKDF2.",
        ],
    )

    selection = select_guidance_procedures(
        "Docker Compose health recovery",
        [crypto, docker],
        GuidanceBudget(max_procedures=3, min_relevance_score=0.05),
    )

    assert [item["id"] for item in selection.selected] == ["docker"]
    assert selection.excluded[0].procedure_id == "crypto"
    assert selection.excluded[0].reason == "below min_relevance_score"


def test_diversity_prevents_duplicate_spam():
    duplicate_a = _docker_proc("docker-a", title="Docker health recovery A")
    duplicate_b = _docker_proc("docker-b", title="Docker health recovery B")
    distinct = _docker_proc(
        "docker-distinct",
        title="Docker health verifier port recovery",
        facts=[
            "Inspect APP_PORT and docker-compose.yml port bindings.",
            "Verify /health returns HTTP 200 on the sandbox port.",
        ],
    )

    selection = select_guidance_procedures(
        "Docker health recovery",
        [duplicate_a, duplicate_b, distinct],
        GuidanceBudget(max_procedures=3, min_relevance_score=0.01),
    )

    selected_ids = {item["id"] for item in selection.selected}
    assert len({"docker-a", "docker-b"} & selected_ids) == 1
    assert "docker-distinct" in selected_ids
    assert any("near-duplicate" in item.reason for item in selection.excluded)


def test_debug_guidance_explains_omissions():
    docker = _docker_proc("docker")
    random = _proc(
        "random",
        title="Frontend button color polish",
        category="frontend",
        facts=["Change a CSS class on a React component."],
    )

    guidance = render_agent_guidance(
        [random, docker],
        objective="Docker Compose health recovery",
        retrieval_budget=GuidanceBudget(max_procedures=1, min_relevance_score=0.05),
        debug=True,
    )

    assert "Retrieval budget:" in guidance
    assert "Selected procedures: 1" in guidance
    assert "Omitted procedures: 1" in guidance
    assert "Omission reasons:" in guidance
    assert "random: below min_relevance_score" in guidance


def test_500_procedure_synthetic_codex_stays_precise():
    procedures = []
    procedures.extend(
        _docker_proc(
            f"docker-{index}",
            title=f"Docker Compose health recovery {index}",
            facts=[
                "Inspect docker-compose.yml, runtime.env, and health-policy.conf.",
                "Align HEALTH_MODE with the required health policy.",
                "Recreate the Docker Compose service before verifying health.",
                "Verify /health returns HTTP 200 and a healthy body.",
            ],
        )
        for index in range(10)
    )
    procedures.extend(
        _proc(
            f"crypto-{index}",
            title=f"OpenSSL SHA256 reverse seed {index}",
            category="crypto/hash/openssl",
            facts=[
                "Calculate the SHA256 hex digest of the transformed input.",
                "Decrypt vault.enc with OpenSSL AES-256-CBC and PBKDF2.",
            ],
        )
        for index in range(120)
    )
    procedures.extend(
        _proc(
            f"frontend-{index}",
            title=f"React frontend recovery {index}",
            category="frontend",
            facts=[
                "Use a React render recovery procedure.",
                "Run the frontend test suite.",
            ],
        )
        for index in range(120)
    )
    procedures.extend(
        _proc(
            f"random-{index}",
            title=f"Random operational note {index}",
            category="random",
            facts=[
                "Inspect unrelated service logs.",
                "Update an unrelated configuration value.",
            ],
        )
        for index in range(250)
    )

    guidance = render_agent_guidance(
        procedures,
        objective="Recover Docker Compose health endpoint",
        retrieval_budget=GuidanceBudget(
            max_procedures=3,
            max_guidance_chars=2_500,
            min_relevance_score=0.05,
        ),
        max_chars=10_000,
    )

    assert len(procedures) == 500
    assert len(guidance) <= 2_500
    assert "Docker Compose" in guidance
    assert "health-policy.conf" in guidance
    assert "HEALTH_MODE" in guidance
    assert "SHA256" not in guidance
    assert "vault.enc" not in guidance
    assert "React render" not in guidance
    assert "Random operational note" not in guidance
