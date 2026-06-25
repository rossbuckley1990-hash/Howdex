# Howdex external pilot outreach

This pack prepares Howdex for real pilot outreach. It does not claim that any
post has been made, any stranger has used Howdex, or any external adoption
exists.

## Launch checklist

- Re-read the current README and benchmark caveats.
- Confirm the repo installs and tests locally.
- Confirm the Docker n20 benchmark cited in README is still the latest
  committed benchmark evidence before quoting it.
- Choose one community at a time.
- Read that community's posting rules manually before posting.
- Edit the draft to match the community's tone and rules.
- Avoid duplicate posting, brigading, or cross-post spam.
- Post from a real maintainer account.
- Record the posted link in `launch/tracking/PILOT_TRACKING.md`.
- Track any real external issue, PR, procedure submission, or verified receipt
  only after it exists.

## Target communities to research manually before posting

Research each community's current rules before posting. Do not assume these are
acceptable venues without checking.

- Hacker News Show HN.
- r/LocalLLaMA, if the rules allow open-source agent tooling posts.
- r/MachineLearning, only if rules allow project posts and the post is technical
  enough.
- r/opensource, if project-showcase rules permit it.
- r/selfhosted, only if the local-first MCP/Codex angle is relevant and allowed.
- LangChain/LangGraph community forums or Discord channels, where project
  announcements are allowed.
- MCP community channels, where local tool-server projects are allowed.
- Agent framework Discords or forums with explicit showcase channels.
- Awesome-agent, awesome-mcp, or open-source AI tooling directories, after
  reading their contribution rules.

## Posting rules reminder

- Read and follow each community's rules.
- Do not spam.
- Do not repost the same copy everywhere.
- Do not imply endorsement by a community, directory, framework, or company.
- Do not claim external users, pilots, adoption, traction, or market validation
  until those are tracked with links.
- Do not claim production-safe autonomous execution.
- Do not claim broad compounding is proven.
- Do not claim live cross-model transfer is proven unless a real committed
  result exists.
- Do not claim Howdex beats AWM, WebArena, Mind2Web, or any other benchmark
  unless measured and linked.

## Allowed claims

- Howdex is an open verification layer for agent know-how.
- Howdex turns execution traces into portable, receipt-backed procedures.
- Procedures are guidance, not executable authority.
- Howdex is local-first and deterministic by default.
- Howdex includes MCP support and optional adapters for common agent runtimes.
- The internal Docker n20 benchmark in README may be cited with its caveats.
- The project is looking for pilot users and real feedback.

## Forbidden claims

- External users exist.
- External pilots have started.
- The project has traction, adoption, or market validation.
- Howdex provides production-safe autonomy.
- Broad compounding has been proven.
- Live cross-model transfer has been proven if only dry-run harnesses exist.
- Howdex beats AWM, WebArena, Mind2Web, or similar benchmarks without measured
  evidence.
- Candidate procedures are verified.
- Every Codex entry is verified.

## How to record links after posting

After Ross manually posts somewhere, update `launch/tracking/PILOT_TRACKING.md` with:

- date;
- channel;
- exact link;
- posted_by;
- status;
- response count or short response summary;
- notes.

Use `status` values such as:

- drafted;
- posted;
- removed;
- discussion-active;
- no-response;
- follow-up-needed.

## How to record first external issue, PR, or procedure submission

Only update the external adoption counter after real external evidence exists.

Record:

- the issue, PR, or procedure submission link;
- whether the contributor is external to the project;
- whether it includes a procedure, receipt, benchmark result, or integration
  report;
- whether the submission was accepted, pending, or rejected;
- any follow-up needed.

Do not count private conversations, likes, upvotes, or vague interest as
confirmed pilot users.
