"""Task-relevance filtering for rendered operational guidance."""

from __future__ import annotations

from howdex import Howdex
from howdex.core.guidance import render_agent_guidance
from howdex.core.types import Procedure


def _docker_procedure() -> Procedure:
    return Procedure(
        id="docker-procedure",
        task_signature="recover broken Docker Compose HTTP health endpoint",
        steps=[
            {
                "canonical_name": "inspect_file",
                "parameterized_args": {"path": "runtime.env"},
                "target": "runtime.env",
            },
            {
                "canonical_name": "execute_bash",
                "parameterized_args": {"cmd": "docker compose up -d --build"},
                "target": "docker compose service",
            },
            {
                "canonical_name": "execute_bash",
                "parameterized_args": {
                    "cmd": "curl -sS -i http://127.0.0.1:43123/health"
                },
                "target": "/health",
            },
        ],
        expected_outcome="HTTP 200 from /health",
        success_rate=1.0,
        support_count=1,
        success_count=1,
        confidence=0.9,
        raw_supporting_examples=[
            {
                "steps": [
                    {
                        "tool_name": "execute_bash",
                        "tool_args": {"cmd": "cat runtime.env"},
                        "observation": "HEALTH_MODE=broken",
                    },
                    {
                        "tool_name": "execute_fs_write",
                        "tool_args": {
                            "file_path": "runtime.env",
                            "content": "APP_PORT=8000\nHEALTH_MODE=ready\n",
                        },
                        "observation": "wrote runtime.env",
                    },
                    {
                        "tool_name": "execute_bash",
                        "tool_args": {
                            "cmd": "docker compose up -d --build --force-recreate"
                        },
                        "observation": "container recreated",
                    },
                    {
                        "tool_name": "execute_bash",
                        "tool_args": {
                            "cmd": "curl -sS -i http://127.0.0.1:43123/health"
                        },
                        "observation": (
                            "SUCCESS: real health verifier passed HTTP 200"
                        ),
                    },
                ],
            }
        ],
        source_episode_ids=["docker-episode"],
    )


def _crypto_procedure() -> Procedure:
    return Procedure(
        id="crypto-procedure",
        task_signature="decrypt vault.enc from seed.txt",
        steps=[
            {
                "canonical_name": "execute_bash",
                "parameterized_args": {
                    "cmd": (
                        'printf %s "$(cat seed.txt | rev)" | '
                        "sha256sum | awk '{print $1}'"
                    )
                },
            },
            {
                "canonical_name": "execute_bash",
                "parameterized_args": {
                    "cmd": (
                        "openssl enc -d -aes-256-cbc -pbkdf2 "
                        "-in vault.enc -pass pass:<hash>"
                    )
                },
            },
        ],
        success_rate=1.0,
        support_count=1,
        success_count=1,
        confidence=0.9,
        raw_supporting_examples=[
            {
                "steps": [
                    {
                        "tool_name": "execute_bash",
                        "tool_args": {
                            "cmd": (
                                'printf %s "$(cat seed.txt | rev)" | '
                                "sha256sum | awk '{print $1}'"
                            )
                        },
                        "observation": "calculated SHA256 digest",
                    },
                    {
                        "tool_name": "execute_bash",
                        "tool_args": {
                            "cmd": (
                                "openssl enc -d -aes-256-cbc -pbkdf2 "
                                "-in vault.enc -pass pass:<hash>"
                            )
                        },
                        "observation": "SUCCESS: decrypted TARGET:EXAMPLE",
                    },
                ],
            }
        ],
        source_episode_ids=["crypto-episode"],
    )


def _zb2_procedure() -> Procedure:
    return Procedure(
        id="zb2-procedure",
        task_signature="decode challenge.zb2 and extract TARGET",
        steps=[
            {
                "canonical_name": "execute_file",
                "parameterized_args": {"cmd": "python3 decoder.py challenge.zb2"},
            }
        ],
        success_rate=1.0,
        support_count=1,
        success_count=1,
        confidence=0.9,
        raw_supporting_examples=[
            {
                "steps": [
                    {
                        "tool_name": "execute_fs_write",
                        "tool_args": {
                            "file_path": "decoder.py",
                            "content": (
                                "ZB2! data[4] data[5] data[6] reverse "
                                "xor checksum % 251 TARGET:"
                            ),
                        },
                        "observation": "wrote decoder.py",
                    },
                    {
                        "tool_name": "execute_bash",
                        "tool_args": {"cmd": "python3 decoder.py challenge.zb2"},
                        "observation": "SUCCESS: decoded TARGET 9001",
                    },
                ],
            }
        ],
        source_episode_ids=["zb2-episode"],
    )


def test_docker_guidance_excludes_crypto_and_target_facts():
    guidance = render_agent_guidance(
        [_docker_procedure(), _crypto_procedure(), _zb2_procedure()],
        objective="Recover Docker Compose service health at /health.",
        include_source=False,
    )

    assert "inspect the Docker Compose service configuration" in guidance
    assert "verify the local /health endpoint" in guidance
    assert "SHA256" not in guidance
    assert "trailing newline" not in guidance
    assert "TARGET" not in guidance
    assert "OpenSSL" not in guidance


def test_polyglot_openssl_guidance_keeps_crypto_facts():
    guidance = render_agent_guidance(
        [_docker_procedure(), _crypto_procedure()],
        objective="Decrypt vault.enc from seed.txt.",
        include_source=False,
    )

    assert "calculate the SHA256 hex digest" in guidance
    assert "hash bytes exactly; do not add a trailing newline" in guidance
    assert "decrypt with OpenSSL AES-256-CBC" in guidance
    assert "include -pbkdf2" in guidance
    assert "inspect the Docker Compose service configuration" not in guidance


def test_zb2_guidance_keeps_binary_decode_target_facts():
    guidance = render_agent_guidance(
        [_docker_procedure(), _zb2_procedure()],
        objective="Decode challenge.zb2 and reveal the true TARGET value.",
        include_source=False,
    )

    assert "success requires revealing the expected TARGET string" in guidance
    assert "check the file magic marker before decoding" in guidance
    assert "use the dynamic key from the encoded file header" in guidance
    assert "use the payload offset from the encoded file header" in guidance
    assert "use the payload length from the encoded file header" in guidance
    assert "inspect the Docker Compose service configuration" not in guidance


def test_mixed_memory_store_retrieval_does_not_contaminate_docker_guidance(
    tmp_path,
):
    memory = Howdex(path=tmp_path / "mixed.db", embedder="hashing")
    try:
        for procedure in (_docker_procedure(), _crypto_procedure()):
            memory.store.put_procedure(dict(procedure.__dict__))

        guidance = memory.guidance(
            "Recover the broken Docker Compose HTTP service and make /health return 200.",
            query="recover broken service",
            top_k=3,
            min_confidence=0.0,
            include_source=False,
        )

        assert "verify the local /health endpoint" in guidance
        assert "SHA256" not in guidance
        assert "trailing newline" not in guidance
        assert "TARGET" not in guidance
        assert "OpenSSL" not in guidance
    finally:
        memory.close()


def test_relevance_filtered_guidance_is_deterministic():
    procedures = [_docker_procedure(), _crypto_procedure(), _zb2_procedure()]
    kwargs = {
        "objective": "Recover Docker Compose service health at /health.",
        "include_source": False,
    }

    first = render_agent_guidance(procedures, **kwargs)
    second = render_agent_guidance(procedures, **kwargs)

    assert first == second
