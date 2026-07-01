# Mod 067 — ship ec2_traefik user_data bring-up log to CloudWatch

Part of the [ec2_traefik-functional campaign](../_campaign_ec2_traefik_functional.md).
An observability improvement that made the rest of the campaign debuggable.

## Problem

When the traefik instance's user_data failed, it was a black box:
- The serial console (`aws ec2 get-console-output`) did not reliably populate on
  Nitro — it returned empty repeatedly during the walk.
- SSM Session Manager was denied by an org SCP, and the traefik role lacks
  `AmazonSSMManagedInstanceCore`.
- Only 80/443 are open (no SSH).

So each boot failure could only be guessed at, forcing blind fix→re-provision
cycles (bugs 4, 5 were found this way, expensively).

## Fix

Add an EXIT trap to user_data that ships `/var/log/docex-user-data.log` to the
project's existing `/<project>/ec2_traefik` CloudWatch log group (stream
`bringup-<instance_id>`). The traefik IAM role already grants
`logs:CreateLogStream` + `logs:PutLogEvents` there, so no new permissions. It is:

- **Best-effort** — every AWS call is `|| true`; the trap preserves and returns
  the real exit code, so a shipping failure never masks the boot result.
- **Fires on success and failure** (`set -e` triggers EXIT) — the log always
  shows how far boot got and why it stopped.
- **Placed right after IMDS** (so `PROJECT`/`REGION`/`INSTANCE_ID` and AWS CLI
  are available). Failures before that point are rare now (bugs 2/4 fixed) and
  are the package-install steps, which log to the console fine.

This is a **permanent** improvement, not a debug throwaway: reverse-proxy
bring-up should be observable in the same CloudWatch group everything else uses,
especially given the serial console's unreliability.

## Payoff (this campaign)

The breadcrumb immediately revealed that (post mods 063/065/066) user_data now
runs to completion and traefik serves — and surfaced the real remaining problem,
bug 6 (Service-Connect backend not VPC-DNS-resolvable → 502), which no amount of
guessing had pinned down. See the campaign doc's "Walk #3 results".

## No doctrine change

`ec2_traefik.md § Logging` already promises CloudWatch log shipping for the
instance; this extends it to the bring-up phase. A future doc pass could mention
the `bringup-<id>` stream explicitly, but no rule changes.

## Tests

`test_mod067_user_data_ships_bringup_log_to_cloudwatch` (eip + pip): assert the
rendered user_data installs an EXIT trap that calls `aws logs put-log-events`
against the `/<project>/ec2_traefik` group, and that it's best-effort.
