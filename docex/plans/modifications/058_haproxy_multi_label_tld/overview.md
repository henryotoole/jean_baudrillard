# Mod 058 — HAProxy demux multi-label TLD support

Fifth mod of the `001_skill_update` campaign. Closes the planner's "HAProxy
Cannot Handle multi-label TLD's" item — a TODO the doctrine itself already
flagged.

## The bug

The fixed-foundation `web_demux` HAProxy parses the `<project>` segment out of a
request's SNI/Host to forward to `<project>-traefik`. The old Lua took
`parts[#parts - 2]` (3rd-from-last label), which is correct only when the apex is
a single-label TLD (`.com`, `.tech`). For a multi-label TLD (`.co.uk`,
`.com.au`) every position shifts and the parse picks the wrong label — the
request never reaches the project's traefik. `fixed_master_network.md` carried
this as an explicit open TODO ("Multi-label TLDs need the PSL-aware variant
below").

## Fix (doctrine; PSL-aware — operator's chosen approach)

The demux Lua is now **Public Suffix List-aware**. It loads the PSL once at
startup, computes the public suffix of each request domain, derives the apex
(registrable domain = public suffix + 1 label), and returns the label
immediately to its left as the project. This is correct for **any** TLD and
unifies the single- and multi-label cases (no special-casing).

Concretely, in `doctrine/infrastructure/preinfra/fixed_master_network.md`:
- `project_resolver.lua` rewritten: `load_psl` (plain / wildcard `*.` /
  exception `!` rules), `public_suffix_label_count` (full PSL algorithm —
  exceptions win, else longest matching plain/wildcard rule, else the default
  `*` = one label), and a `project_from_host` that uses it.
- The `web_demux` `docker-compose.yml` mounts `public_suffix_list.dat` into the
  container.
- The stand-up instructions add a `curl` of the PSL from publicsuffix.org, with
  a note that it's slow-changing data to refresh occasionally, not every
  stand-up.

The Design-section prose already described the PSL approach ("valid TLDs known
from a public suffix list… remove the TLD, then `[-2]`"); only the Lua had
lagged. No prose contradiction remained to fix beyond removing the TODO comment.

## docex scope

The `web_demux` is operator-managed prerequisite infrastructure — docex does not
generate its config (`docex preinfra` only checks the `docex-ingress` bridge
exists). So docex carries **no logic change**, only a one-comment accuracy fix in
`emit/compose.py` (the project-traefik docstring that described the old
`split('.')[-2]` parse now describes the PSL-aware parse). No tests to run.

## Why PSL over the alternatives

The operator chose full PSL over an operator-maintained apex list or a curated
multi-label-suffix subset: it needs zero per-project/per-apex configuration and
is correct for the whole internet, at the cost of shipping the PSL data file into
the demux container and refreshing it occasionally. For a host that may serve
projects across arbitrary apexes, that generality is worth the one mounted file.
