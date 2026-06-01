# Doctrine Smoke-Test Projects

This folder holds the two doctrine-faithful smoke-test projects (`fixed/` and `elastic/`) that `docex` walks before cutting a minor or major version.

The canonical architecture/design doc for these projects lives in the core planning tree at [`../plans/core/test_projects.md`](../plans/core/test_projects.md) — it covers why two foundations, the shared code identity, the nested-git-repo structure, the commit cadence between inner and outer repos, and the cut lifecycle.

The operator's pre-cut walk procedure (the actual step-by-step against real infrastructure) lives next to this stub at [`PRE_CUT_CHECKLIST.md`](./PRE_CUT_CHECKLIST.md).
