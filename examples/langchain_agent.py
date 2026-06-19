"""Use Howdex as a LangChain agent's memory backend.

Prereqs:
    pip install langchain langchain-openai howdex-ai

Run: python examples/langchain_agent.py
"""

import os

from howdex import Howdex
from howdex.adapters.langchain import HowdexLangChainAdapter


def demo():
    # build the adapter
    memory = Howdex(path="./langchain.db", embedder="hashing")
    adapter = HowdexLangChainAdapter(memory)

    # seed some memory
    memory.remember(
        "The user is a Python developer who loves clean code",
        layer="semantic", importance=0.9,
    )

    # inspect relevant memory before a turn
    context = adapter.inspect_howdex("What languages do I like?")
    print("=== Loaded memory context ===")
    print(context)

    # save a useful outcome
    adapter.remember_howdex(
        "The assistant confirmed that the user prefers Python.",
        source="agent",
    )
    print("\n=== Saved new turn to memory ===")

    # next turn — should find the new memory too
    context = adapter.inspect_howdex("Tell me more about my preferences")
    print("\n=== Next turn context ===")
    print(context)


if __name__ == "__main__":
    demo()
