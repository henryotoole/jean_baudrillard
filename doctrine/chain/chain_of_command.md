---
stratum: conditional
---

# Chain of Command

The chain of command is a method of structuring agent teams such that:
1. Contexts are clearly delineated by task and kept low in token count.
2. Blocking decisions are resolved by sufficiently broadly-scoped context.

Solving both of the above enables greater scope of change to a single project while minimizing needed human intervention.

## Basic Premise

The basic premise is to define a new axis for agents which is *orthogonal* to subject matter: the axis of *rank*.

Rank is fundamentally a measure of an agent's knowledge breadth vs. knowledge depth in-context. A context with narrow-but-deep focus might have loaded detailed documentation and scanned code for a single hexagonal module. A context with broad-but-shallow focus might have read high-level architecture docs for an entire project containing many hexagonal modules.

This measure of knowledge is a practical first-class consideration because it qualifies the level of decision that an agent can make on its own authority. For example, the decisions required to implement a hex-domain object are narrow in focus, requiring module documentation and deep understanding of module code. Conversely, the decision "should auth live in a database or process memory" is much more involved, requiring doctrine infrastructure skills, project infrastructure knowledge, architectural documentation, and overall project-goal understanding. The former should be made by a context with deep, local knowledge; the latter only by one with broad doctrine and project knowledge.

Ideally, all decisions would simply be made by a context with maximum depth and breadth. However, the two compete for space in the total context limit of the agent's model: `context_usage ∝ depth * breadth`. In practice we must choose; this choice lets us scope tasks by rank as a given *kind of task* requires a certain balance of depth and breadth.

SIDE NOTE: Claude's built-in `/goal` is an differing approach to solving the same problem as *chain of command*, but it is one-dimensional and too strict. Given a real blocker, `/goal` forces claude to do almost anything to circumvent it. Sometimes a problem is beyond the scope of an agent's authority, and responsibility for a solution is delegated upwards to a higher agent or ultimately the operator.

## Lexicon

Some additions to our doctrine-lexicon (useful for this document, and adaptable later to `lexicon.md`).

| Word | Synonyms | Definition |
| ---- | -------- | ---------- |
| Commanding Officer | "CO", "C.O." | The agent which spawned a sub-agent. |
| Advance |  | A planned collection of mods executed together in service of one or more goals. |

## Ranks

The basic premise of *rank* implies a direct and linear relationship between context breadth and design authority. Higher ranks have more breadth, less depth, and more authority than lower ones. This yields the following **privileges of rank**:
1. Higher ranks can issue orders to lower ones (e.g. create and drive subagents of lower rank).
2. Higher ranks have more design authority when it comes to decisions.
3. Higher ranks have less constraint in direction.
4. Higher ranks are more likely to encounter unexpected problems or circumstances.

The following table summarizes some properties of the different ranks:

| Name | Turns Expected | Bounded By | Escalates To | Purpose |
| ---- | -------------- | ---------- | ------------ | ------- |
| private | One shot. | Specific, focused instructions. | `private` | Reduce C.O. context burden. |
| corporal | A handful; predictable depending on process. | General scope of assigned process. | `corporal` | Intelligent detail work. |
| sarge | Unpredictable; scales with scope of advance. | Goals and constraints of the advance. | Operator | Orchestration. |

### Private

The `private` rank is deeply focused and deeply constrained. These subagents take explicit, highly bounded instructions and execute them. The primary purpose of a `private`-rank agent is to lower the context burden on their C.O.'s.

They are generally one-shot launches; either the `private` subagent will complete its task or encounter a truly unforeseen blocker.

**Examples**:
1. The implementation-execution step of a mod cycle.
2. Researching a topic and returning a summary.
3. Straightforwards code investigation.

NOTE: These are quite similar to the "general" subagents that claude already deploys at will to do research or kick off a specific task.

### Corporal

The `corporal` rank takes well defined processes and follows them. They have design authority within the bounds of the process they are following and goals set for them. 

Depending on the process the `corporal` is following, the "conversation" will likely be multi-turn. Turn ends are predictable by the process - for example, a `corporal` performing the doctrine mod cycle will often pause after design but before implementation to raise any out-of-scope design questions that emerged.

**Examples**:
1. Running a formal doctrine mod cycle.
2. Skill-based context-heavy processes like `project-cohere` (including bespoke project processes).

### Sergeant

The `sergeant` rank (or "sarge") orchestrates many subagents in pursuit of one or more goals (e.g. an advance). He will possess both broad scope for the project and operator-intent for the advance.

The `sergeant`'s conversation will be multi-turn and unpredictable, driven by both interaction with the operator and subagents.

**Examples**:
+ Plan and orchestration of mod cycles during an advance.

## Agent Communication

### Decision Ripple

When a ranked agent must make a decision that is outside of its authority, it escalates that decision to its C.O. by ending the current turn with a question (or list of questions if there are multiple decisions). Every rank's agent definition will include escalation guidelines. In practice, `private`-rank agents will rarely raise decisions as they tend to be one-shot. `corporal`-rank agents will, depending on process, probably do this quite frequently as they do the bulk of the real on-the-ground detail work.

Whenever a decision is raised to a C.O. at the end of a subagent's turn, the C.O. agent much choose whether he *himself* has the authority to make the decision. If not, the *C.O.* should raise the decision higher. In this way, decisions ripple all the way up to the human operator.

### Communication Mechanism

When sarge needs to contact the operator with a blocking question, he can either:
1. Use conventional techniques like ending the turn with a question or the `AskUserQuestion` tool.
2. Use the `field_radio` mcp tool.

### Formal Response

To ensure intent is clearly communicated when a subagent ends its turn, one of the following formal response enum types should be included at the start of turn-end text:

| Enum Value | Meaning |
| ---------- | ------- |
| COMPLETE | The task the subagent was assigned is now complete. |
| RAISE_DECISION | The subagent needs a decision made by a higher authority. |
| FAILED | The subagent has failed in its task. |

The response will therefore look something like:

```
Formal response: `COMPLETE`

<rest of turn-end message prose>
```

## Practical Implementation

In order to actually field a chain-of-command-style system, agents must actually be *implemented* somewhere. The best fit for this is the `claude code` harness' subagent system. Agents are defined via individual markdown files that set the system prompt, default skills, available tools, etc.

However, chain-of-command-style agents are composed along two *different* axes: subject matter and rank. A `corporal`-rank subagent that performs mod cycles will be distinct from one that performs the `project-cohere` skill. The `claude code` agent folder supports subfolders, so the pattern will be:

`.../agents/${rank}/${name}`

Furthermore, an agents rank will be included in the frontmatter of the agent file:
```md
---
rank: ${rank}
---
```

Rank general information (e.g. the contents of this file) will not be imbedded in the agent file. Like other conditional data, it will link back to the doctrine. The agent file will uniquely define:
1. The subject matter for which the agent must be knowledgeable: fundamental skills and system prompt.
2. The chain-of-command specifics needed: escalation guidelines.

Notably, the thing that distinguishes an "agent" from a "skill" is again context bounding. Both imply action / tasks, but skills can be loaded at any point in a context but an agent implies a single context bounded to the agent's task.