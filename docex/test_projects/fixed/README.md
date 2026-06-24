# docex_smoke_fixed

A minimal `fixed`-foundation smoke-test project. Run before cutting a doctrine minor or major version to surface release-path bugs that unit tests structurally can't reach.

This project is **not** a real product. See [`plans/core/masterplan.md`](./plans/core/masterplan.md) for design intent and [`../PRE_CUT_CHECKLIST.md`](../PRE_CUT_CHECKLIST.md) for the operator-driven walk through `projinfra → envinfra → check → merge → containerize → release stage → stagetest → release prod → teardown`.
