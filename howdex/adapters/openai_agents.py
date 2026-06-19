from __future__ import annotations

from typing import Any


class HowdexOpenAIAgentsAdapter:
    """OpenAI Agents SDK adapter for Howdex."""

    def __init__(self, memory):
        self.memory = memory

    def inspect_howdex_text(self, query: str, top_k: int = 5) -> str:
        results = self.memory.search(query, top_k=top_k, min_score=0.0)

        if not results:
            return "Relevant Howdex memories: none"

        lines = ["Relevant Howdex memories:"]
        for r in results:
            content = r.memory.content.replace("\n", " ")
            lines.append(f"- score={r.score:.3f}: {content[:500]}")

        return "\n".join(lines)

    def remember_howdex_text(self, content: str) -> str:
        if hasattr(self.memory, "remember_trusted"):
            self.memory.remember_trusted(
                content,
                source="agent",
                trust="neutral",
                safety="general",
            )
        else:
            self.memory.remember(content)

        return "remembered"

    def tools(self) -> list[Any]:
        try:
            from agents import function_tool
        except Exception as exc:
            raise ImportError(
                "OpenAI Agents adapter requires openai-agents. Install with: pip install openai-agents"
            ) from exc

        adapter = self

        @function_tool
        def inspect_howdex(query: str) -> str:
            """Search Howdex memory for relevant prior experience."""
            return adapter.inspect_howdex_text(query)

        @function_tool
        def remember_howdex(content: str) -> str:
            """Store an important memory in Howdex."""
            return adapter.remember_howdex_text(content)

        return [inspect_howdex, remember_howdex]


def create_howdex_tools(memory) -> list[Any]:
    """Create OpenAI Agents SDK function tools for Howdex."""
    return HowdexOpenAIAgentsAdapter(memory).tools()
