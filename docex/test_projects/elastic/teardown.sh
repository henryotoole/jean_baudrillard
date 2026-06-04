#!/usr/bin/env bash
# teardown.sh — fully retire docex_smoke_elastic from AWS.
#
# Idempotent: safe to re-run. Smoke-project teardown does in script
# what production retirement does manually:
#   - Disables RDS deletion_protection on every project DB before
#     `tofu destroy` reaches them (the transfer table sets
#     deletion_protection=true on every RDS for prod safety; smoke
#     projects always teardown so we override at retirement time).
#   - Direct-deletes every project RDS via the AWS API with
#     --skip-final-snapshot, then waits for full deletion. The
#     doctrine leaves skip_final_snapshot at the prod-safe default
#     (false), which would otherwise block tofu destroy and leave
#     the project's VPC orphaned via still-attached RDS ENIs.
#     Mod 028.
#   - Purges ECR images/repos before the project-tier `tofu destroy`
#     so it doesn't trip on RepositoryNotEmptyException.
# Then walks `tofu destroy` per env (prod → stage → project) — by
# this point the RDS instances are already gone, so the destroys
# reconcile state and clean up the VPC, ALB, ECS, etc. Finishes by
# cleaning tofu-side residue (SSM params, state backend) and
# sweeping any local docker artifacts from `dev`/`test` envs.
#
# AWS_REGION pinned to us-east-1 (doctrine).

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="docex_smoke_elastic"
AWS_REGION="us-east-1"

# Project name as it shows up in AWS resource names. The smoke project
# uses snake_case (docex_smoke_elastic), but several AWS resource types
# disallow underscores in identifiers; docex's `naming_policies` table
# (mod 005) translates per policy:
#   s3  → hyphen (no underscores in S3 bucket names)
#   ddb → underscore (DynamoDB accepts both; doctrine prefers underscore)
#   rds → hyphen (RDS identifiers disallow underscores)
# Mirror those translations here so teardown finds what bootstrap created.
PROJECT_AWS_PREFIX="${PROJECT_NAME//_/-}"
STATE_BUCKET="${PROJECT_AWS_PREFIX}-tofu-state"
STATE_LOCK_TABLE="${PROJECT_NAME}_tofu_locks"

export AWS_REGION

echo "==> tearing down $PROJECT_NAME in AWS region $AWS_REGION"

# -- 1. Disable RDS deletion_protection ---------------------------------
# WHY: the relational_db/postgres transfer-table entry sets
# deletion_protection=true so production RDS instances can't be deleted
# accidentally. Smoke projects always teardown — override at retirement
# time so the subsequent tofu destroy can proceed.
#
# `modify-db-instance --apply-immediately` is async — the API call
# returns immediately but the flag flip can take 5-30s to land. If
# tofu destroy runs before the flag is actually false in AWS, the
# RDS deletion call is rejected and tofu skips that resource (the
# subsequent project-tier destroy then trips on the still-attached
# RDS ENIs). Poll until every project RDS reports DeletionProtection=false
# before proceeding.
echo "-- disabling RDS deletion_protection (smoke project)"
project_dbs=()
for db in $(aws rds describe-db-instances \
              --query "DBInstances[?starts_with(DBInstanceIdentifier, \`${PROJECT_AWS_PREFIX}-\`)].DBInstanceIdentifier" \
              --output text 2>/dev/null || true); do
  echo "   RDS: $db"
  project_dbs+=("$db")
  aws rds modify-db-instance \
    --db-instance-identifier "$db" \
    --no-deletion-protection \
    --apply-immediately >/dev/null 2>&1 || true
done

if [[ "${#project_dbs[@]}" -gt 0 ]]; then
  echo "   waiting for DeletionProtection=false to land in AWS..."
  for db in "${project_dbs[@]}"; do
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
      protected=$(aws rds describe-db-instances \
                    --db-instance-identifier "$db" \
                    --query "DBInstances[0].DeletionProtection" \
                    --output text 2>/dev/null || echo "true")
      if [[ "$protected" == "False" || "$protected" == "false" ]]; then
        break
      fi
      sleep 5
    done
    if [[ "$protected" != "False" && "$protected" != "false" ]]; then
      echo "   (warning: $db still shows DeletionProtection=$protected after polling; tofu destroy may skip it)"
    fi
  done
fi

# -- 2. Direct-delete RDS instances ------------------------------------
# Step 1 disabled deletion_protection, but tofu destroy still asks AWS
# for a final snapshot identifier when destroying aws_db_instance.
# The doctrine's postgres engine on elastic leaves skip_final_snapshot
# at the terraform-aws-provider default (false) — correct for prod
# safety, but blocks smoke-project retirement: AWS rejects the delete,
# tofu silently continues, and the project-tier destroy later trips on
# RDS-managed ENIs that haven't released. (Mod 028.)
#
# Smoke projects always retire — bypass tofu for RDS using the AWS API
# directly with --skip-final-snapshot. Once each RDS is gone, the
# subsequent tofu destroy reconciles state (resource absent from AWS
# → removed from state) and proceeds cleanly to the project tier.
if [[ "${#project_dbs[@]}" -gt 0 ]]; then
  echo "-- direct-delete RDS instances (--skip-final-snapshot)"
  for db in "${project_dbs[@]}"; do
    echo "   RDS: $db (deleting)"
    aws rds delete-db-instance \
      --db-instance-identifier "$db" \
      --skip-final-snapshot \
      --delete-automated-backups >/dev/null 2>&1 || true
  done

  echo "   waiting for RDS instances to fully delete..."
  for db in "${project_dbs[@]}"; do
    # RDS deletion takes a few minutes (1-3 typical, up to 10 in
    # rare cases). Poll until describe-db-instances returns
    # DBInstanceNotFound. Bounded at ~10 min so a stuck delete
    # surfaces as a warning rather than hanging forever.
    for attempt in $(seq 1 60); do
      err="$(aws rds describe-db-instances \
               --db-instance-identifier "$db" 2>&1 >/dev/null || true)"
      if echo "$err" | grep -q "DBInstanceNotFound"; then
        echo "   RDS: $db gone"
        break
      fi
      sleep 10
    done
    if ! echo "$err" | grep -q "DBInstanceNotFound"; then
      echo "   (warning: $db did not fully delete within 10 min; tofu destroy will reconcile what it can)"
    fi
  done
