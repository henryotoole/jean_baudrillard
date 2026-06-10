"""``docex bootstrap`` — idempotent setup for elastic projects.

Per :doc:`elastic_bootstrap.md` (doctrine/infrastructure/specifics),
bootstrap is the one-shot setup that makes an elastic-foundation project
usable. It covers:

1. **State backend** — the S3 bucket and DynamoDB lock table OpenTofu
   needs to manage any project resource. Created directly via boto3
   because tofu itself can't run without them.
2. **Project-tier infrastructure** — the VPC, Route53 hosted zone, ACM
   certificate, public/private subnets, and ECR repositories shared by
   every elastic environment. Created via ``tofu apply`` against
   ``infra/output/project/production/main.tf`` (emitted by ``docex
   compile``; per mod 035, project-tier output is split by side).

The project-tier apply is split into two phases because ACM DNS
validation requires the project's Route53 zone to be reachable via the
public DNS chain — which it only is once the operator NS-delegates from
the parent registrar (or parent hosted zone). Bootstrap therefore:

- **Phase 1** (zone not yet in state): targeted apply of just
  ``aws_route53_zone.project``. Prints the zone's NS records and exits,
  asking the operator to delegate and re-run.
- **Phase 2** (zone in state): full apply of the project-tier HCL,
  which will succeed iff the delegation is in place — cert validation
  blocks otherwise, giving a clear failure surface.

Both phases are idempotent. Fixed-foundation projects short-circuit at
the top with a no-op.
"""

from __future__ import annotations

from pathlib import Path

from docex import ELASTIC_REGION
from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.errors import BootstrapFailed
from docex.naming import apply_policy, dns_label
from docex.opentofu.subprocess_runner import (
    tofu_apply,
    tofu_init,
    tofu_output,
    tofu_state_list,
)


_ZONE_RESOURCE_ADDR = "aws_route53_zone.project"


def run_bootstrap(ctx: ProjectContext, aws: AWSClient) -> int:
    """Create or reconcile the project's state backend and project-tier infra.

    Returns process exit code (0 on success).
    """
    if ctx.infra is not None and ctx.infra.foundation == "fixed":
        print("docex bootstrap is a no-op for fixed-foundation projects.")
        return 0

    project = ctx.project.name
    # Route the raw underscore-joined names through the matching naming
    # policies. `s3` hyphenates and lowercases (S3 buckets reject
    # underscores); `ddb` preserves underscores (DynamoDB accepts both
    # and the doctrine prefers the project-name form).
    policies = ctx.transfer_tables.naming_policies
    bucket = apply_policy(f"{project}_tofu_state", policies.get("s3"))
    table = apply_policy(f"{project}_tofu_locks", policies.get("ddb"))

    try:
        # ----- Step 1: state backend (boto3) ----------------------------
        if not aws.s3_bucket_exists(bucket):
            aws.s3_create_bucket(bucket, region=ELASTIC_REGION)
            print(f"bootstrap: created S3 bucket {bucket}")
        else:
            print(f"bootstrap: S3 bucket {bucket} already exists")

        # Reconcile bucket-level settings every run. Each is idempotent
        # at the AWS API level — putting the same config twice is a no-op.
        aws.s3_enable_versioning(bucket)
        aws.s3_enable_encryption(bucket)
        aws.s3_block_public_access(bucket)

        if not aws.ddb_table_exists(table):
            aws.ddb_create_locking_table(table)
            print(f"bootstrap: created DynamoDB table {table}")
        else:
            print(f"bootstrap: DynamoDB table {table} already exists")

        # ----- Step 2: project-tier tofu apply --------------------------
        rc = _apply_project_tier(ctx)
        if rc != 0:
            return rc
    except Exception as exc:
        # Surface a clean DocexError so the dispatcher renders nicely.
        raise BootstrapFailed(
            f"bootstrap failed against project {project!r} in region "
            f"{ELASTIC_REGION!r}: {exc}"
        ) from exc

    return 0


