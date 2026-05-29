# docex_smoke_elastic

A minimal `elastic`-foundation smoke-test project. Run before cutting a `docex` minor or major version to surface AWS release-path bugs that unit tests structurally can't reach.

This project is **not** a real product. See [`plans/core/masterplan.md`](./plans/core/masterplan.md) for design intent and [`../PRE_CUT_CHECKLIST.md`](../PRE_CUT_CHECKLIST.md) for the operator-driven walk through `bootstrap → compile → containerize → release stage → stagetest → release prod → teardown`.
