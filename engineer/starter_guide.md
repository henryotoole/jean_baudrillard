# Starter Guide

This guide is aimed at the first-time reader of this repository attempting to orient themselves and learn about the doctrine.

## The Repository

This repository is broken into a handful of top level folders. Only one of these actually contains the *doctrine* corpus - the rest is dedicated to machinery, notes, and meta-level documentation. These folders are listed in the table below:

| Folder Name | Purpose |
| ----------- | ------- |
| `agents` | Holds anthropic-style custom agent prompts. |
| `docex` | Holds the prime executor stratum of the doctrine (more on this later). |
| `doctrine` | The root of the actual corpus of doctrine files. |
| `engineer` | Notes from and for my own mind *about* the doctrine and this repository. |
| `setup` | Machinery that "installs" the doctrine and associated tooling into a `claude code` installation. |
| `skill_iter` | Proving-ground for skills. |
| `skills` | [Standard form](https://agentskills.io/specification) skills packaged for AI use. |
| `upgrades` | Meta-machinery used to guide LLM's through upgrading projects from old to new versions of the doctrine. |

Of these, only the `doctrine` folder is important right now. The contents of the other folders have to do with *making this system work*; but the `doctrine` files themselves describe *what this system is* in detail.

## Suggested Approach

The best place to start is unsurprisingly the actual [doctrine overview file](../doctrine/doctrine.md). This file provides the briefest of overviews into *what the doctrine is for* and *how it is fundamentally organized*. Also note the [lexicon](../doctrine/lexicon.md); this file lists the doctrine's fundamentally load-bearing words. Some of these are industry standard, others are bespoke to this doctrine. You may find it handy to return to the lexicon for reference as you read.

Some further clarification is useful here. Each folder within `doctrine` (e.g. `doctrine/infrastructure`) corresponds to a topic:

| Folder Name | Purpose |
| ----------- | ------- |
| `chain` | "Chain of command"-style multi-agent work structure. |
| `charts` | Drawings referenced by other docs (separated into this folder for token efficiency reasons). |
| `hexagonal_architecture` | Canonical definitions of hexagonal architecture, rules, and resulting project structure. |
| `infrastructure` | How infrastructure concerns are handled under the doctrine. |
| `practices` | Code-writing conventions, processes, heuristics, and styles. |
| `skills` | How doctrine-corpus skills are written. |

Of these, the critical folders are `infrastructure`, `practices`, and `hexagonal_architecture`.

> Note that the infrastructure folder itself has a complex sub-structure. Any direct child of the folder e.g. `infrastructure/shape.md` is general; any grandchild e.g. `infrastructure/specifics/release.md` is detailed and specific. I recommend avoiding the details for now. They are designed more for LLM consumption than human and I spend far less time editing them.

Before proceeding deeper, it's probably a good idea to enumerate the different aspects of software development that this doctrine submits opinions about:
+ Infrastructure - How a project declares what infrastructure it uses, and how that infrastructure is launched and managed, how networks connect them, etc.
+ Folder Structure - How a file's position in project folder hierarchy encodes its meaning. 
+ Environments - What environments exist, standard names (`dev`, `test`, `stage`, `prod`), and standard practices as code updates flow across them.
+ CI/CD Flow - The formalized process by which code artifacts make it from development to production and the gates they must pass.
+ Development Flow - Repeatable processes for agents to use when developing new code, complete with documentation updates and testing.
+ Architecture - Suggested architecture patterns (today, only hexagonal) with rules and organization.

The result is complex, even after I have simplified it down as much as I can.

### Infrastructure

The absolute best place to start is by reading the [infrastructure overview](../doctrine/infrastructure/infrastructure.md). This file weaves together many of the key load-bearing words of the doctrine. Much of what is described in this file is widely-practiced and well known, just opinionated. Two concepts, however, are inventions of this doctrine and may be surprising:
1. `docex` - This refers to the "executor branch" of the doctrine; operations so deterministic that they can be reduced to literal code. This code fills the `docex` folder and is leveraged via command-line. See the opening paragraphs of [docex.md](../doctrine/infrastructure/docex.md).
2. `infra.yml` or "CICL" - This refers the doctrine's own streamlined IaC language. This feature is explained in [cicl.md](../doctrine/infrastructure/cicl.md) and is what allows us to cleanly setup project `dev` and `prod` environments. It also enables the ambitious-but-evidently-possible feat of translating a project from on-prem (`fixed`) to cloud infrastructure (`elastic`) seamlessly.

While getting familiar with the doctrine, it's probably fine to think of `docex` as "the thing that runs all the CI/CD commands" and of `infra.yml` as "the place were we can define project infrastructure shape".

Speaking of shape, the general shape of doctrine-deployed projects can be read about [here](../doctrine/infrastructure/shape.md#general). This terse description helps lend some substance to the otherwise more theoretical writings in the infrastructure overview.

The numerous other infrastructure topics branch off in `infrastructure/*` files. [cicd.md](../doctrine/infrastructure/cicd.md) tracks through the CICD process, [telemetry.md](../doctrine/infrastructure/telemetry.md) describes the telemetry system, etc.

### Architecture

Simply reading [hex_overview.md](../doctrine/hexagonal_architecture/hex_overview.md) provides a the specifics of how the doctrine interprets hexagonal architecture (which is to say, as canonically as possible). Readers familiar with hex should not find anything surprising.

### Development Practices

Here I guide the reader's attention specifically to two files.

The first is [inception.md](../doctrine/practices/inception.md), which describes the inception process of a new project. This is a very tangible document which lists the *exact steps* that an agent will take with the human operator to kick off a new project.

The second is [modifications.md](../doctrine/practices/modifications.md). It's very short, but represents perhaps the most important loop documented in the doctrine. The *modification* is the fundamental unit of formal change. Change can introduce drift; drift begets divergence. This cycle is designed to prevent drift.

