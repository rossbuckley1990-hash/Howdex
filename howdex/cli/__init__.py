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
    howdex codex lint <path>            # lint Codex entries
    howdex codex policy-check <path>    # check Codex policy metadata
    howdex registry init <path>         # create a Codex registry layout
    howdex forget <id>                  # delete a memory
    howdex vacuum                       # GC expired + tombstoned
    howdex mcp                          # start MCP server (stdio)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

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
    print("\nNext: howdex remember \"Hello, world\"")
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
            print(
                f"    confidence={p.confidence:.2f}  "
                f"success={p.success_count}/{p.support_count}  "
                f"steps={len(p.steps)}"
            )
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
        print("  per layer:")
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
            print(
                f"  id={p.id[:8]}  confidence={p.confidence:.2f}  "
                f"success={p.success_count}/{p.support_count}  uses={p.use_count}"
            )
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
        result = mem.publish_codex(
            args.codex_path,
            require_signed_receipt=args.require_signed_receipt,
        )
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


def _print_governance_report(report) -> None:
    if not report.findings:
        print("✓ no governance findings")
        return
    for finding in report.findings:
        print(finding.format())


def cmd_codex_lint(args: argparse.Namespace) -> int:
    from howdex.codex_governance import lint_codex

    report = lint_codex(args.codex_path, hmac_key=args.hmac_key)
    _print_governance_report(report)
    if report.ok:
        print("✓ codex lint passed")
        return 0
    return 1


def cmd_codex_diff(args: argparse.Namespace) -> int:
    from howdex.codex_governance import diff_codex_entries

    lines = diff_codex_entries(args.left, args.right)
    if not lines:
        print("✓ no governance-relevant differences")
        return 0
    print("\n".join(lines))
    return 1


def cmd_codex_merge(args: argparse.Namespace) -> int:
    from howdex.codex_governance import merge_codex_entries

    merged, messages = merge_codex_entries(
        args.left,
        args.right,
        args.output,
        interactive=args.interactive,
    )
    if not merged:
        print("✗ merge blocked by governance conflict")
        for message in messages:
            print(f"- {message}")
        return 1
    print(f"✓ merged Codex entry written to {args.output}")
    return 0


def cmd_codex_verify(args: argparse.Namespace) -> int:
    from howdex.codex_governance import verify_codex

    report = verify_codex(args.codex_path, hmac_key=args.hmac_key)
    _print_governance_report(report)
    if report.ok:
        print("✓ codex verify passed")
        return 0
    return 1


def cmd_codex_deprecate(args: argparse.Namespace) -> int:
    from howdex.codex_governance import deprecate_entry

    path = deprecate_entry(
        args.entry_id,
        args.reason,
        codex_path=args.codex_path,
    )
    print(f"✓ deprecated {args.entry_id} in {path}")
    return 0


def cmd_codex_trust(args: argparse.Namespace) -> int:
    from howdex.codex_governance import set_trust_level

    path = set_trust_level(
        args.entry_id,
        args.level,
        codex_path=args.codex_path,
    )
    print(f"✓ set {args.entry_id} trust level to {args.level} in {path}")
    return 0


def cmd_codex_policy_check(args: argparse.Namespace) -> int:
    from howdex.codex_governance import policy_check_codex

    report = policy_check_codex(args.codex_path)
    _print_governance_report(report)
    if report.ok:
        print("✓ codex policy-check passed")
        return 0
    return 1


def _print_registry_findings(findings) -> None:
    if not findings:
        print("✓ no registry findings")
        return
    for finding in findings:
        print(finding.format())


def cmd_registry_init(args: argparse.Namespace) -> int:
    from howdex.registry import registry_init

    result = registry_init(args.registry_path)
    print(f"✓ initialized registry at {result['root']}")
    return 0


