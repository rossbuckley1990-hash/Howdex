# Dogfooding Howdex

Howdex should build Howdex.

The dogfood harness records the execution traces used to implement Howdex
roadmap phases, learns a procedure from each phase, publishes a local candidate
Codex entry, and optionally attaches verifier evidence. Over time this creates
compounding, inspectable evidence for how Howdex itself gets built.

This is local-only. It does not require OpenAI, Docker, a hosted registry, or a
cloud service.

## Why this exists

Howdex is verified agent procedure infrastructure. The strongest way to prove
that is to use Howdex as part of its own build loop:

1. capture the trace of a roadmap phase;
2. learn a reusable procedure from that trace;
3. publish a candidate Codex entry;
4. attach verification evidence when a local check passes;
5. use the learned guidance for the next similar phase.

The goal is not to pretend every phase is automatically solved. The goal is to
make the build process observable, repeatable, and reusable.

## Run a phase through the dogfood loop

Start a phase:

```bash
python scripts/howdex_dogfood.py start \
  --phase "procedure-trust-calibration" \
  --objective "Add procedure trust calibration benchmark"
```

This writes the active phase state to:

```text
.howdex/dogfood/current.json
```

Log steps as the phase progresses:

```bash
python scripts/howdex_dogfood.py step \
  --action "created procedure_trust_calibration_test.py" \
  --observation "added dry-run calibration bins and output schema"
```

End the phase after validation:

```bash
python scripts/howdex_dogfood.py end \
  --outcome success \
  --verifier "python -m pytest" \
  --observed "480 passed"
```

Then ask Howdex for guidance on a similar future phase:

```bash
python scripts/howdex_dogfood.py guidance \
  --objective "Add AWM head-to-head benchmark harness"
```

## What gets stored

The dogfood harness uses a dedicated local database by default:

```text
.howdex/dogfood/howdex.db
```

The active phase state contains:

- phase name;
- objective;
- session id;
- timestamped steps;
- optional metadata.

On `end`, the state file is replayed into Howdex as an episodic session with the
same session id, then `learn(min_samples=1)` runs against the local dogfood
database.

## Codex entries

After learning, the harness publishes procedures to:

```text
.howdex/dogfood/codex
```

Entries are candidate Codex entries by default. A candidate entry is useful
operational memory, but it is not proof.

## Receipts

If `--verifier` and `--observed` are supplied on `end`, the harness attaches a
local verification receipt to the learned procedure.

The harness records the verifier command and observed signal; it does not run
arbitrary verifier commands itself. This keeps the dogfood CLI safe and
predictable. Run the verifier yourself, then pass the observed result.

Unverified procedures stay unverified. Candidate Codex entries are not marked
verified unless the operator explicitly republishes after attaching sufficient
receipt evidence.

## Source artifacts

Guidance excludes source artifacts by default. The dogfood path is meant to
transfer operational procedure memory, not paste code into future prompts.

## Compounding evidence

Each phase can produce:

- an execution trace;
- a learned procedure;
- a candidate Codex entry;
- optional verifier evidence;
- reusable guidance for the next similar phase.

That loop is the compounding claim Howdex should be able to demonstrate: agents
should not start every roadmap phase cold.
