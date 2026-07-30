---
name: chain-of-command
description: Doctrine for structuring agent teams by rank — choosing whether work goes to a private, corporal, or sergeant subagent, escalating a decision that exceeds an agent's authority, and formatting a turn-end formal response. Use this whenever you are spawning or driving subagents as a ranked team, deciding which rank owns a task, hitting a decision above your authority, or ending a subagent's turn, even if the word "rank" is never used.
metadata:
  type: thread
---

# chain-of-command

Ranked agent teams organize context along an axis orthogonal to subject matter: *rank*, the trade of knowledge breadth against depth that sets an agent's design authority. A task is placed at the rank whose depth/breadth balance it needs; decisions that exceed that authority ripple upward.

## General Information

The whole model lives in one file. **Read it now.**

[`chain_of_command.md`](../../doctrine/chain/chain_of_command.md) — the premise (rank = breadth vs. depth vs. authority), the three ranks (`private` / `corporal` / `sergeant`) and what each is bounded by, decision-ripple escalation, the `COMPLETE` / `RAISE_DECISION` / `FAILED` formal-response enum, and the `agents/${rank}/${name}` implementation layout.