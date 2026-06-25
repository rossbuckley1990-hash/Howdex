from howdex.core.guidance import render_agent_guidance


def test_agent_guidance_includes_objective_rules_facts_and_verification():
    procedures = [
        {
            "task_signature": "polyglot_crypto_teacher",
            "confidence": 0.91,
            "support_count": 1,
            "learned_facts": [
                "read the raw contents of seed.txt",
                "reverse the seed string before hashing it",
                "calculate the SHA256 hex digest of the reversed seed",
                "hash the reversed seed bytes exactly, with no trailing newline",
                "decrypt vault.enc with openssl AES-256-CBC",
                "include the -pbkdf2 flag when decrypting",
            ],
            "failed_attempts": [
                "cat seed.txt | rev | printf %s | shasum -a 256",
            ],
            "verification": [
                "Run the real verifier before marking done",
                "Success requires TARGET output",
            ],
        }
    ]

    guidance = render_agent_guidance(
        procedures,
        objective="Decrypt vault.enc using Bash only",
        constraints=[
            "Python is unavailable",
            "Use Bash tools only",
            "Do not paste source code",
        ],
        target_environment="bash",
        include_source=False,
        include_failed_attempts=True,
        include_verification=True,
    )

    assert "# HOWDEX OPERATIONAL MEMORY" in guidance
    assert "Objective:" in guidance
    assert "Decrypt vault.enc using Bash only" in guidance
    assert "Rules:" in guidance
    assert "Python is unavailable" in guidance
    assert "Learned operational facts:" in guidance
    assert "reverse the seed string before hashing it" in guidance
    assert "Avoid these failed attempts:" in guidance
    assert "printf does not read from stdin" in guidance
    assert "Verification:" in guidance
    assert "Success requires TARGET output" in guidance


def test_agent_guidance_excludes_source_when_disabled():
    procedures = [
        {
            "task_signature": "source_tool_teacher",
            "learned_facts": ["write a parser"],
            "source_artifacts": [
                {
                    "file_path": "decoder.py",
                    "content": "import hashlib\nprint('secret source')",
                }
            ],
        }
    ]

    guidance = render_agent_guidance(
        procedures,
        objective="Solve without pasted source",
        include_source=False,
    )

    assert "decoder.py" not in guidance
    assert "import hashlib" not in guidance
    assert "secret source" not in guidance
    assert "Source artifacts excluded" in guidance


def test_agent_guidance_can_include_source_when_enabled():
    procedures = [
        {
            "task_signature": "source_tool_teacher",
            "learned_facts": ["write a parser"],
            "source_artifacts": [
                {
                    "file_path": "decoder.py",
                    "content": "print('hello')",
                }
            ],
        }
    ]

    guidance = render_agent_guidance(
        procedures,
        objective="Replay source artifact",
        include_source=True,
    )

    assert "decoder.py" in guidance
    assert "```python" in guidance
    assert "print('hello')" in guidance


def test_agent_guidance_is_deterministic():
    procedures = [
        {
            "task_signature": "task",
            "confidence": 0.5,
            "learned_facts": ["fact b", "fact a", "fact b"],
            "failed_attempts": ["bad b", "bad a", "bad b"],
            "verification": ["verify b", "verify a"],
        }
    ]

    first = render_agent_guidance(
        procedures,
        objective="Do task",
        constraints=["constraint b", "constraint a"],
    )
    second = render_agent_guidance(
        procedures,
        objective="Do task",
        constraints=["constraint b", "constraint a"],
    )

    assert first == second
    assert first.count("fact b") == 1
    assert first.count("bad b") == 1


def test_agent_guidance_respects_max_chars():
    procedures = [
        {
            "task_signature": "large",
            "learned_facts": [f"fact {i}" for i in range(100)],
        }
    ]

    guidance = render_agent_guidance(
        procedures,
        objective="Short output",
        max_chars=500,
    )

    assert len(guidance) <= 500
    assert guidance.endswith("\n[Howdex guidance truncated]\n")
