"""The ``howdex`` command-line tool.

Usage:

    howdex init                         # initialize ~/.howdex
    howdex remember "fact"              # quick-store
    howdex remember "x" --layer working --ttl 60
    howdex search "query"               # preferred retrieval command
    howdex recall "query"               # compatibility alias
    howdex learn                        # consolidate episodes → procedures
    howdex sync http://peer:7331        # sync with peer
    howdex stats                        # show stats
    howdex procedures                   # list learned procedures
    howdex procedure export             # export portable procedure JSON
    howdex procedure import <path>      # import portable procedure JSON
    howdex codex init                   # create .howdex/codex
    howdex codex publish                # publish procedures to local Codex
    howdex codex pull <path>            # import another local Codex
    howdex forget <id>                  # delete a memory
    howdex vacuum                       # GC expired + tombstoned
    howdex mcp                          # start MCP server (stdio)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import json
import sys
from pathlib import Path
from typing import Any, Optional

from howdex import Howdex, __version__
from howdex.core.types import MemoryLayer, MemoryType


def _format_mem(m: dict[str, Any]) -> str:
    layer = m.get("layer", "?")
    type_ = m.get("type", "?")
    content = m.get("content", "")
    if len(content) > 200:
        content = content[:197] + "..."
    return f"[{layer}/{type_}] {content}\n  id={m['id'][:8]} importance={m.get('importance', 0):.2f}"


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else None
    mem = Howdex(path=path, embedder=args.embedder)
    print(f"✓ Initialized Howdex at {mem.path}")
    print(f"  embedder: {mem.embedder.name} (dim={mem.embed_dim})")
    print(f"  node_id:  {mem.store.node_id}")
    print(f"\nNext: howdex remember \"Hello, world\"")
    return 0


def cmd_remember(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder, agent_id=args.agent_id)
    try:
        layer = MemoryLayer(args.layer)
        mtype = MemoryType(args.type) if args.type else _default_type(layer)
        m = mem.remember(
            content=args.content,
            layer=layer,
            type=mtype,
            metadata=json.loads(args.metadata) if args.metadata else {},
            importance=args.importance,
            ttl=args.ttl,
            source=args.source,
        )
        print(f"✓ remembered ({m.id[:8]}) [{layer.value}/{mtype.value}]")
        print(f"  {args.content}")
        return 0
    finally:
        mem.close()


def _default_type(layer: MemoryLayer) -> MemoryType:
    return {
        MemoryLayer.WORKING: MemoryType.CONTEXT,
        MemoryLayer.SEMANTIC: MemoryType.FACT,
        MemoryLayer.EPISODIC: MemoryType.SESSION,
        MemoryLayer.PROCEDURAL: MemoryType.WORKFLOW,
    }[layer]


def cmd_search(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder, agent_id=args.agent_id)
    try:
        results = mem.search(
            args.query,
            layer=args.layer,
            top_k=args.top_k,
            min_score=args.min_score,
        )
        if not results:
            print("(no memories matched)")
            return 0
        for r in results:
            print(f"{r.score:.3f}  [{r.matched_by}]  {r.memory.content[:120]}")
            if args.verbose:
                print(f"          id={r.memory.id[:8]} layer={r.memory.layer.value} "
                      f"type={r.memory.type.value} importance={r.memory.importance:.2f}")
        return 0
    finally:
        mem.close()


def cmd_learn(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        procs = mem.learn(min_samples=args.min_samples, dry_run=args.dry_run)
        if not procs:
            print("(no new procedures learned — need more episodes)")
            return 0
        verb = "would learn" if args.dry_run else "learned"
        print(f"✓ {verb} {len(procs)} procedure(s):")
        for p in procs:
            print(f"  • {p.task_signature}")
            print(f"    success_rate={p.success_rate:.2f}  samples={p.sample_count}  "
                  f"steps={len(p.steps)}")
            if p.preconditions:
                print(f"    preconditions: {p.preconditions}")
        return 0
    finally:
        mem.close()


def cmd_sync(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        result = mem.sync(peer=args.peer)
        print(f"✓ sync complete: {result}")
        return 0
    finally:
        mem.close()


def cmd_stats(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        s = mem.stats()
        print(f"Howdex — {s['db_path']}")
        print(f"  node_id:           {s['node_id']}")
        print(f"  total memories:    {s['total_memories']}")
        print(f"  per layer:")
        for layer, n in s["per_layer"].items():
            print(f"    {layer:12s} {n}")
        print(f"  episodes:          {s['episodes']}")
        print(f"  procedures:        {s['procedures']}")
        print(f"  pending sync ops:  {s['pending_sync_ops']}")
        return 0
    finally:
        mem.close()


def cmd_procedures(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        procs = mem.list_procedures()
        if not procs:
            print("(no procedures yet — run `howdex learn` after some episodes)")
            return 0
        for p in procs:
            print(f"• {p.task_signature}")
            print(f"  id={p.id[:8]}  success_rate={p.success_rate:.2f}  "
                  f"samples={p.sample_count}  uses={p.use_count}")
            if p.steps:
                for i, s in enumerate(p.steps):
                    print(f"  {i+1}. {s.get('action', '?')} → {s.get('observation', '?')[:80]}")
            if p.preconditions:
                print(f"  preconditions: {p.preconditions}")
            print()
        return 0
    finally:
        mem.close()


def cmd_procedure_export(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        result = mem.export_procedures(args.output)
        print(f"✓ exported {result['exported']} procedure(s) to {result['output']}")
        return 0
    finally:
        mem.close()


def cmd_procedure_import(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        result = mem.import_procedures(args.source)
        print(
            "✓ processed "
            f"{result['files']} file(s): "
            f"{result['imported']} imported, "
            f"{result['updated']} updated, "
            f"{result['unchanged']} unchanged"
        )
        return 0
    finally:
        mem.close()


def cmd_codex_init(args: argparse.Namespace) -> int:
    from howdex.portable import init_codex

    result = init_codex(args.codex_path)
    print(f"✓ initialized local Codex at {result['root']}")
    return 0


def cmd_codex_publish(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        result = mem.publish_codex(args.codex_path)
        print(
            f"✓ published {result['exported']} procedure(s) "
            f"to {result['procedures']}"
        )
        return 0
    finally:
        mem.close()


def cmd_codex_pull(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        result = mem.pull_codex(args.source)
        print(
            "✓ pulled "
            f"{result['files']} file(s): "
            f"{result['imported']} imported, "
            f"{result['updated']} updated, "
            f"{result['unchanged']} unchanged"
        )
        return 0
    finally:
        mem.close()


def cmd_forget(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        mem.forget(args.memory_id)
        print(f"✓ forgot {args.memory_id[:8]}")
        return 0
    finally:
        mem.close()


def cmd_vacuum(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        n = mem.vacuum()
        print(f"✓ vacuumed {n} memories")
        return 0
    finally:
        mem.close()


def cmd_mcp(args: argparse.Namespace) -> int:
    """Start the MCP server over stdio."""
    from howdex.mcp.server import run_stdio
    run_stdio(path=args.path, embedder=args.embedder)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export all memories to JSON."""
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        out: list[dict[str, Any]] = []
        for m in mem.store.query(limit=10_000_000):
            out.append(m.to_dict())
        with open(args.output, "w") as f:
            json.dump({"memories": out}, f, indent=2)
        print(f"✓ exported {len(out)} memories to {args.output}")
        return 0
    finally:
        mem.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="howdex",
        description="Howdex — procedural memory for autonomous agents",
    )
    p.add_argument("--version", action="version", version=f"howdex {__version__}")
    p.add_argument("--path", help="database path (default: $HOWDEX_HOME/howdex.db or ~/.howdex/howdex.db)")
    p.add_argument("--embedder", default=None,
                   help="embedding backend: st | openai | hashing (default: auto)")
    p.add_argument("--agent-id", default=None)

    sub = p.add_subparsers(dest="cmd", required=True)

    health_parser = sub.add_parser("health", help="Run Howdex production healthcheck")
    health_parser.set_defaults(func=cmd_health)

    eval_parser = sub.add_parser("eval", help="Run Howdex benchmark suites")
    eval_parser.add_argument(
        "suite",
        choices=["swe-repeat", "swe-repeat-multi", "swe-repeat-9", "real-repo", "oss-repo"],
        help="Evaluation suite to run.",
    )
    eval_parser.set_defaults(func=cmd_eval)


    sub.add_parser("init", help="initialize a new Howdex database").set_defaults(func=cmd_init)

    sp = sub.add_parser("remember", help="store a memory")
    sp.add_argument("content")
    sp.add_argument("--layer", default="semantic",
                    choices=[l.value for l in MemoryLayer])
    sp.add_argument("--type", default=None, choices=[t.value for t in MemoryType])
    sp.add_argument("--metadata", default=None, help="JSON object")
    sp.add_argument("--importance", type=float, default=0.5)
    sp.add_argument("--ttl", type=float, default=None, help="seconds (working memory default: 300)")
    sp.add_argument("--source", default="user")
    sp.set_defaults(func=cmd_remember)

    for name, help_text in (
        ("search", "search memories"),
        ("recall", "search memories (compatibility alias)"),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("query")
        sp.add_argument("--layer", default=None, choices=[l.value for l in MemoryLayer])
        sp.add_argument("--top-k", type=int, default=5)
        sp.add_argument("--min-score", type=float, default=0.1)
        sp.add_argument("-v", "--verbose", action="store_true")
        sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("learn", help="consolidate episodes → procedures")
    sp.add_argument("--min-samples", type=int, default=3)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_learn)

    sp = sub.add_parser("sync", help="sync with peer")
    sp.add_argument("peer", help="HTTP URL or .json file path")
    sp.set_defaults(func=cmd_sync)

    sub.add_parser("stats", help="show database stats").set_defaults(func=cmd_stats)
    sub.add_parser("procedures", help="list learned procedures").set_defaults(func=cmd_procedures)

    procedure_parser = sub.add_parser(
        "procedure",
        help="export or import portable procedures",
    )
    procedure_sub = procedure_parser.add_subparsers(
        dest="procedure_cmd",
        required=True,
    )

    sp = procedure_sub.add_parser(
        "export",
        help="export learned procedures as JSON",
    )
    sp.add_argument(
        "output",
        nargs="?",
        default=None,
        help="output directory (default: .howdex/procedures)",
    )
    sp.set_defaults(func=cmd_procedure_export)

    sp = procedure_sub.add_parser(
        "import",
        help="import a procedure JSON file or directory",
    )
    sp.add_argument("source")
    sp.set_defaults(func=cmd_procedure_import)

    codex_parser = sub.add_parser(
        "codex",
        help="manage the local portable procedure registry",
    )
    codex_sub = codex_parser.add_subparsers(dest="codex_cmd", required=True)

    sp = codex_sub.add_parser("init", help="create a local Codex folder")
    sp.add_argument(
        "codex_path",
        nargs="?",
        default=None,
        help="Codex directory (default: .howdex/codex)",
    )
    sp.set_defaults(func=cmd_codex_init)

    sp = codex_sub.add_parser(
        "publish",
        help="publish learned procedures to the local Codex",
    )
    sp.add_argument(
        "codex_path",
        nargs="?",
        default=None,
        help="Codex directory (default: .howdex/codex)",
    )
    sp.set_defaults(func=cmd_codex_publish)

    sp = codex_sub.add_parser(
        "pull",
        help="import procedures from another local Codex",
    )
    sp.add_argument("source")
    sp.set_defaults(func=cmd_codex_pull)

    sp = sub.add_parser("forget", help="delete a memory")
    sp.add_argument("memory_id")
    sp.set_defaults(func=cmd_forget)

    sub.add_parser("vacuum", help="GC expired memories + tombstones").set_defaults(func=cmd_vacuum)

    sp = sub.add_parser("export", help="export all memories to JSON")
    sp.add_argument("output")
    sp.set_defaults(func=cmd_export)

    sub.add_parser("mcp", help="start MCP server (stdio)").set_defaults(func=cmd_mcp)

    return p



def cmd_health(args):
    """Run Howdex production healthcheck."""
    proc = subprocess.run([sys.executable, "-m", "howdex.health"])
    return proc.returncode


def cmd_eval(args):
    """Run Howdex benchmark suites."""
    root = Path.cwd()

    suites = {
        "swe-repeat": root / "benchmarks" / "swe_repeat_benchmark.py",
        "swe-repeat-multi": root / "benchmarks" / "swe_repeat" / "runner.py",
        "swe-repeat-9": root / "benchmarks" / "swe_repeat" / "runner.py",
        "real-repo": root / "benchmarks" / "real_repo_repair_benchmark.py",
        "oss-repo": root / "benchmarks" / "oss_repo_repair_benchmark.py",
    }

    script = suites.get(args.suite)

    if script is None:
        print(f"Unknown eval suite: {args.suite}")
        return 1

    if not script.exists():
        print(f"Missing benchmark script: {script}")
        return 1

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run([sys.executable, str(script)], env=env)
    return proc.returncode


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
