---
name: transcript-summary
description: This skill describes how to summarize the transcript of an agent session's run, especially when subagents are involved. Use this skill when you are trying to assess an agent session's run for usage.
metadata:
  type: conventional
---

This skill is likely to grow in the future, but for now it just describes how to use some executor tooling to get good cost usage summaries.

## Token & cost usage by subagent

To break down a session's token usage and cost per subagent — with the full agent hierarchy, chronological spawn order, and a cost-weighted usage chart — run the executor:

```
python3 <skill>/executor/token_metrics.py <session-id | path/to/session.jsonl>
```

Pass a bare session id (resolved under `~/.claude/projects/*/`) or a path to the main `.jsonl`. Add `--json` for a structured breakdown to pipe elsewhere, or `--width=N` to size the usage bar.

The chart is **cost-weighted** — each shaded segment is that agent's share of dollar cost, not raw token count (raw counts are ~96% cache-read and would render as a solid bar). Ranks and names come from each subagent's recorded `agentType` (`jean-baudrillard:<rank>:<name>` for chain-of-command agents). The one maintenance point is the rate table at the top of the script — keep it current with published per-model pricing.

