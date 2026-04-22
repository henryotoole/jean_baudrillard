# Planning

This document contains my ideas for 'planning guidelines' that are given to the machine during the planning stage.

## Hexagonal Module Plan and Doc

| Section | What to include |
| ------- | --------------- |
| Purpose | Why this module exists and what it does. |
| Driving Ports | Inbound ports (use cases) with brief descriptions. |
| Reacting Ports | Outbound ports (dependencies) the module requires. |
| Adapters Included | Which adapters ship with this module. |
| Hard Boundaries | Explicit notes on what the module should **not** do. This prevents scope creep. |

The above is currently in hex_overview.md. However, this should probably be mirrored in the docs that describe the planning stages, which don't yet exist themselves.

## Planning Stages

There's a flow to creating code:
1. Start with an idea of some sort (strategic goals)
2. Translate that into a `masterplan.md`
3. Break that masterplan down into specific tactical choices (e.g. hex modules, frontend layout and scope, etc.)
4. Execute on those tactical choices to write code.
5. Iterate on the working product, making changes to code and planning documents when applicable.

This is my flow now. But could it be better with AI? What does the planning-update loop look like? How can I make sure that changes to code ripple up the stack to the planning docs without changing fundamental precepts of what the thing does?

The division must be strategy v tactics. The machine can make tactical changes but never alter strategy.