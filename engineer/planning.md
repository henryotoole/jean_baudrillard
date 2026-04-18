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