#!/usr/bin/env python3
"""Summarize token usage and cost by subagent for a Claude Code session.

Given a top-level session (a bare session id, or a path to its `.jsonl`),
reconstruct the subagent tree and print per-agent token usage and cost.

The usage chart is **cost-weighted**: each shaded segment's width is that
category's share of the agent's dollar cost, not its raw token count — it
answers "where did the cost go?". A count-weighted bar would be almost solid
`▒` (cache reads dominate token counts but are the cheapest category).

The tree, ranks, and names come entirely from the on-disk transcript layout:
  ~/.claude/projects/<slug>/<session>.jsonl                       (root/main)
  ~/.claude/projects/<slug>/<session>/subagents/agent-*.jsonl     (subagents)
  ~/.claude/projects/<slug>/<session>/subagents/agent-*.meta.json (metadata)

Each subagent's meta carries {agentType, description, toolUseId, spawnDepth}.
`toolUseId` is the id of the `Agent` tool_use block in the PARENT transcript,
which is how parent->child edges are recovered at any depth.

Usage:
    python3 token_metrics.py <session-id | path/to/session.jsonl> [--json] [--width N]

Exit code is 0 on success, non-zero if the session can't be found.
"""
import glob
import json
import os
import re
import sys

# --- Rate table -------------------------------------------------------------
# $ per 1M tokens: (input, output). KEEP CURRENT — pull from the claude-api
# skill / platform pricing docs whenever models or prices change.
#
# WHY no long-context tiering: current-generation models (Opus 4.6+, Sonnet
# 4.6+, Fable 5) price the full 1M context window at the flat input rate. The
# >200k premium that older Sonnet 4/4.5-era models charged does NOT apply here,
# so cost is a flat per-model calculation with no per-request tiering.
RATES = {
    "claude-fable-5":    (10.0, 50.0),
    "claude-mythos-5":   (10.0, 50.0),
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-opus-4-7":   (5.0, 25.0),
    "claude-opus-4-6":   (5.0, 25.0),
    "claude-opus-4-5":   (5.0, 25.0),
    "claude-sonnet-5":   (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
}
DEFAULT_RATE = (5.0, 25.0)  # unknown model -> assume Opus-tier; flagged in output

CACHE_READ_MULT = 0.1
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.0

# Usage-chart categories, in bar order (left -> right).
CAT_CHARS = "░▒▓█"          # R, Rr, Rc, W
CAT_LABELS = ("R", "Rr", "Rc", "W")
DEFAULT_BAR_WIDTH = 19


def rate_for(model):
    """Return ((input_rate, output_rate), unknown) for a message's model id.

    Strips the `[1m]` long-context marker and any trailing date suffix before
    matching, then falls back to a prefix match, then to DEFAULT_RATE.
    """
    if not model:
        return DEFAULT_RATE, True
    m = model.replace("[1m]", "")
    m = re.sub(r"-\d{8}$", "", m)
    if m in RATES:
        return RATES[m], False
    for key, val in RATES.items():
        if m.startswith(key):
            return val, False
    return DEFAULT_RATE, True


def new_acc():
    return {
        # raw token totals (for the INPUT / OUTPUT columns)
        "in": 0, "cr": 0, "cc": 0, "out": 0,
        # per-category dollar cost (for the chart, %s, and COST column)
        "cost_R": 0.0, "cost_Rr": 0.0, "cost_Rc": 0.0, "cost_W": 0.0,
        "unknown_model": False, "assumed_split": False,
    }


def read_usage(path):
    """Sum an agent's OWN usage from its transcript (not its descendants').

    Uses the top-level `message.usage` per assistant message; the `iterations`
    array mirrors it and is ignored to avoid double-counting.

    WHY dedupe on message id: Claude Code writes the same assistant message to
    the transcript more than once (streaming/continuation artifacts), each copy
    carrying the identical `usage`. Each API response is billed once, so counting
    every copy over-states cost ~3x. Deduping by `message.id` matches the
    harness's own `total_cost_usd` to within ~0.1% (validated against
    run_outcome.py's recorded ground truth).
    """
    acc = new_acc()
    seen = set()
    try:
        fh = open(path)
    except OSError:
        return acc
    with fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            msg = obj.get("message") or {}
            u = msg.get("usage")
            if not u:
                continue
            mid = msg.get("id")
            if mid is not None:
                if mid in seen:
                    continue
                seen.add(mid)
            (in_rate, out_rate), unknown = rate_for(msg.get("model"))
            if unknown:
                acc["unknown_model"] = True

            it = u.get("input_tokens") or 0
            ot = u.get("output_tokens") or 0
            cr = u.get("cache_read_input_tokens") or 0
            cc = u.get("cache_creation_input_tokens") or 0

            split = u.get("cache_creation") or {}
            w5 = split.get("ephemeral_5m_input_tokens")
            w1 = split.get("ephemeral_1h_input_tokens")
            if w5 is None and w1 is None:
                # No TTL split recorded — price the whole write pool at 5m.
                w5, w1 = cc, 0
                if cc:
                    acc["assumed_split"] = True
            else:
                w5, w1 = (w5 or 0), (w1 or 0)

            acc["in"] += it
            acc["out"] += ot
            acc["cr"] += cr
            acc["cc"] += cc
            acc["cost_R"] += it * in_rate / 1e6
            acc["cost_Rr"] += cr * in_rate * CACHE_READ_MULT / 1e6
            acc["cost_Rc"] += (w5 * CACHE_WRITE_5M_MULT + w1 * CACHE_WRITE_1H_MULT) * in_rate / 1e6
            acc["cost_W"] += ot * out_rate / 1e6
    return acc


def costs_tuple(acc):
    return (acc["cost_R"], acc["cost_Rr"], acc["cost_Rc"], acc["cost_W"])


def total_cost(acc):
    return sum(costs_tuple(acc))


# --- Session resolution & tree reconstruction -------------------------------

def find_session(arg):
    """Resolve a session id or path to the main transcript's absolute path."""
    if arg.endswith(".jsonl") and os.path.exists(arg):
        return os.path.abspath(arg)
    base = os.path.expanduser("~/.claude/projects")
    matches = glob.glob(os.path.join(base, "*", f"{arg}.jsonl"))
    if matches:
        return matches[0]
    sys.exit(f"ERROR: session not found: {arg}")


def agent_tool_uses(path):
    """Yield (tool_use_id, timestamp) for every `Agent` spawn in a transcript."""
    try:
        fh = open(path)
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            content = (obj.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Agent":
                    yield b.get("id"), obj.get("timestamp")


def rank_name(agent_type):
    """Split a recorded agentType into (rank, name).

    Doctrine chain-of-command agents record as `jean-baudrillard:<rank>:<name>`.
    Anything else leaves rank blank and uses the whole value as the name.
    """
    if not agent_type:
        return "", "root"
    if agent_type.startswith("jean-baudrillard:"):
        parts = agent_type.split(":")
        if len(parts) >= 3:
            return parts[1], parts[2]
    return "", agent_type


def build_tree(main_path):
    """Return (nodes, edges) for the session.

    nodes: label -> {"meta": dict|None, "acc": usage-acc}
    edges: parent_label -> [(child_label, spawn_ts), ...] sorted by spawn_ts
    Labels are "MAIN" for the root and the agent-<hash> basename otherwise.
    """
    session_dir = main_path[:-len(".jsonl")]
    sub_paths = sorted(glob.glob(os.path.join(session_dir, "subagents", "agent-*.jsonl")))

    def label_path(label):
        if label == "MAIN":
            return main_path
        return os.path.join(session_dir, "subagents", f"{label}.jsonl")

    nodes = {"MAIN": {"meta": None, "acc": read_usage(main_path)}}
    child_by_tool = {}
    for sp in sub_paths:
        label = os.path.basename(sp)[:-len(".jsonl")]
        meta = {}
        try:
            with open(sp[:-len(".jsonl")] + ".meta.json") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            pass
        nodes[label] = {"meta": meta, "acc": read_usage(sp)}
        tid = meta.get("toolUseId")
        if tid:
            child_by_tool[tid] = label

    edges = {}
    for label in nodes:
        for tid, ts in agent_tool_uses(label_path(label)):
            child = child_by_tool.get(tid)
            if child:
                edges.setdefault(label, []).append((child, ts))
    for k in edges:
        edges[k].sort(key=lambda x: x[1] or "")
    return nodes, edges


def order_rows(nodes, edges):
    """DFS from MAIN, assigning tree numbers and glyph prefixes by spawn time."""
    rows = []

    def prefix(stack):
        if not stack:
            return ""
        parts = ["    " if last else "│   " for last in stack[:-1]]
        parts.append("└── " if stack[-1] else "├── ")
        return "".join(parts)

    def walk(label, number, stack):
        left = "." if not stack else prefix(stack) + number
        rows.append({"label": label, "number": number, "left": left})
        kids = edges.get(label, [])
        for i, (child, _ts) in enumerate(kids):
            child_num = str(i + 1) if number == "." else f"{number}.{i + 1}"
            walk(child, child_num, stack + [i == len(kids) - 1])

    walk("MAIN", ".", [])
    # Any subagent we couldn't link to a parent (shouldn't happen) trails at end.
    linked = {r["label"] for r in rows}
    for label in nodes:
        if label not in linked:
            rows.append({"label": label, "number": "?", "left": f"(orphan) {label}"})
    return rows


# --- Formatting -------------------------------------------------------------

def fmt_tok(n):
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1_000:
        return f"{n / 1e3:.0f}k"
    return str(int(n))


def fmt_cost(c):
    if c >= 1:
        return f"${c:,.2f}"
    return f"${c:.3f}"


def usage_bar(costs, width):
    total = sum(costs)
    if total <= 0:
        return " " * width
    raw = [c / total * width for c in costs]
    cells = [int(x) for x in raw]
    order = sorted(range(4), key=lambda i: raw[i] - cells[i], reverse=True)
    for i in range(width - sum(cells)):
        cells[order[i]] += 1
    return "".join(CAT_CHARS[i] * cells[i] for i in range(4))


def pct(costs):
    total = sum(costs)
    if total <= 0:
        return ["-"] * 4
    return [f"{round(c / total * 100)}" for c in costs]


def render_table(nodes, rows, width):
    header = ["", "RANK", "NAME", "USAGE CHART",
              "R%", "Rr%", "Rc%", "W%", "INPUT", "OUTPUT", "COST"]
    body = []
    footnotes = {"unknown": False, "assumed": False}
    for r in rows:
        node = nodes[r["label"]]
        acc = node["acc"]
        rank, name = rank_name((node["meta"] or {}).get("agentType"))
        costs = costs_tuple(acc)
        p = pct(costs)
        footnotes["unknown"] |= acc["unknown_model"]
        footnotes["assumed"] |= acc["assumed_split"]
        body.append([
            r["left"], rank, name, usage_bar(costs, width),
            p[0], p[1], p[2], p[3],
            fmt_tok(acc["in"] + acc["cr"] + acc["cc"]),
            fmt_tok(acc["out"]),
            fmt_cost(total_cost(acc)),
        ])

    # TOTAL row (sum across every agent).
    tot = new_acc()
    for node in nodes.values():
        a = node["acc"]
        for k in ("in", "cr", "cc", "out", "cost_R", "cost_Rr", "cost_Rc", "cost_W"):
            tot[k] += a[k]
    tcosts = costs_tuple(tot)
    tp = pct(tcosts)
    total_row = [
        "TOTAL", "", "", usage_bar(tcosts, width),
        tp[0], tp[1], tp[2], tp[3],
        fmt_tok(tot["in"] + tot["cr"] + tot["cc"]),
        fmt_tok(tot["out"]),
        fmt_cost(total_cost(tot)),
    ]

    all_rows = [header] + body + [total_row]
    # Column widths. Numeric columns (index >= 3) right-align; text left-align.
    widths = [max(len(row[c]) for row in all_rows) for c in range(len(header))]

    def line(cells):
        out = []
        for c, val in enumerate(cells):
            out.append(val.ljust(widths[c]) if c < 3 else val.rjust(widths[c]))
        return "  ".join(out).rstrip()

    lines = [line(header), ""]
    lines += [line(b) for b in body]
    lines += ["", line(total_row)]
    lines += ["", "LEGEND (usage chart is cost-weighted — share of $ cost, not tokens)",
              "R  - ░ input_tokens (uncached input)",
              "Rr - ▒ cache_read_input_tokens",
              "Rc - ▓ cache_creation_input_tokens",
              "W  - █ output_tokens"]
    if footnotes["unknown"]:
        lines.append("NOTE: an unknown model was priced at the Opus-tier default — cost is an estimate.")
    if footnotes["assumed"]:
        lines.append("NOTE: some cache-creation tokens lacked a 5m/1h split and were priced at the 5m rate.")
    return "\n".join(lines)


def to_json(nodes, rows):
    out = []
    for r in rows:
        node = nodes[r["label"]]
        acc = node["acc"]
        rank, name = rank_name((node["meta"] or {}).get("agentType"))
        out.append({
            "number": r["number"],
            "label": r["label"],
            "rank": rank,
            "name": name,
            "description": (node["meta"] or {}).get("description"),
            "spawn_depth": (node["meta"] or {}).get("spawnDepth"),
            "tokens": {
                "input": acc["in"], "cache_read": acc["cr"],
                "cache_creation": acc["cc"], "output": acc["out"],
            },
            "cost": {
                "R": round(acc["cost_R"], 6), "Rr": round(acc["cost_Rr"], 6),
                "Rc": round(acc["cost_Rc"], 6), "W": round(acc["cost_W"], 6),
                "total": round(total_cost(acc), 6),
            },
        })
    return json.dumps(out, indent=2)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    width = DEFAULT_BAR_WIDTH
    for a in argv:
        if a.startswith("--width="):
            width = max(4, int(a.split("=", 1)[1]))
    if not args:
        sys.exit("usage: token_metrics.py <session-id | path.jsonl> [--json] [--width=N]")

    main_path = find_session(args[0])
    nodes, edges = build_tree(main_path)
    rows = order_rows(nodes, edges)
    print(to_json(nodes, rows) if as_json else render_table(nodes, rows, width))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
