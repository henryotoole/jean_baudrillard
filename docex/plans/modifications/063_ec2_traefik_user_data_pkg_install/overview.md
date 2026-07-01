# Mod 063 — Fix ec2_traefik user_data package install on Ubuntu 24.04

Part of the [ec2_traefik-functional campaign](../_campaign_ec2_traefik_functional.md).
Bug 2 of 3.

## Problem

The EC2-traefik instance's user_data installs its dependencies with:

```sh
apt-get install -y --no-install-recommends \
    curl ca-certificates unzip jq awscli amazon-cloudwatch-agent
```

On the pinned AMI (latest Ubuntu 24.04 LTS / noble), **`awscli` and
`amazon-cloudwatch-agent` are not installable from apt**:
- `awscli` was dropped from the Ubuntu archive (upstream directs users to the
  AWS CLI v2 bundle or snap).
- `amazon-cloudwatch-agent` was never in the Ubuntu archive; it's an AWS-hosted
  `.deb`.

`apt-get install` fails on those two packages, and because the script runs under
`set -euo pipefail` (line 9), **user_data aborts immediately** — before
installing traefik, attaching the ACME EBS volume, or writing any systemd units.
Net effect: nothing listens on :80/:443; the reverse proxy is dead on arrival.

Confirmed on real AWS via `aws ec2 get-console-output`:
```
E: Package 'awscli' has no installation candidate
E: Unable to locate package amazon-cloudwatch-agent
cloud-init: Failed to run module scripts_user ... failed
```

## What AWS CLI is used for (why it's load-bearing)

The user_data calls `aws` for: `ec2 describe-volumes` / `attach-volume` (ACME
volume), `ssm get-parameter` (config sync timer), and — pip variant —
`route53 change-resource-record-sets` (boot DNS update). AWS CLI **must** be
present and working. The CloudWatch agent, by contrast, only ships traefik logs
— useful but not required for the proxy to function; its install should be
best-effort.

## Fix

In `emit/templates/ec2_traefik_user_data.sh.j2`:

1. Keep the apt install for packages that DO exist on noble:
   `curl ca-certificates unzip jq` (drop `awscli` and
   `amazon-cloudwatch-agent`).
2. Install **AWS CLI v2** from the official bundle (arch-aware), which is the
   supported no-apt path:
   ```sh
   ARCH=$(uname -m)   # x86_64 | aarch64 — both are valid AWS CLI bundle arches
   curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" -o /tmp/awscliv2.zip
   unzip -q /tmp/awscliv2.zip -d /tmp
   /tmp/aws/install
   rm -rf /tmp/awscliv2.zip /tmp/aws
   ```
3. Install the **CloudWatch agent** from its AWS-hosted `.deb`, **best-effort**
   (must not abort user_data if it fails):
   ```sh
   CW_ARCH=$( [ "$ARCH" = "aarch64" ] && echo arm64 || echo amd64 )
   if curl -sSL "https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/${CW_ARCH}/latest/amazon-cloudwatch-agent.deb" -o /tmp/cwagent.deb; then
       dpkg -i /tmp/cwagent.deb || apt-get install -f -y || true
   fi
   rm -f /tmp/cwagent.deb || true
   ```
   The later `amazon-cloudwatch-agent-ctl … || true` call already tolerates the
   agent being absent, so log shipping simply won't happen if the download
   fails — traefik still serves.

## Robustness principle

An **optional** tool (CloudWatch agent) must never abort the script. AWS CLI is
required and may fail hard (that's correct — the instance is useless without it).
Keep `set -euo pipefail`; wrap only the best-effort steps in `|| true`.

## No doctrine change

`ec2_traefik.md` describes behavior (traefik + LE + SSM config sync + CW logs),
not the apt mechanics. The intended behavior is unchanged; this fixes the
install so that behavior can actually happen. No doctrine prose edit.

## Tests

Unit test over the rendered user_data (mirror the existing `test_mod044_*` and
`test_mod062_*` user_data assertions in `tests/integration/test_compile.py`):
- Asserts the rendered script does NOT `apt-get install` `awscli` or
  `amazon-cloudwatch-agent`.
- Asserts it installs AWS CLI v2 via the `awscli-exe-linux-` bundle URL and runs
  `aws/install`.
- Asserts the CloudWatch agent step is best-effort (`|| true` present on its
  path) so it can't abort user_data.
- Both variants (`eip`, `pip`).

Real-AWS confirmation happens in the campaign re-walk (task #9), not in unit
tests.