def cmd_registry_index(args: argparse.Namespace) -> int:
    from howdex.registry import registry_index

    result = registry_index(args.registry_path)
    print(
        json.dumps(
            {
                "entries": result["entries"],
                "root": str(result["root"]),
                "root_hash": result["root_hash"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_registry_verify(args: argparse.Namespace) -> int:
    from howdex.registry import registry_verify

    result = registry_verify(args.registry_path)
    _print_registry_findings(result.findings)
    if result.ok:
        print("✓ registry verify passed")
        return 0
    return 1


def cmd_registry_pull(args: argparse.Namespace) -> int:
    from howdex.registry import registry_pull

    result = registry_pull(args.source, args.to)
    print(
        json.dumps(
            {
                "entries": result["entries"],
                "root": str(result["root"]),
                "root_hash": result["root_hash"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_registry_add(args: argparse.Namespace) -> int:
    from howdex.registry import registry_add

    result = registry_add(args.procedure_json, args.to)
    print(f"✓ added {result['path']} to registry {result['root']}")
    return 0


def cmd_registry_trust_policy(args: argparse.Namespace) -> int:
    from howdex.registry import registry_trust_policy

    print(json.dumps(registry_trust_policy(args.registry_path), indent=2, sort_keys=True))
    return 0


def cmd_receipt_import(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        receipt = mem.import_signed_attestation(
            args.source,
            procedure_id=args.procedure_id,
            key_material=args.hmac_key,
        )
        signed = receipt.metadata.get("attestation_status") == "signed_verified"
        label = "signed verified" if signed else receipt.metadata.get("attestation_status", receipt.status)
        print(f"✓ imported receipt {receipt.receipt_id} ({label})")
        return 0
    finally:
        mem.close()


def cmd_receipt_verify(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        result = mem.verify_receipt_file(args.source, key_material=args.hmac_key)
        print(
            json.dumps(
                {
                    "status": result.status,
                    "evidence_valid": result.evidence_valid,
                    "payload_hash_valid": result.payload_hash_valid,
                    "signature_valid": result.signature_valid,
                    "reasons": result.reasons,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if result.status in {"signed_verified", "evidence_observed"} else 1
    finally:
        mem.close()


def cmd_procedure_status(args: argparse.Namespace) -> int:
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        status = mem.procedure_status(args.procedure_id)
        verification_status = mem.procedure_verification_status(args.procedure_id)
        receipts = mem.list_receipts(args.procedure_id)
        signed_receipts = [
            receipt
            for receipt in receipts
            if receipt.metadata.get("attestation_status") == "signed_verified"
        ]
        print(
            json.dumps(
                {
                    "procedure_id": args.procedure_id,
                    "status": status,
                    "verification_status": verification_status,
                    "receipt_count": len(receipts),
                    "signed_verified_receipt_count": len(signed_receipts),
                },
                indent=2,
                sort_keys=True,
            )
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


def cmd_drift(args: argparse.Namespace) -> int:
    """Detect procedures with low canonical confidence (brittleness check)."""
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        at_risk = mem.detect_canonicalization_drift(
            min_confidence=args.min_confidence,
        )
        if not at_risk:
            print(f"✓ no procedures with canonical confidence < {args.min_confidence}")
            return 0
        print(f"⚠ {len(at_risk)} procedure(s) with low canonical confidence:")
        for entry in at_risk:
            print(f"  {entry['task_signature']} (id={entry['procedure_id'][:8]})")
            print(f"    at_risk_steps: {entry['at_risk_steps']}/{entry['total_steps']}")
            print(f"    min_confidence: {entry['min_confidence']}")
            print(f"    suggestion: {entry['suggestion']}")
        return 0
    finally:
        mem.close()


def cmd_system_prompt(args: argparse.Namespace) -> int:
    """Print a system-prompt snippet that tells an LLM to honor Howdex guidance."""
    from howdex.core.agent_guidance import render_system_prompt_snippet
    snippet = render_system_prompt_snippet(
        strict=args.strict,
        max_guidance_chars=args.max_chars,
    )
    print(snippet)
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    """Merkle ledger operations: verify, root, export, attest."""
    from howdex import Howdex
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        ledger = mem.ledger()

        if args.ledger_cmd == "verify":
            valid, error = ledger.verify()
            if valid:
                print(f"✓ Ledger integrity verified")
                print(f"  Blocks: {ledger.block_count()}")
                print(f"  Chain root: {ledger.chain_root()}")
                return 0
            else:
                print(f"✗ LEDGER TAMPERED: {error}", file=sys.stderr)
                return 1

        elif args.ledger_cmd == "root":
            print(ledger.chain_root())

        elif args.ledger_cmd == "export":
            fmt = args.format
            output = args.output or f"ledger_export.{fmt}"
            path = ledger.export(output, fmt=fmt)
            print(f"✓ Exported {ledger.block_count()} blocks to {path}")
            valid, _ = ledger.verify()
            print(f"  Chain root: {ledger.chain_root()}")
            print(f"  Integrity: {'✅ verified' if valid else '❌ tampered'}")
            return 0

        elif args.ledger_cmd == "attest":
            import json as _json
            attestation = ledger.attest(hmac_key=args.hmac_key)
            print(_json.dumps(attestation, indent=2, default=str))
            return 0

        elif args.ledger_cmd == "stats":
            blocks = ledger.get_blocks(start=0, limit=100000)
            event_counts: dict[str, int] = {}
            for b in blocks:
                et = b["event_type"]
                event_counts[et] = event_counts.get(et, 0) + 1
            print(f"Ledger stats:")
            print(f"  Total blocks: {len(blocks)}")
            print(f"  Chain root:   {ledger.chain_root()[:24]}...")
            valid, _ = ledger.verify()
            print(f"  Integrity:    {'✅ verified' if valid else '❌ tampered'}")
            print(f"  Events:")
            for et, count in sorted(event_counts.items()):
                print(f"    {et}: {count}")
            return 0

        else:
            print(f"unknown ledger subcommand: {args.ledger_cmd}", file=sys.stderr)
            return 1
    finally:
        mem.close()


def cmd_compliance(args: argparse.Namespace) -> int:
    """Generate a compliance report mapping receipts to a framework's controls."""
    from howdex.governance import ComplianceReport, SUPPORTED_FRAMEWORKS
    if args.framework not in SUPPORTED_FRAMEWORKS:
        print(f"error: framework must be one of {SUPPORTED_FRAMEWORKS}", file=sys.stderr)
        return 1
    mem = Howdex(path=args.path, embedder=args.embedder)
    try:
        report = ComplianceReport.generate(
            mem,
            framework=args.framework,
            reporting_period_start=args.period_start,
            reporting_period_end=args.period_end,
        )
        if args.output:
            path = report.to_file(args.output)
            print(f"✓ {args.framework.upper()} report written to {path}")
            print(f"  report_hash: {report.report_hash}")
        else:
            print(report.to_markdown())
        return 0
    finally:
        mem.close()


def cmd_registry(args: argparse.Namespace) -> int:
    """Pull, list, search, or push to the public Howdex procedure registry."""
    from howdex import public_registry as registry_mod
    if args.registry_cmd == "pull":
        result = registry_mod.registry_pull(args.to, registry_url=args.url)
        if result.get("error"):
            print(f"✗ {result['error']}", file=sys.stderr)
            return 1
        print(f"✓ pulled {result['pulled']} procedure(s) to {result['target']}")
        return 0
    elif args.registry_cmd == "list":
        entries = registry_mod.registry_list(args.from_dir)
        if not entries:
            print("(no procedures in registry)")
            return 0
        print(f"{'ID':<40} {'STATUS':<12} {'TITLE':<30}")
        for e in entries:
            print(f"{e['id']:<40} {e['status']:<12} {e['title'][:30]}")
        return 0
    elif args.registry_cmd == "search":
        results = registry_mod.registry_search(args.query, args.from_dir)
        if not results:
            print("(no matches)")
            return 0
        print(f"{'SCORE':<6} {'STATUS':<12} {'TITLE':<30}")
        for r in results:
            print(f"{r['score']:<6} {r['status']:<12} {r['title'][:30]}")
        return 0
    elif args.registry_cmd == "push":
        result = registry_mod.registry_push(args.source, args.to)
        print(f"✓ pushed {result['pushed']} verified procedure(s) to {result['target']}")
        if result["skipped_unverified"]:
            print(f"  skipped {result['skipped_unverified']} unverified (registry requires status=verified)")
        if result["skipped_lint"]:
            print(f"  skipped {result['skipped_lint']} that failed governance lint (no receipt material)")
        return 0
    else:
        print(f"unknown registry subcommand: {args.registry_cmd}", file=sys.stderr)
        return 1


def cmd_mcp(args: argparse.Namespace) -> int:
    """Start the MCP server over stdio."""
    from howdex.mcp.server import run_stdio
    run_stdio(
        path=args.db or args.path,
        embedder=args.embedder,
        codex_path=args.codex,
        readonly=args.readonly,
    )
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
    p.add_argument(
        "--require-receipt",
        action="store_true",
        help="Strict mode: end_session('success') without a verified receipt "
             "is downgraded to 'unverified'. Prevents hallucinated successes "
             "from being consolidated into procedures.",
    )

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
                    choices=[layer.value for layer in MemoryLayer])
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
        sp.add_argument("--layer", default=None, choices=[layer.value for layer in MemoryLayer])
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

    sp = procedure_sub.add_parser(
        "status",
        help="show receipt-backed status for one procedure",
    )
    sp.add_argument("procedure_id")
    sp.set_defaults(func=cmd_procedure_status)

    receipt_parser = sub.add_parser(
        "receipt",
        help="import or verify procedure receipt attestations",
    )
    receipt_sub = receipt_parser.add_subparsers(dest="receipt_cmd", required=True)

    sp = receipt_sub.add_parser(
        "import",
        help="import a signed or unsigned attestation JSON file",
    )
    sp.add_argument("source")
    sp.add_argument("--procedure-id", default=None)
    sp.add_argument(
        "--hmac-key",
        default=None,
        help="HMAC key material used to verify hmac-sha256 attestations",
    )
    sp.set_defaults(func=cmd_receipt_import)

    sp = receipt_sub.add_parser(
        "verify",
        help="verify a signed or unsigned attestation JSON file",
    )
    sp.add_argument("source")
    sp.add_argument(
        "--hmac-key",
        default=None,
        help="HMAC key material used to verify hmac-sha256 attestations",
    )
    sp.set_defaults(func=cmd_receipt_verify)

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
    sp.add_argument(
        "--require-signed-receipt",
        action="store_true",
        help="publish only procedures with a signed verified receipt",
    )
    sp.set_defaults(func=cmd_codex_publish)

    sp = codex_sub.add_parser(
        "pull",
        help="import procedures from another local Codex",
    )
    sp.add_argument("source")
    sp.set_defaults(func=cmd_codex_pull)

    sp = codex_sub.add_parser(
        "lint",
        help="lint Codex entries for schema, proof, source, and policy hygiene",
    )
    sp.add_argument("codex_path")
    sp.add_argument("--hmac-key", default=None)
    sp.set_defaults(func=cmd_codex_lint)

    sp = codex_sub.add_parser(
        "diff",
        help="show governance-relevant differences between two Codex entries",
    )
    sp.add_argument("left")
    sp.add_argument("right")
    sp.set_defaults(func=cmd_codex_diff)

    sp = codex_sub.add_parser(
        "merge",
        help="merge two Codex entries when no semantic conflict is detected",
    )
    sp.add_argument("--interactive", action="store_true")
    sp.add_argument("left")
    sp.add_argument("right")
    sp.add_argument("--output", required=True)
    sp.set_defaults(func=cmd_codex_merge)

    sp = codex_sub.add_parser(
        "verify",
        help="verify Codex proof and governance metadata",
    )
    sp.add_argument("codex_path")
    sp.add_argument("--hmac-key", default=None)
    sp.set_defaults(func=cmd_codex_verify)

    sp = codex_sub.add_parser(
        "deprecate",
        help="mark a Codex entry deprecated with a reason",
    )
    sp.add_argument("entry_id")
    sp.add_argument("--reason", required=True)
    sp.add_argument("--codex-path", default="codex")
    sp.set_defaults(func=cmd_codex_deprecate)

    sp = codex_sub.add_parser(
        "trust",
        help="set a conservative trust level for a Codex entry",
    )
    sp.add_argument("entry_id")
    sp.add_argument("--level", required=True, choices=["candidate", "verified", "blocked"])
    sp.add_argument("--codex-path", default="codex")
    sp.set_defaults(func=cmd_codex_trust)

    sp = codex_sub.add_parser(
        "policy-check",
        help="check Codex entries for policy approval and banned command hazards",
    )
    sp.add_argument("codex_path")
    sp.set_defaults(func=cmd_codex_policy_check)

    registry_parser = sub.add_parser(
        "registry",
        help="manage protocol-first Howdex Codex registries",
    )
    registry_sub = registry_parser.add_subparsers(dest="registry_cmd", required=True)

    sp = registry_sub.add_parser(
        "init",
        help="create a local Codex registry layout",
    )
    sp.add_argument("registry_path")
    sp.set_defaults(func=cmd_registry_init)

    sp = registry_sub.add_parser(
        "index",
        help="rebuild registry indexes and manifest counts",
    )
    sp.add_argument("registry_path")
    sp.set_defaults(func=cmd_registry_index)

    sp = registry_sub.add_parser(
        "verify",
        help="verify registry manifest, indexes, schemas, root hash, and signatures",
    )
    sp.add_argument("registry_path")
    sp.set_defaults(func=cmd_registry_verify)

    sp = registry_sub.add_parser(
        "pull",
        help="copy a local or file:// registry into another local registry",
    )
    sp.add_argument("source")
    sp.add_argument("--to", required=True)
    sp.set_defaults(func=cmd_registry_pull)

    sp = registry_sub.add_parser(
        "add",
        help="add one procedure JSON entry to a registry",
    )
    sp.add_argument("procedure_json")
    sp.add_argument("--to", required=True)
    sp.set_defaults(func=cmd_registry_add)

    sp = registry_sub.add_parser(
        "trust-policy",
        help="print the registry trust_policy manifest field",
    )
    sp.add_argument("registry_path")
    sp.set_defaults(func=cmd_registry_trust_policy)

    sp = sub.add_parser("forget", help="delete a memory")
    sp.add_argument("memory_id")
    sp.set_defaults(func=cmd_forget)

    sub.add_parser("vacuum", help="GC expired memories + tombstones").set_defaults(func=cmd_vacuum)

    # Architectural-hardening subcommands
    sp = sub.add_parser(
        "drift",
        help="detect procedures with low canonical confidence (brittleness check)",
    )
    sp.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        help="flag steps with canonical_confidence below this threshold",
    )
    sp.set_defaults(func=cmd_drift)

    sp = sub.add_parser(
        "system-prompt",
        help="print a system-prompt snippet that tells an LLM to honor Howdex guidance",
    )
    sp.add_argument(
        "--strict",
        action="store_true",
        help="emit the strict variant (forbids claiming success without a verifier)",
    )
    sp.add_argument(
        "--max-chars",
        type=int,
        default=6000,
        help="the guidance char budget to advertise to the LLM",
    )
    sp.set_defaults(func=cmd_system_prompt)

    # Merkle ledger subcommands (the cryptographic audit trail)
    ledger_parser = sub.add_parser(
        "ledger",
        help="Merkle audit ledger: verify, root, export, attest, stats",
    )
    ledger_sub = ledger_parser.add_subparsers(dest="ledger_cmd", required=True)

    ledger_sub.add_parser("verify", help="verify chain integrity (tamper detection)").set_defaults(func=cmd_ledger)
    ledger_sub.add_parser("root", help="print the current chain root (memory fingerprint)").set_defaults(func=cmd_ledger)
    ledger_sub.add_parser("stats", help="show ledger statistics").set_defaults(func=cmd_ledger)

    ledger_export = ledger_sub.add_parser("export", help="export the ledger for external audit")
    ledger_export.add_argument("--format", choices=["json", "soc2", "csv"], default="json")
    ledger_export.add_argument("--output", default=None)
    ledger_export.set_defaults(func=cmd_ledger)

    ledger_attest = ledger_sub.add_parser("attest", help="create a signed attestation of the chain root")
    ledger_attest.add_argument("--hmac-key", default=None, help="HMAC key for signing")
    ledger_attest.set_defaults(func=cmd_ledger)

    # Governance / compliance subcommands (the unicorn wedge)
    sp = sub.add_parser(
        "compliance",
        help="generate a compliance report (SOC 2, EU AI Act, NIST AI RMF)",
    )
    sp.add_argument(
        "--framework",
        required=True,
        choices=["soc2", "eu-ai-act", "nist-ai-rmf"],
        help="compliance framework to map receipts against",
    )
    sp.add_argument("--output", default=None, help="write report to file (default: stdout)")
    sp.add_argument("--period-start", default=None, help="reporting period start (ISO 8601)")
    sp.add_argument("--period-end", default=None, help="reporting period end (ISO 8601)")
    sp.set_defaults(func=cmd_compliance)

    # Public registry subcommands (the network-effect seed)
    # Named "public-registry" to avoid conflict with the existing "registry"
    # subparser (which implements the local Codex registry protocol).
    reg_parser = sub.add_parser(
        "public-registry",
        help="pull/list/search/push the PUBLIC Howdex procedure registry",
    )
    reg_sub = reg_parser.add_subparsers(dest="registry_cmd", required=True)

    reg_pull = reg_sub.add_parser("pull", help="pull the public registry to a local directory")
    reg_pull.add_argument("--to", required=True, help="local target directory")
    reg_pull.add_argument("--url", default=None, help="registry URL (default: $HOWDEX_REGISTRY_URL)")
    reg_pull.set_defaults(func=cmd_registry)

    reg_list = reg_sub.add_parser("list", help="list procedures in a local registry")
    reg_list.add_argument("--from-dir", required=True, help="local registry directory")
    reg_list.set_defaults(func=cmd_registry)

    reg_search = reg_sub.add_parser("search", help="search procedures in a local registry")
    reg_search.add_argument("query", help="search query")
    reg_search.add_argument("--from-dir", required=True, help="local registry directory")
    reg_search.set_defaults(func=cmd_registry)

    reg_push = reg_sub.add_parser("push", help="push verified procedures to a registry directory")
    reg_push.add_argument("source", help="source procedures directory (Codex procedures/)")
    reg_push.add_argument("--to", required=True, help="target registry directory")
    reg_push.set_defaults(func=cmd_registry)

    sp = sub.add_parser("export", help="export all memories to JSON")
    sp.add_argument("output")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("mcp", help="start MCP server (stdio)")
    sp.add_argument(
        "--db",
        default=None,
        help="database path (default: $HOWDEX_HOME/howdex.db or ~/.howdex/howdex.db)",
    )
    sp.add_argument(
        "--codex",
        default=None,
        help="local Codex directory or JSON entry file to expose for guidance/search",
    )
    sp.add_argument(
        "--readonly",
        action="store_true",
        help="disable mutating MCP tools",
    )
    sp.set_defaults(func=cmd_mcp)

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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
