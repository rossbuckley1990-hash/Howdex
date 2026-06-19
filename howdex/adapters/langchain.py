from __future__ import annotations

from typing import Any


class HowdexLangChainAdapter:
    """Small LangChain adapter for Howdex.

    Usage:
        adapter = HowdexLangChainAdapter(memory)
        tools = adapter.tools()
    """

    def __init__(self, memory):
        self.memory = memory

    def inspect_howdex(self, query: str, top_k: int = 5) -> str:
        results = self.memory.search(query, top_k=top_k, min_score=0.0)

        if not results:
            return "Relevant Howdex memories: none"

        lines = ["Relevant Howdex memories:"]
        for r in results:
            content = r.memory.content.replace("\n", " ")
            lines.append(f"- score={r.score:.3f}: {content[:500]}")

        return "\n".join(lines)

    def remember_howdex(
        self,
        content: str,
        source: str = "agent",
        trust: str = "neutral",
        safety: str = "general",
    ) -> str:
        if hasattr(self.memory, "remember_trusted"):
            self.memory.remember_trusted(
                content,
                source=source,
                trust=trust,
                safety=safety,
            )
        else:
            self.memory.remember(content)

        return "remembered"

    def tools(self) -> list[Any]:
        try:
            from langchain_core.tools import tool
        except Exception as exc:
            raise ImportError(
                "LangChain adapter requires langchain-core. Install with: pip install langchain langchain-core"
            ) from exc

        adapter = self

        @tool
        def inspect_howdex(query: str) -> str:
            """Search Howdex memory for relevant prior experience."""
            return adapter.inspect_howdex(query)

        @tool
        def remember_howdex(content: str) -> str:
            """Store an important memory in Howdex."""
            return adapter.remember_howdex(content)

        return [inspect_howdex, remember_howdex]


def create_howdex_tools(memory) -> list[Any]:
    """Create LangChain tools for Howdex."""
    return HowdexLangChainAdapter(memory).tools()