def _apply_project_tier(ctx: ProjectContext) -> int:
    """Run the two-phase project-tier tofu apply.

    Returns 0 on success of whichever phase we ran. Phase 1 returns 0
    after printing NS records; it's still success in the bootstrap
    sense — the operator just has work to do before re-running.
    """
    project = ctx.project.name
    # Mod 035: project-tier output is split by side; the elastic HCL
    # lives under the production/ side.
    project_dir = ctx.project_root / "infra" / "output" / "project" / "production"
    main_tf = project_dir / "main.tf"

    if not main_tf.is_file():
        raise BootstrapFailed(
            f"{main_tf} is missing — run `docex compile` before "
            "`docex bootstrap` so the project-tier HCL exists."
        )

    rc = tofu_init(project_dir, backend=True)
    if rc != 0:
        raise BootstrapFailed(
            f"`tofu init` in {project_dir} exited {rc}; "
            "the state backend exists but tofu could not initialize against it."
        )

    state = tofu_state_list(project_dir)
    zone_applied = _ZONE_RESOURCE_ADDR in state

    if not zone_applied:
        # ----- Phase 1: zone only -----
        print("bootstrap: phase 1 — applying Route53 hosted zone only.")
        rc = tofu_apply(
            project_dir,
            targets=[_ZONE_RESOURCE_ADDR],
            auto_approve=True,
        )
        if rc != 0:
            raise BootstrapFailed(
                f"`tofu apply -target={_ZONE_RESOURCE_ADDR}` exited {rc}."
            )
        _print_delegation_instructions(project_dir, project, ctx.infra.apex_domain)
        return 0

    # ----- Phase 2: full apply -----
    print("bootstrap: phase 2 — applying full project-tier HCL.")
    rc = tofu_apply(project_dir, auto_approve=True)
    if rc != 0:
        # The most likely cause is the ACM cert validation hanging on a
        # missing NS delegation. Give the operator a concrete next step.
        print(
            "\n"
            "bootstrap: phase 2 `tofu apply` failed.\n"
            "  Most common cause: the parent zone has not been NS-delegated "
            "to the project zone yet. ACM cert validation blocks until the "
            "delegation propagates.\n"
            "  Re-run `docex bootstrap` once the NS records are live."
        )
        return rc

    print(
        f"bootstrap: project {project!r} fully bootstrapped "
        f"(region={ELASTIC_REGION})."
    )
    return 0


def _print_delegation_instructions(
    project_dir: Path, project: str, apex_domain: str
) -> None:
    """Print the zone's NS records and what the operator must do next."""
    # WHY: the zone covers `<project>.<apex_domain>`, not the bare apex —
    # the apex zone lives at the parent (registrar or parent Route53 zone)
    # and is what we delegate FROM. The project segment is DNS-labeled so
    # this matches the zone name the HCL actually emitted (a Route53 zone
    # rejects underscores).
    project_subdomain = f"{dns_label(project)}.{apex_domain}"
    nameservers = tofu_output(project_dir, "zone_name_servers")
    print("")
    print(f"bootstrap: Route53 hosted zone for {project_subdomain!r} created.")
    print("")
    if isinstance(nameservers, list) and nameservers:
        print("  NS records:")
        for ns in nameservers:
            print(f"    {ns}")
    else:
        print(
            "  Could not read `zone_name_servers` output from tofu. Run "
            f"`tofu -chdir={project_dir} output zone_name_servers` to see them."
        )
    print("")
    print(
        f"  Next step: delegate {project_subdomain!r} to the NS records above "
        f"by setting NS records\n"
        f"  in the parent zone ({apex_domain!r}) at your registrar or parent "
        "Route53 hosted zone.\n"
        "  After the delegation propagates, re-run `docex bootstrap` to apply "
        "the rest of\n"
        f"  the project-tier infrastructure ({project} VPC, subnets, ACM "
        "certs, ECR repositories)."
    )
    print("")
