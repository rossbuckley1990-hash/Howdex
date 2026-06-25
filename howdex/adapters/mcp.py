from __future__ import annotations


def create_howdex_mcp_server(memory, name: str = "howdex-memory"):
    """Create a FastMCP server exposing Howdex tools.

    Usage:
        from howdex import Howdex
        from howdex.adapters.mcp import create_howdex_mcp_server

        mem = Howdex("./howdex.db")
        server = create_howdex_mcp_server(mem)
        server.run()
    """

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:
        raise ImportError("MCP adapter requires mcp. Install with: pip install mcp") from exc

    mcp = FastMCP(name)

    @mcp.tool()
    def inspect_howdex(query: str, top_k: int = 5) -> str:
        """Search Howdex memory for relevant prior experience."""
        results = memory.search(query, top_k=top_k, min_score=0.0)

        if not results:
            return "Relevant Howdex memories: none"

        lines = ["Relevant Howdex memories:"]
        for r in results:
            content = r.memory.content.replace("\n", " ")
            lines.append(f"- score={r.score:.3f}: {content[:500]}")

        return "\n".join(lines)

    @mcp.tool()
    def remember_howdex(content: str) -> str:
        """Store an important memory in Howdex."""
        if hasattr(memory, "remember_trusted"):
            memory.remember_trusted(
                content,
                source="agent",
                trust="neutral",
                safety="general",
            )
        else:
            memory.remember(content)

        return "remembered"

    @mcp.tool()
    def howdex_stats() -> str:
        """Return Howdex memory statistics."""
        return str(memory.stats())

    return mcp
