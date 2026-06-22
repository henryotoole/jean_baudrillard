---
stratum: conditional
---
# Skills and the Doctrine

This file gives an overview of how the "thread skills" attached to the doctrine are structured, written, tested, and formatted.

Thread skills provide coverage for the [conditional stratum](../doctrine.md#strata) of the doctrine's information. Such skills take the form of *router + thread*; they provide links to relevant doctrine documents for an action and a thread of narrative to tie those links together. See [this overview](../doctrine.md#skills) for more info on the *content* a thread skill should cover and action-based trigger philosophy.

## Structure

All skills are stored in the $jb/skills folder. They follow standard Anthropic practices for structure e.g. a folder with the skill name with `SKILL.md` inside. Any mechanism that loads a skill does so without moving the skill folder; this prevents broken relative links from a skill to the doctrine.

"Thread" skills are distinguished by the presence of additional metadata in the SKILL.md YAML frontmatter e.g.:
```yml
metadata:
  type: thread
```

## Form

All skills are formed in accordance with the Anthropic-endorsed [Agent Skills Standard](https://agentskills.io/home). Most critically, all skills have standard-prescribed YAML frontmatter which provides *metadata* for the skill. The most critical of these fields is the *description*, which is an always-in-context description of the skill's purpose. They should be authored as crisp, slightly "pushy" activity triggers.

The body of a thread skill has a loosely defined standard shape. Thread skills should generally contain one `#` H1 (the skill name) plus a short intro stating the router intent.

It should be followed by the mandatory `## General Information` H2 section. This section should start with a short line noting that the section contains critical orienting information and **an instruction to read all referenced files now**. The rest of the section should catalog links to relevant files.

Then, if there are relevant specifics for the thread skill, the `## Specific Information` H2 should follow. It should start with a short line noting that the section contains detailed specifics and mechanisms and **an instruction that the referenced files should be read on demand**. The rest of the section should catalog links to relevant files.

Lastly, a `## Thread` H2 can follow containing the "thread" that binds the references together: read-order, how files interact, and the boundary calls to sibling skills.

### References

References from all skills to doctrine files should take the form: `[filename.md](../../doctrine/path/to/file.md)`.

References to *sibling skills* are plain code-formatted names (`cicd-pipeline`), not file links.

## Loading Mechanism

Skills must be made available to agents. The mechanism varies depending on the harness being used. This section will have a subsection for each harness that the doctrine has yet been designed to work with.

Agents discover and trigger skills through the always-in-context skill metadata. 

### Anthropic via Claude Code

Skills are made available to claude code via the *plugin* mechanism. The doctrine's git repo ships with a plugin definition at:

`$jb/.claude-plugin/plugin.json`

This plugin ought to be configured in global user settings so that skills are always available. 

## Maintenance

Thread skill bodies route into the doctrine and doctrine files remain the single source of truth. A doctrine edit only requires that thread skill pointers still resolve. Two meta-skills enforce health on a cadence rather than at authoring time:
+ `cohere` - assesses doctrine internal conceptual integrity and thread-skill-based coverage. See `$jb/skills/cohere/SKILL.md` for more info.
+ `skill-evaluation` - tests the actual performance of individual skills with both trigger and outcome evals. See [below](#testing)

### Testing

Testing all skills is done in accordance with the vendored Anthropic skill-eval standard. The structure for these tests lives in `$jb/skill_eval`. 