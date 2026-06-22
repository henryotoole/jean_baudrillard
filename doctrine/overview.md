---
stratum: resident
---

# Doctrine

In every engineering project, choices must be made. Some choices are *not deterministic* - they are conditional on project specifics and require a judgement call. We might loosely call the sum of these choices "design". Other choices are truly agnostic to, or directly dependent on, project specifics. Those choices are *deterministic*. 

The purpose of doctrine is to provide one canonical way to perform all *deterministic* tasks. Having and adhering to doctrine ensures:
1. Code remains concise - less documentation, less decision making, less sprawling infrastructure.
2. Code is consistent cross-project - it is easy to move from one project to another because infrastructure, architecture, and conventions will be very similar.
3. Reduced drift - we don't invent two different ways to do the same thing.

Some examples:

**Design**
1. Whether or not a storage backing service is needed.
2. Hexagonal module domains and boundaries.

**Doctrine**
1. The choice of storage backing service is deterministic - if infra is self-hosted it's `minio`; if cloud-provided it's `S3`.
2. The use of hexagonal architecture.

## Structure

The doctrine's files are structured by file-structure hierarchy along topic lines - the "infrastructure" folder contains files relating to infrastructure; each file is named after the infrastructure topic it covers. Just as critical are the links which connect file and file-sections together. These links form a graph that is just as load-bearing to the conceptual integrity of the doctrine as the file-structure.

Doctrine files also carry a small amount of YAML frontmatter. Today it is a single field, `stratum`, classifying the file as one of `resident`, `conditional`, or `executor`:

```yml
---
stratum: resident
---
```

## Strata

Doctrine content falls into three **strata**, distinguished by *when* the information is needed.

1. **Resident Stratum** - Information fundamental to writing code and necessary to provide skill-triggering vocabulary. This stratum is *always resident in context* and is always loaded first to take advantage of context **primacy bias**. Includes the doctrine overview, lexicon, practices, architecture, and a handful of other things. 

2. **Conditional Stratum** - Information needed only when performing a specific *activity*: cutting a release, debugging preinfra, designing telemetry, authoring a transfer table. This stratum is loaded into context with **skills**. Each skill is scoped to an activity and loaded when the agent undertakes it. Skills avoid replicating doctrine knowledge; rather they hold a set of links to relevant doctrine files. Conditional stratum info ranges from *general* (shorter, orienting, "what") to *specific* (longer, detailed, "how").

3. **Executor Stratum** - Action encoded as code. `docex` and its shim are in the Executor stratum. The executor takes the literal actions the other strata describe; it is consumed *by* skills to do work and is never itself wrapped in a skill.

## Skills

Skills are the loading mechanism for the conditional stratum. Skills which link into the corpus of the doctrine are referred to as *thread skills* and they follow these rules:

- **Split by activity, not topic.** There is a thread skill for *making a release*, not one for *understanding CI/CD*. The agent reaches for a thread skill on the basis of what it is doing, so a thread skill's boundary is an action.
- **Bodies are router + thread.** A thread skill body carries minimal *duplicated* prose. It does not restate what the doctrine files say, because a restatement drifts from its source. Instead the body:
	- (a) routes the agent's attention to specific files, or specific sections within files.
	- (b) supplies the *thread* that ties concepts together: which files to read first, the order to read them in, how files interact, and the criteria for deciding among them.
- **Progressive disclosure within the body.** The general-to-specific axis is expressed through *how the body directs attention*. On load, the body points the agent to general information to read immediately. Specific information is referenced for the agent to read only if it finds it needs it.
- **Metadata follows best practice.** A skill's name and description are the entire trigger interface and are always in context; they are written as crisp activity triggers so the agent loads the right skill at the right time. This applies to all skills, not just thread skills.

Because thread skill bodies route into the doctrine rather than copy it, the doctrine files remain the single source of truth. A doctrine edit does not require rewriting a thread skill — it only requires that the thread skill's pointers still resolve. Keeping those pointers valid (no dangling links, no references to moved sections) is the one ongoing cost of this structure, and it should be checked mechanically. Thread skills are discovered through their always-in-context metadata (each skill's name and description); authored as activity triggers, those descriptions are the discovery map, so no separate catalog is maintained.