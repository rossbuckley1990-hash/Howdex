import shutil
from pathlib import Path

from howdex import Howdex


def fresh_memory(name: str) -> Howdex:
    root = Path.home() / f".howdex-adapter-test-{name}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return Howdex(path=str(root / "howdex.db"))


def test_langchain_adapter_imports_and_inspects():
    from howdex.adapters.langchain import HowdexLangChainAdapter

    mem = fresh_memory("langchain")
    mem.remember_trusted(
        "Before deployment, check DATABASE_URL.",
        source="system",
        trust="verified",
        safety="operational",
    )

    adapter = HowdexLangChainAdapter(mem)
    text = adapter.inspect_howdex("deployment")
    assert "DATABASE_URL" in text


def test_openai_agents_adapter_imports_and_inspects():
    from howdex.adapters.openai_agents import HowdexOpenAIAgentsAdapter

    mem = fresh_memory("openai-agents")
    mem.remember_trusted(
        "Before deployment, check DATABASE_URL.",
        source="system",
        trust="verified",
        safety="operational",
    )

    adapter = HowdexOpenAIAgentsAdapter(mem)
    text = adapter.inspect_howdex_text("deployment")
    assert "DATABASE_URL" in text


def test_mcp_adapter_import_function_exists():
    from howdex.adapters.mcp import create_howdex_mcp_server

    assert callable(create_howdex_mcp_server)
