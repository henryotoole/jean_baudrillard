# Chain of Command

Notes on constructing a hierarchy so that truly important decisions ripple up to the operator's eyes while trivial things are handled by the chain of command.

Claude's built-in `/goal` is an attempt to achieve this, but it is one-dimensional and too strict. Given a real blocker, `/goal` forces claude to do almost anything to circumvent it. Sometimes a problem is beyond the scope of an agent's authority, and responsibility for a solution is delegated upwards to a higher agent or ultimately the operator.

Furthermore, attacking a complex goal quickly leads to large, sprawling contexts. This has several disadvantages: the perils of compaction, primacy / recency bias, cost, and speed. A tiered approach means we can avoid cluttering the higher levels with details, and lower levels can be re-spawned (e.g. cleared) relatively frequently as their scopes are far lower.

Question: I know sub-agent is accepted vernacular. Is super-agent also accepted?

## Ranks

So I want to introduce different "ranks" corresponding to the scope of operations an agent is responsible for. This will tie in directly with the mod cycle and somewhat indirectly with "recommended skills". 

Ranks (increasing order of scope)
1. Private - Implementation execution.
2. Corporal - Mod cycle design and documentation work.
3. Sergeant ("Sarge") - Oversight of successive mod cycles. 

The private / corporal divide is actually already mostly present in our practices. The mod cycle assumes a "design" agent (the corporal) performing design and documentation work. Execution of `implementation.md` is shoved off on a subagent (the private).

### Private

This is the lowest rank, the "grunt" which performs literal implementation-execution work. Generally the work for a `private` is very tightly controlled:
+ Execution permissions provided via `implementation.md`
+ Directive to "research this topic and return a summary"
+ Directive to "investigate this module and summarize how it works"

### Corporal

The corporal is the design workhorse rank. He'll be given mod instructions and then asked to perform a mod cycle to achieve that result. He will:
+ Research the core docs, codebase, and any other needed resources to come up with best possible means to achieve the mod's goals.
+ Ask the orchestrating agent (`sergeant`) for guidance if it's not sure of the right means to choose.
+ Design the mod (`overview.md`)
+ Ask the orchestrating agent (`sergeant`) to review and approve the design overview.
+ Create `implementation.md`
+ Kick off his own subagent (`private`) to carry out the execution.
+ Check over the resulting work
+ Summarize the results to orchestrating agent (`sergeant`), check if `sergeant` wants to make any further changes.
+ Update core docs

Note that the above is essentially *just the mod cycle* with different language as to *who's responsible for what*.

### Sergeant / "Sarge"

Sarge (`sergeant`) is the only really new addition. This agent is the (current) top-level orchestrator for the others. 

The idea is that, when I have a goal in mind, it often spans multiple mod cycles (a "mod run"). I just want to kick off a long-running single thread of work that will eventually reach it (unless it hits a real blocker). Sarge is my agent for this. He'll break a set of goals into mods, and then spawn a subagent (`corporal`) to implement each one. He keeps an eye on the design (by reading the `overview.md`'s produced by the process) and reading the `corporal`'s summary outputs of the mod cycle result. However, he won't load all the very deep details needed for `implementation.md`, hopefully keeping a cleaner context.

Sarge is also welcome, and even encouraged, to use his own `private`-rank agents as well for things like investigation and research. Sarge should always load the project's core planning docs, but deeper investigation into the code or research into a topic might be appropriate to do with subagent-and-summary, rather than directly.

Sarge also gets some other special abilities. For one, when sarge elevates a decision, he does so to the human operator. Furthermore, he can use the `field_radio` tooling (discussed below) to get ahold of the operator even if the operator is not physically present at the terminal session.

Sarge also wields some real authority. If a `corporal` raises a design question, sarge actually has the authority to make the choice or to elevate further. I'm thinking of the following guidelines for choosing:
1. If a design choice has ramifications outside of the scope of the "mod run"'s goals, it should probably escalate to the operator.
2. If sarge and the corporal disagree on a course of action and can't find middle ground, the decision should escalate to the operator.
3. What level of involvement the operator wishes to have.

