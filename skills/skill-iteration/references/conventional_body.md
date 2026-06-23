# Authoring a self-contained skill body

How to write the markdown body of a **self-contained** skill — one that carries its own corpus of knowledge rather than routing into an external one. This is the generic skill-writing guidance (adapted from Anthropic's skill-creator, now forked into this doctrine); read it once the skill's intent and description are settled. (For a **thread** skill that routes into the doctrine, use `thread_body.md` instead — the two are mutually exclusive.)

## Anatomy of a skill

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description required)
│   └── Markdown instructions
└── Bundled resources (optional)
    ├── scripts/     - executable code for deterministic / repetitive tasks
    ├── references/  - docs loaded into context as needed
    └── assets/      - files used in output (templates, icons, fonts)
```

## Progressive disclosure

Skills load in three levels — design the body around them:

1. **Metadata** (name + description) — always in context (~100 words).
2. **SKILL.md body** — in context whenever the skill triggers (under ~500 lines ideal).
3. **Bundled resources** — pulled in as needed (unlimited; scripts can execute without being loaded into context).

Key patterns:

- Keep `SKILL.md` under ~500 lines. Approaching the limit is the signal to add a layer of hierarchy: move detail into `references/` and leave a clear pointer about when to read it.
- Reference bundled files explicitly from `SKILL.md`, with guidance on *when* to read each.
- For large reference files (>300 lines), include a table of contents.
- **Organize multi-variant skills by variant.** When a skill spans several domains or frameworks, put the workflow + selection logic in `SKILL.md` and one reference file per variant, so only the relevant one is read:

  ```
  cloud-deploy/
  ├── SKILL.md            (workflow + selection)
  └── references/
      ├── aws.md
      ├── gcp.md
      └── azure.md
  ```

## Principle of lack of surprise

A skill's contents must not surprise the user relative to how it's described, and must never contain malware, exploit code, or anything that could compromise system security. Don't build skills designed to facilitate unauthorized access, data exfiltration, or other malicious activity. (Benign framing like "roleplay as an X" is fine.)

## Writing patterns

Prefer the **imperative form** in instructions.

**Defining an output format** — be explicit:

```markdown
## Report structure
ALWAYS use this exact template:
# [Title]
## Executive summary
## Key findings
## Recommendations
```

**Examples** — concrete input/output pairs carry a lot of weight:

```markdown
## Commit message format
**Example 1:**
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication
```

## Writing style

Explain to the model *why* things matter rather than leaning on heavy-handed `MUST`/`NEVER` directives. Today's models have good theory of mind; given the reasoning behind an instruction, they generalize past rote rules. If you find yourself writing `ALWAYS` or `NEVER` in all caps or reaching for rigid structures, treat it as a yellow flag — reframe and explain the reasoning instead. Write a draft, then reread it with fresh eyes and cut anything not pulling its weight. Keep the skill general, not overfit to a few specific examples.