fi

# -- 3. ECR images + repos ----------------------------------------------
# WHY: aws_ecr_repository emits without `force_delete = true`, so
# `tofu destroy` at the project tier fails with
# RepositoryNotEmptyException if any image is still in the repo. Purge
# ahead of tofu so the project-tier destroy is clean. Tofu treats
# already-deleted resources as removed-from-state on its next pass.
echo "-- ECR repositories under prefix $PROJECT_NAME/"
for repo in $(aws ecr describe-repositories \
                --query "repositories[?starts_with(repositoryName, \`${PROJECT_NAME}/\`)].repositoryName" \
                --output text 2>/dev/null || true); do
  echo "   ECR repo: $repo"
  image_ids="$(aws ecr list-images --repository-name "$repo" \
               --query 'imageIds[*]' --output json 2>/dev/null || echo '[]')"
  if [[ "$image_ids" != "[]" ]]; then
    aws ecr batch-delete-image --repository-name "$repo" --image-ids "$image_ids" >/dev/null \
      || echo "   (warning: batch-delete-image failed for $repo)"
  fi
  aws ecr delete-repository --repository-name "$repo" --force >/dev/null 2>&1 || true
done

# -- 4. tofu destroy each env, then project tier ------------------------
for layer in prod stage project; do
  dir="$PROJECT_ROOT/infra/output/$layer"
  if [[ -f "$dir/main.tf" ]]; then
    echo "-- tofu destroy: $layer"
    (cd "$dir" && tofu init -input=false -upgrade >/dev/null 2>&1 || true)
    (cd "$dir" && tofu destroy -auto-approve -input=false) \
      || echo "   (warning: tofu destroy on $layer had non-zero exit; continuing)"
  fi
done

# -- 5. SSM parameters under the project prefix -------------------------
echo "-- SSM parameters under /${PROJECT_NAME}/"
mapfile -t params < <(aws ssm describe-parameters \
  --parameter-filters "Key=Name,Option=BeginsWith,Values=/${PROJECT_NAME}/" \
  --query 'Parameters[*].Name' --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)
if [[ "${#params[@]}" -gt 0 ]]; then
  # AWS API caps delete-parameters at 10 names per call.
  for ((i=0; i<${#params[@]}; i+=10)); do
    aws ssm delete-parameters --names "${params[@]:i:10}" >/dev/null 2>&1 || true
  done
fi

# -- 6. tofu state backend (full retirement) ----------------------------
echo "-- tofu state bucket + lock table"
# Empty the bucket first (versions + delete markers); then delete it.
aws s3api list-object-versions --bucket "$STATE_BUCKET" \
  --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
  --output json 2>/dev/null > /tmp/${PROJECT_NAME}-versions.json || true
if [[ -s /tmp/${PROJECT_NAME}-versions.json ]] && \
   ! grep -q '"Objects": null' /tmp/${PROJECT_NAME}-versions.json; then
  aws s3api delete-objects --bucket "$STATE_BUCKET" \
    --delete file:///tmp/${PROJECT_NAME}-versions.json >/dev/null 2>&1 || true
fi
aws s3api list-object-versions --bucket "$STATE_BUCKET" \
  --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
  --output json 2>/dev/null > /tmp/${PROJECT_NAME}-markers.json || true
if [[ -s /tmp/${PROJECT_NAME}-markers.json ]] && \
   ! grep -q '"Objects": null' /tmp/${PROJECT_NAME}-markers.json; then
  aws s3api delete-objects --bucket "$STATE_BUCKET" \
    --delete file:///tmp/${PROJECT_NAME}-markers.json >/dev/null 2>&1 || true
fi
aws s3api delete-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1 || true
aws dynamodb delete-table --table-name "$STATE_LOCK_TABLE" >/dev/null 2>&1 || true

# -- 7. Compiled output -------------------------------------------------
echo "-- compiled infra/output"
rm -rf "$PROJECT_ROOT/infra/output/dev" \
       "$PROJECT_ROOT/infra/output/test" \
       "$PROJECT_ROOT/infra/output/stage" \
       "$PROJECT_ROOT/infra/output/prod" \
       "$PROJECT_ROOT/infra/output/project"

# -- 8. Local docker artifacts for dev/test envs ------------------------
# `dev`/`test` envs compile to fixed compose stacks even on elastic
# projects; sweep up any local containers/networks/volumes too.
for container in $(docker ps -aq --filter "name=${PROJECT_NAME}" 2>/dev/null || true); do
  docker rm -f "$container" >/dev/null || true
done
for network in $(docker network ls -q --filter "name=${PROJECT_NAME}" 2>/dev/null || true); do
  docker network rm "$network" >/dev/null 2>&1 || true
done
for volume in $(docker volume ls -q --filter "name=${PROJECT_NAME}" 2>/dev/null || true); do
  docker volume rm "$volume" >/dev/null 2>&1 || true
done

echo "==> teardown complete. run verify_clean.sh to confirm."