Lastly, at the start of a session with sarge, sarge should ask some questions which set how autonomously sarge will ask:
1. Whether or not sarge can git commit and branch at will.
2. How involved the operator wants to be with decision making.
	+ Operator wants to be party to all design decisions.
	+ Operator wants sarge to limit the decisions sent to the operator, only seeing significant design decisions and real gaps.
	+ Operator only wants to weigh in when a real gap is reached.
3. Whether sarge can authorize the requisition actual-money-costing AWS infrastructure.

#### Escalation Guidelines
TODO adopt the above down into this.

The basic idea is to err on the side of caution with escalation in the beginning. Say "escalate things unless they match this specific criteria". Then, over time, I can get a feel for what is, and is not, important and try to write a whitelist that lets certain things stay in sarge's authority.

#### Context Stack

The following is my expected usual context stack composition for `sergeant`, in order from start to end:
1. Base doctrine
2. Sergeant skill
3. User choices (whether cna commit, how involved, etc)
4. Own research (core docs) and mod breakdown thoughts
5. Per-mod-cycle
	1. Design overview
	2. Conversations with `corporal`
	3. Resultant summary
	4. Investigation and thought resulting from questions
	5. Q/A with operator
6. Post-mod-run summary

#### Post-Mod-Run Operations

After a mod run, sarge will handle a few things:
1. Bookkeeping - making sure everything is committed and the working branch is clean. 
2. Summarizing - giving the operator a good overview of what's been achieved
	+ A good, but concise summary of all decisions made is probably good to include. This will also help us refine the escalation guidelines.
3. Notifying - use field radio to tell the operator that the run is complete.

He also could do more ambitious things (this is a list of ideas, not part of draft one of this concept):
1. Use a "project-cohere" subagent to cleanup the docs and check that they are still consistent with the code after the changes
2. Attempt a real release to stage / prod.

## Field Radio

Another problem I frequently encounter with longer running tasks is that I'll need to physically leave the machine I'm at. If I'm away from my terminals, a pause for a decision can halt the task until I return to a terminal perhaps hours later. A better communication system would help dramatically. Thus, the field radio (e.g. `field_radio`).

The idea is an MCP tool and server (a real backend, running on a machine HTTP accessible from different claude sessions on different machines). We extend the usual `AskUserQuestion` multiple choice dialogue to a tool call which uses this server to cause a discord bot to present the operator with the choice within a private discord server. The operator responds with a message (probably containing the exact index of the selected option e.g. `B` or `4`, whatever indexing system we choose). The field radio backend then translates that back into a response that sarge can use.

We can do a little better, as well. We can have two additional options:
1. Request More Info - asks sarge to provide a more full picture of the gap / issue / decision and more details on what each possible choice involves and what ramifications will result.
2. Choose Recommended - authorize sarge to make his own choice.

### Other Tools

In addition to the operator choice functionality, the field radio can also supply:
1. A notification method e.g. "mod 2 of 8 complete".

### Auth / Selection

Naturally, an agent session (sarge) will need two things to use internet-available MCP server's tools:
1. A domain at which it lives
2. Auth

I have **no idea** how MCP handles these things; I'm sure there's a standard way.

### Identification

The "radioman" (e.g. the discord bot) should always let me know *who's calling*. Necessary information is:
1. The project name (or, if there's not a clear project involved, the `cwd` working directory)
2. The rank (currently I expect this will always be sarge; but the future may bring more complexity).

For fun, informally we could use phrasing like "Sarge from ${project_name} squad wants to know...".

### Other Human Users

This is indeed targeted at myself. A field radio stack will be personal - it'll tie into my discord and send me messages. Others using the doctrine will need to host their own stacks and generate their own credentials.

### Open Question

1. Do we need a skill to go with the field radio? Or, can we build the necessary instructions into the tool's description? Hopefully the latter.
2. How can we handle MCP server auth and routing? I guess, installing the MCP server into my claude handles the routing...