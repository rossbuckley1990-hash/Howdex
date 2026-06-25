# Enterprise Design Partner Program

## Overview

Howdex is seeking 5-10 Fortune 500 enterprise design partners to pilot the
verification and governance layer for AI agents. This document outlines the
program structure, what partners get, and what we ask in return.

## What partners get

1. **Free Howdex enterprise license** for 12 months (Apache-2.0, so this is
   really about support + design-partner access to the maintainers)

2. **Priority support** — direct Slack channel with the maintainers, 48-hour
   response time on issues, weekly check-ins during the pilot

3. **Compliance report generation** — SOC 2, EU AI Act, NIST AI RMF reports
   from your agent verification receipts, ready for your next audit cycle

4. **Custom framework mapping** — if your compliance team needs a framework
   we don't support yet (ISO 42001, COBIT, FedRAMP), we'll add it

5. **Case study rights** — a co-authored case study showing how your team
   used Howdex to prove agent work was verified (you approve the final text)

6. **Influence on the roadmap** — your use cases directly shape priorities.
   The BootProof gate, compliance reports, and public registry were all
   shaped by real enterprise feedback.

## What we ask

1. **Deploy Howdex** with at least one production agent workload (bug fix,
   infra recovery, data pipeline, etc.)

2. **Use the BootProof verifier gate** — require a deterministic verifier
   before procedures are consolidated

3. **Generate at least one compliance report** — SOC 2, EU AI Act, or
   NIST AI RMF — and share feedback on the control mappings

4. **Provide quarterly feedback** — what worked, what didn't, what's missing

5. **Optionally contribute** verified procedures to the public registry
   (anonymized — no proprietary data)

## Ideal partner profile

- Fortune 500 company in fintech, healthcare, infrastructure, or
  regulated manufacturing
- Currently deploying or piloting AI agents in production
- Has a compliance team that needs to audit agent behavior (SOC 2,
  EU AI Act, NIST AI RMF, ISO 42001)
- Has at least one engineering team willing to integrate Howdex into
  their agent pipeline
- Values open-source and local-first (no cloud lock-in)

## How to apply

Open a GitHub issue with the `design-partner` label, or email
rossbuckley1990-hash@users.noreply.github.com with:

- Company name
- Industry
- Current agent deployment (framework, use case, scale)
- Compliance frameworks you need to satisfy
- Timeline for pilot

## Timeline

- **Month 1**: Integration + first verified procedures
- **Month 2**: Compliance report generation + audit mapping feedback
- **Month 3**: Case study draft + public registry contribution
- **Month 4-12**: Ongoing support + roadmap influence

## Why this matters

The EU AI Act is in force. NIST AI RMF is the US standard. ISO 42001 is
the management system. Enterprises deploying agents need proof that their
agents' work was verified — not just that an LLM claimed success. Howdex
is the only open-source system that provides this proof via the receipt
primitive.

The design partner program is how we validate that the receipt primitive
maps to real compliance needs. Your feedback directly shapes whether
Howdex becomes the standard for agent auditability.
