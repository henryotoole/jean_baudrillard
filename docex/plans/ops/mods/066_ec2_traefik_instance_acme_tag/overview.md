# Mod 066 — traefik instance carries the acme `purpose` tag (AttachVolume IAM)

Part of the [ec2_traefik-functional advance](../_advance_ec2_traefik_functional.md).
Bug 5 — surfaced by the re-walk once mod 065 let user_data reach the EBS-attach
step (never exercised before).

## Problem

user_data attaches the ACME EBS volume at boot via `aws ec2 attach-volume`. The
traefik IAM role's grant (`project.tf.j2` IAM policy) is:

```hcl
Action   = ["ec2:AttachVolume", "ec2:DetachVolume"]
Resource = [".../volume/*", ".../instance/*"]
Condition = { StringEquals = {
    "aws:ResourceTag/purpose" = "ec2_traefik_acme"
    "aws:ResourceTag/project" = "<project>"
}}
```

`ec2:AttachVolume` authorizes against **both** the volume and the instance ARN.
The condition requires `purpose=ec2_traefik_acme` on the resource — but the
**instance carries only `descriptor=EC2`, not `purpose=ec2_traefik_acme`** (mod
060's tagging refactor put that tag only on the volume). So the instance ARN
fails the condition → `AttachVolume` is **AccessDenied** → `set -e` aborts
user_data before the volume mounts and traefik installs.

Confirmed on real AWS: after mods 063+065, the ACME volume stayed `available`
(unattached) and traefik never came up; the IAM policy + instance tags confirm
the mismatch by inspection.

This contradicts `ec2_traefik.md § TLS`, which states the instance and the
AttachVolume grant "both match on `purpose=ec2_traefik_acme` + project" — the
doctrine intended the instance to carry the tag; the refactor dropped it.

## Fix

Add `purpose = "ec2_traefik_acme"` to `aws_instance.project_traefik`'s tags,
mirroring the acme volume's tag pattern (standard projinfra block + the extra
`purpose` key). Now both resources satisfy the AttachVolume condition.

Kept the tight condition (purpose + project) rather than widening the IAM grant
— restoring the doctrine's stated design.

## No doctrine change

`ec2_traefik.md` already says the instance matches on `purpose=ec2_traefik_acme`;
this makes the emitter match the doctrine. No prose edit. (If anything, a future
doc pass could make `ec2_traefik.md § Naming and Tagging` explicit that the
instance carries the extra tag, but the § TLS text already implies it.)

## Tests

`test_mod066_traefik_instance_carries_acme_purpose_tag` (eip + pip): asserts the
`purpose` tag appears on BOTH the volume and the instance (count == 2) and
specifically within the `aws_instance` block.

## Status

Code-confirmed and unit-tested; **walk-unverified** — see the advance doc's
"introspection blocker" note. The re-walk that would confirm it (and surface any
bug 6+) is paused pending a way to introspect the instance.
