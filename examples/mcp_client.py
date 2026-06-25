"""Use Howdex via the MCP (Model Context Protocol) server.

This example shows how to start the MCP server and call it programmatically
over stdio. In practice, you'd configure Claude Desktop / Cursor / etc.
to talk to it instead.

Prereqs:
    pip install howdex-ai

Run: python examples/mcp_client.py
"""

import json
import subprocess
import sys


def call_mcp(proc, method, params=None, req_id=1):
    req = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params:
        req["params"] = params
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        msg = json.loads(line)
        if msg.get("id") == req_id:
            return msg


def main():
    proc = subprocess.Popen(
        [sys.executable, "-m", "howdex.cli", "--embedder", "hashing", "mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )

    # initialize
    resp = call_mcp(proc, "initialize", {})
    print("=== Initialize ===")
    print(json.dumps(resp.get("result"), indent=2))

    # list tools
    resp = call_mcp(proc, "tools/list", {}, req_id=2)
    print("\n=== Tools ===")
    for tool in resp["result"]["tools"]:
        print(f"  • {tool['name']}: {tool['description'][:80]}...")

    # call remember
    resp = call_mcp(proc, "tools/call", {
        "name": "howdex_remember",
        "arguments": {"content": "MCP is the future of agent interfaces",
                      "layer": "semantic", "importance": 0.9},
    }, req_id=3)
    print("\n=== Remember ===")
    print(resp["result"]["content"][0]["text"])

    # call search
    resp = call_mcp(proc, "tools/call", {
        "name": "howdex_search",
        "arguments": {"query": "agent interfaces"},
    }, req_id=4)
    print("\n=== Search ===")
    print(resp["result"]["content"][0]["text"])

    proc.stdin.close()
    proc.wait()


if __name__ == "__main__":
    main()
