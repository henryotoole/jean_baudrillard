# Mod 065 — ec2_traefik user_data: use IMDSv2 tokens for metadata

Part of the [ec2_traefik-functional campaign](../_campaign_ec2_traefik_functional.md).
Bug 4 — surfaced by the campaign re-walk once mod 063 let user_data get past the
package install.

## Problem

The user_data fetches EC2 instance metadata with raw curls:

```sh
INSTANCE_ID=$(curl -sf http://169.254.169.254/latest/meta-data/instance-id)
REGION=$(curl -sf http://169.254.169.254/latest/meta-data/placement/region)
# … and (pip variant) the boot DNS-update:
IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4)
```

The pinned Ubuntu 24.04 AMI enforces **IMDSv2** (`HttpTokens=required` — verified
on the running instance). A metadata request without a session token gets **HTTP
401**, so `curl -f` exits non-zero and — under `set -euo pipefail` — user_data
aborts. It aborts right after the (now-working, post-mod-063) package installs,
before the EBS attach and traefik install, so traefik never starts.

Confirmed on real AWS via `aws ec2 get-console-output`: `cc_scripts_user …
failed` immediately after `Setting up amazon-cloudwatch-agent`, i.e. at the first
raw IMDS curl. `:80`/`:443` on the instance stayed closed.

(AWS CLI v2 calls elsewhere in the script are unaffected — the SDK performs the
IMDSv2 token handshake internally. Only the hand-rolled curls needed fixing.)

## Fix

Fetch an IMDSv2 token once and pass it on every metadata request:

```sh
IMDS_TOKEN=$(curl -sf -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
INSTANCE_ID=$(curl -sf -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" \
    http://169.254.169.254/latest/meta-data/instance-id)
REGION=$(curl -sf -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" \
    http://169.254.169.254/latest/meta-data/placement/region)
```

Same treatment in the pip-variant `docex-traefik-dns-update` script (with the
heredoc `\$` escaping, since it's written to a file that runs per-boot and needs
its own fresh token).

We keep IMDSv2 **required** (the secure default) and make the script speak it,
rather than relaxing the instance to IMDSv1 via `metadata_options`.

## No doctrine change

Implementation detail of the doctrine-managed user_data. No prose edit.

## Tests

Extend the user_data assertions in `tests/integration/test_compile.py`: assert
the rendered script issues a `PUT .../latest/api/token` and passes
`X-aws-ec2-metadata-token:` on the instance-id/region fetches (i.e. no
token-less raw metadata curl remains). Both variants.

Real-AWS confirmation: the campaign re-walk — traefik must come up and serve
`/health` through the instance.
