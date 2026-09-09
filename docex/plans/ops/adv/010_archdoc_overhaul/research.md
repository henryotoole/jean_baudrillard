# Archdoc Overhaul Research

A place for me to prep my research overhaul.

## Docex Needs

### ADR Indexes

it should be possible, and pretty trivial, to generate the ADR indexes with docex.

Perhaps `./bin/docex docs adr` to re-generate ADR indexes.

### Documentation Check

I see this as a dedicated `./bin/docex docs check` command. Simple enough, should describe what, if anything, is wrong and provide an exit code.

This also should be a blocker for `docex check`, I think.

#### Solving Standard Diagrams Against `infra.yml`

Since `infra.yml` describes our infrastructure, the graph it describes should always be a subgraph of the `service` and (since it inherits from `service`) `module` diagrams.

Naturally, `infra.yml` does *not* describe external infra (external actors, 3rd parties) or hex structure so these parts of the C4 diagrams will remain distinct.

Nonetheless, it should be possible to deterministically compare our authored C4 diagrams (in mermaid-form) and `infra.yml` to see if they match or not.

#### Solving Standard Diagrams Against Each Other

`project`, `service`, and `module` diagrams should be able to be deterministically compared to see if they match or not. This is another absolute and fast check we can do to ensure drift has not occurred and that all our docs describe the same thing.

### Reachability Check

One thing that's critical to avoid is the orphaned-but-load-bearing doc. The new way of loading docs no longer loads *all* core docs, just the toplevel ones [ref](./docs.md#llm-agent-usage). So something buried in specifics will never get seen again...

Because routing is strictly top-down, any design doc that no higher-level section or diagram links to is unreachable — an orphaned, invisible, but potentially load-bearing doc. `docex` guards against this mechanically: it enumerates every file under `plans/design`, builds the link graph rooted at the standard docs (the *arc42* files) and the [standard diagrams](#standard-diagrams), and flags any file not reachable from a root. No per-doc frontmatter is required — reachability is computed from the link graph itself. This check runs as a blocking step of `docex check`.

### Missing Standard File

Perhaps some sort check that all our standard doc files exist, and a warning if any non-optional ones do not? This could be a command, that is also run on `docex check` as blocking.