# Consolidate hand-derived env-subdomain expressions onto `compiled.subdomain`

The compiler already computes the env subdomain `<env>.<project>.<apex_domain>`
at `cicl/compile.py:369` and carries it as `compiled.subdomain` (see
`cicl/model.py:419`). Two other sites re-derive the same expression by hand
instead of reading the carried field:

- `orchestrate/aggregate.py:54` (`_host_for`) — `f"{env}.{dns_label(ctx.project.name)}.{apex}"`
- `orchestrate/up.py:211-212` — `f"{env}.{project_seg}.{apex_domain}"`

Every copy is a reader — there is no emitter in this family — so a drift fails
loudly ("one command talks to the wrong host") rather than silently addressing a
resource nothing created. Low severity, but real duplication of a value the
compiler already owns.

## Changes to make

1. Have `_host_for` and `up.py` read `compiled.subdomain` and delete their
   hand-rolled expressions.
2. `_host_for` takes a `ProjectContext`, which does not currently expose the
   compiled infra — thread `compiled.subdomain` (or the compiled object) in
   rather than swapping a one-liner. `up.py` needs the same.
3. Grep for the expression again after the fix — the count is found by grepping,
   never by predicting, and it has already grown once. Related cousins build the
   *project*/*stage* variant (`stagetest.py:93` → `stage.<project>.<apex>`;
   `bootstrap.py:204`, `emit/hcl.py:1210` → bare `<project>.<apex>`); those are a
   distinct expression, worth a glance but not necessarily this consolidation.
