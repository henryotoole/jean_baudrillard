"""The durable-job substrate (Mod 148).

A long docex command can launch its work in a **vessel** — a detached,
deterministically-named process that outlives the foreground invocation —
leaving behind an on-disk **run record** under ``.docex/runs/<id>/``. One
uniform set of verbs (``job ls|status|wait|logs|result``) then operates on
that record, so a killed foreground monitor never loses the run.

This mod ships one vessel kind (the sibling container, used by ``docex
test``) and one self-heal reaper. The abstraction is written
vessel-polymorphic so later mods can add a host-process vessel and further
callers without reshaping it.

Modules:

- ``record``  — run-id minting, the ``.docex/runs/<id>/`` layout, atomic
  ``exit`` write, ``meta``/``status`` read+write, and ``classify()``.
- ``vessel``  — the ``ContainerVessel`` (self-inspect clone launch,
  liveness, rm).
- ``reaper``  — the single-run preflight reap for a scope.
- ``commands``— the ``job`` verbs, the ``docex test`` durable wrapper, and
  the hidden ``__run-job`` in-vessel entrypoint.
"""
