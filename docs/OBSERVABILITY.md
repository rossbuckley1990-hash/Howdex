# Howdex Observability

Howdex can emit optional OpenTelemetry spans for procedural-memory decisions.
This helps teams inspect why operational memory was selected, rendered,
published, rejected, or treated as stale.

OpenTelemetry is optional. Installing Howdex does not require OTel packages;
without them, tracing is a no-op.

```bash
python -m pip install "howdex-ai[otel]"
```

## Why OpenTelemetry matters

Procedural memory is infrastructure. Teams need to answer questions like:

- Which procedure was selected for this task?
- Was it verified, candidate, stale, or incompatible?
- How many procedures were omitted by the context budget?
- Did guidance include source artifacts?
- Which MCP or adapter surface requested the guidance?
- Was a Codex entry published as candidate or verified?

Howdex emits standard OTel spans so these decisions can be inspected with the
same tooling teams already use for services, jobs, and agents.

## Spans Howdex emits

- `howdex.guidance.retrieve`
- `howdex.guidance.select`
- `howdex.guidance.render`
- `howdex.procedure.inject`
- `howdex.codex.search`
- `howdex.codex.publish`
- `howdex.receipt.attach`
- `howdex.policy.evaluate`
- `howdex.staleness.evaluate`

## Example attributes

Howdex emits decision metadata, not raw source or artifacts:

- `howdex.procedure_id`
- `howdex.procedure_status`
- `howdex.receipt_status`
- `howdex.relevance_score`
- `howdex.selected_count`
- `howdex.omitted_count`
- `howdex.guidance_chars`
- `howdex.include_source`
- `howdex.verified_only`
- `howdex.policy_status`
- `howdex.staleness_status`
- `howdex.source_episode_count`
- `howdex.codex_entry_id`
- `howdex.adapter`

## Local console exporter example

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(ConsoleSpanExporter())
)

from howdex import Howdex

memory = Howdex(path="~/.howdex/howdex.db", embedder="hashing")
print(memory.guidance("Recover Docker Compose health endpoint"))
```

## Collector integrations

Howdex does not depend on Datadog, New Relic, Splunk, Honeycomb, Grafana, or
any hosted collector. Configure the standard OpenTelemetry SDK/exporter in your
application or agent runtime, then route spans to the collector your
organization already uses.

## Privacy warning

Do not emit raw source code, command output, secrets, or artifacts as span
attributes. Howdex’s built-in spans use identifiers, counts, statuses, and
scores by default. Source artifacts remain excluded from guidance unless a
caller explicitly opts in with `include_source=True`, and they are not added to
telemetry attributes.
