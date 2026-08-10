# Test-fixture Dockerfiles float their base tag, and one rotted silently

**Found:** advance 006, mod 126.

## What happened

`tests/integration/test_check_real.py::test_check_real_happy_path` was **already
red** when advance 006 began — before this advance changed a line. The cause was
`_gate_healthcheck_tooling`, which built the fixture image and probed it for
`curl`: `docker run --rm python:3.12-slim sh -c 'command -v curl'` prints
nothing, and the fixture's `prod` stage adds only `psycopg2-binary` while
`api.web` declares `health_check_path`.

Advance 005's report records **"integration 20/0"** at handoff. Deleting the gate
in mod 126 brought the suite to **18 passed, green** — verified, not inferred. So
either that number was wrong when written, or, far more likely, it decayed
afterwards and nothing observed the decay, because nothing re-ran the integration
suite between the 1.7.0 smoke walk and advance 006.

## The mechanism

`tests/fixtures/sample_project/core/api/Dockerfile` opens `FROM python:3.12-slim`
— a **floating tag**. Debian's slim images have dropped `curl` from the base
layer; a tag that resolved to an image carrying it once resolves to one that does
not now. Nothing in the repo pinned it.

This is the doctrine's own **base layer rot** risk
([`masterplan.md § Upstream tool drift`](../../core/masterplan.md#upstream-tool-drift))
landing somewhere the doctrine did not think to look. `docex`'s *shipped* image
pins its base by digest precisely against this. Test fixtures were left floating
because they are not the shipped artifact — but a fixture is the input to a gate
whose verdict we then believe.

## Why it is worth a brief rather than a shrug

The symptom is gone: the gate that failed no longer exists, and no remaining gate
builds a fixture image and inspects its contents. So there is nothing to fix
today. What survives is the shape, and it is advance 005's recurring defect in a
new costume — **a number that was inherited rather than re-derived**. "Integration
20/0" was true when measured and was carried forward as a fact about the present.

Two directions if this is taken up:

1. **Pin fixture base images by digest**, as the shipped `Dockerfile` does. Cheap,
   and it converts silent rot into a loud pull failure.
2. **Re-derive the suite counts at the start of an advance rather than reading them
   out of the previous advance's report.** Advance 006 did this by accident — the
   unit baseline was re-run at plan time — and it is the only reason the red test
   was noticed at all.

The second is the more valuable of the two, and it is not a code change.
