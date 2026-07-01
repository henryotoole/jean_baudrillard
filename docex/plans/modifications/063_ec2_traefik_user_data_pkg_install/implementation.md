# Mod 063 — Implementation (done inline)

Small, self-contained template fix; implemented directly rather than via a
sub-agent. See [`overview.md`](./overview.md) for the design.

## Changes

**`src/docex/emit/templates/ec2_traefik_user_data.sh.j2`** — replaced the single
apt line that installed `curl ca-certificates unzip jq awscli
amazon-cloudwatch-agent` with:
1. `apt-get install -y --no-install-recommends curl ca-certificates unzip jq`
   (only packages that exist on Ubuntu 24.04).
2. AWS CLI v2 via the official bundle (`awscli-exe-linux-${ARCH}.zip` →
   `/tmp/aws/install`), arch-aware. Load-bearing → runs under `set -e`.
3. CloudWatch agent via the AWS-hosted `.deb`, best-effort
   (`dpkg -i … || apt-get install -f -y || true`, inside an `if curl …` guard)
   so it can never abort user_data.

The `${ARCH}` / `${CW_ARCH}` bash expansions are escaped to `$${…}` for the HCL
heredoc automatically by the mod-062 escaping in `emit/hcl.py` (verified in the
rendered output).

**`tests/integration/test_compile.py`** — added
`test_mod063_user_data_installs_awscli_v2_not_apt` (parametrized eip/pip):
asserts no apt `awscli`/`cloudwatch-agent`, AWS CLI v2 bundle present, CW agent
best-effort.

## Verification

- Rendered from source + `tofu validate` on `project/production` → valid.
- Full fast suite: 629 passed (627 + 2 new).
- Real-AWS confirmation deferred to the campaign re-walk (task #9): the instance
  must actually finish user_data and serve traefik.
