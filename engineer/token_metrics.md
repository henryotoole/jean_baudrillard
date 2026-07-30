# Token Metrics

Simple - a command line program which takes a session ID as an input and produces metrics as an output.

A sample of what I'd like the output to look like is below. It is at heart really just a table, but in text form.

The leftmost tree details the agent hierarchy. The "root" is the toplevel agent and each descendent in the tree is a subagent. 1.1 is a subagent of 1, which is a subagent of root.

The order (top to bottom) should be determined by when that agent was launched. As subagents can persist for a while, the *start time* should be used to order these. We can infer below that 1.2 was launched after 1.1, but before 1.3.

Rank is simply the agent's rank; left blank if the agent is not a doctrine chain-of-command style. Name is the agent's name. Rank can be determined because the full formal name of a doctrine chain-of-command style agent will be `jean-baudrillard:<rank>:<agent-name>`.

The usage chart visualizes the data that's recorded to the right with R/Rr/Rc/W. Each category represents a category of token usage; categories are named in the legend at the very bottom of the output. The chart shows **cost-weighted** proportions: each category's share of the bar reflects its share of that agent's *cost*, not its raw token count. This is deliberate — the chart answers "where did the cost go?". (A count-weighted bar would be near useless: real sessions are ~96%+ cache-read tokens, which are the cheapest category, so the bar would render as an almost-solid ▒.) The "░" character represents R, the "▒" Rr, etc. etc. from left to right.

Example terminal output. Note that the token category percentages are *approximate* (I eyeballed them for the example) as are the input/output/cost numbers.
```
              RANK      NAME                  USAGE CHART           R%   Rr%  Rc%  W%   INPUT OUTPUT COST 
                                                                                                          
.             sergeant  doctrine-advance      ░░░░▒▒▒▒▓▓▓▓███████  (15 / 15 / 15 / 55)  104k  33k    $4.45
├── 1         corporal  mod-developer         ░░░▒▒▒▒▓▓██████████  (15 / 15 / 8  / 62)  99k   3k     $0.37
│   ├── 1.1   private   mod-implementor       ░░▒▒▒▒▓▓▓▓█████████  (7  / 15 / 15 / 63)  144k  14k    $2.24
│   ├── 1.2             general-purpose       ░▒▒▒▒▒▒▓▓▓▓▓▓▓▓▓▓██  ...                                    
│   └── 1.3             general-purpose       ░▒▒▒▒▒▒▓▓▓▓▓▓▓▓████  ...                                    
└── 2         corporal  mod-developer         ░░░▒▒▒▒▓▓▓▓▓▓▓▓▓███  ...                                    
    ├── 2.1   private   mod-implementor       ░░░▒▒▒▓▓▓▓█████████  ...                                    
    └── 2.2             general-purpose       ░▒▒▒▒▓▓▓▓██████████  ...                                    
                                                                                                          
                                                                                                          
                                                                                                          
                                                                                                          
LEGEND                                                                                                    
R  - ░░ input_tokens (uncached input remainder — NOT total input)                                          
Rr - ▒▒ cache_read_input_tokens                                                                            
Rc - ▓▓ cache_creation_input_tokens                                                                        
W  - ██ output_tokens                                                                                      
```

## Cost calculation: four visual categories, five price inputs

The usage chart has four categories, but computing the COST column requires five, because `cache_creation_input_tokens` (Rc) is billed at two different rates depending on the cache TTL. The `usage` object splits it under `cache_creation`:

- `cache_creation.ephemeral_5m_input_tokens` — 5-minute cache writes (≈1.25× the input rate)
- `cache_creation.ephemeral_1h_input_tokens` — 1-hour cache writes (≈2× the input rate)

So the cost of the Rc bucket must be computed from these two sub-fields separately; the single `cache_creation_input_tokens` total is only sufficient for the *visual* proportion, not for the price. The five price inputs are therefore: input (R), cache-read (Rr), cache-write-5m, cache-write-1h, and output (W).

Cost nuances the calculation must handle:
1. **Per-model rates.** Each category's rate depends on `message.model`; pull current rates from a rate table rather than hardcoding. Current rates (input / output per Mtok): Fable 5 $10/$50; Opus 4.6–4.8 $5/$25; Sonnet 4.6/5 $3/$15; Haiku 4.5 $1/$5. Cache multipliers are relative to the input rate: read ×0.1, write-5m ×1.25, write-1h ×2.
2. **No long-context premium (current models).** Current-generation models — Opus 4.6+, Sonnet 4.6+, Fable 5 — price the full 1M context window at the flat input rate. The `[1m]` marker in a model id (e.g. `claude-opus-4-8[1m]`) does **not** imply a premium tier, and cost has no >200k tiering to implement. (Only older Sonnet 4/4.5-era models charged a >200k premium; if the transcript ever contains one of those, tiering would matter — but the flat table above covers everything current.)

Note also: server-side tool surcharges (e.g. web search, priced per use) are **not** recorded in the token `usage` object. Token-derived cost is therefore an exact floor; it will undercount any agent that used such tools.

## Implementation

The executor lives at [`../../skills/transcript-summary/executor/token_metrics.py`](../../skills/transcript-summary/executor/token_metrics.py). It takes a session id (resolved under `~/.claude/projects/*/`) or a path to the main `.jsonl`, reconstructs the subagent tree via each subagent's `.meta.json` `toolUseId` (matched against the `Agent` tool_use in its parent transcript), orders siblings by spawn time, and prints the table above. `--json` emits the same data structured; `--width=N` sets the bar width. The rate table at the top of the file is the one thing to keep current.

**Dedupe usage by `message.id`.** Claude Code writes the same assistant message to the transcript 2–3 times (streaming/continuation artifacts), each copy carrying identical `usage`. Each API response is billed once, so summing every copy overstates cost ~3×. Counting one row per unique `message.id` matches the harness's own `total_cost_usd` to within ~0.1% (validated against `run_outcome.py`'s recorded ground truth across 24 mixed-model sessions; median ratio 0.999). The residual is a slight *under*count — expected, since token-derived cost is a floor that excludes server-side tool surcharges.