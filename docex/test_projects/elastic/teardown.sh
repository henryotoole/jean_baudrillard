#!/usr/bin/env bash
# teardown.sh — fully retire docex_smoke_elastic from AWS.
#
# Idempotent: safe to re-run. Smoke-project teardown does in script
# what production retirement does manually:
#   - Disables RDS deletion_protection on every project DB before
#     `tofu destroy` reaches them (the transfer table sets
#     deletion_protection=true on every RDS for prod safety; smoke
#     projects always teardown so we override at retirement time).
#   - Purges ECR images/repos before the project-tier `tofu destroy`
#     so it doesn't trip on RepositoryNotEmptyException.
# Then walks `tofu destroy` per env (stage → prod → project), cleans
# up tofu-side residue (SSM params, state backend), and sweeps any
# local docker artifacts from `dev`/`test` envs.
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
echo "-- disabling RDS deletion_protection (smoke project)"
for db in $(aws rds describe-db-instances \
              --query "DBInstances[?starts_with(DBInstanceIdentifier, \`${PROJECT_AWS_PREFIX}-\`)].DBInstanceIdentifier" \
              --output text 2>/dev/null || true); do
  echo "   RDS: $db"
  aws rds modify-db-instance \
    --db-instance-identifier "$db" \
    --no-deletion-protection \
    --apply-immediately >/dev/null 2>&1 || true
done

# -- 2. ECR images + repos ----------------------------------------------
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

# -- 3. tofu destroy each env, then project tier ------------------------
for layer in prod stage project; do
  dir="$PROJECT_ROOT/infra/output/$layer"
  if [[ -f "$dir/main.tf" ]]; then
    echo "-- tofu destroy: $layer"
    (cd "$dir" && tofu init -input=false -upgrade >/dev/null 2>&1 || true)
    (cd "$dir" && tofu destroy -auto-approve -input=false) \
      || echo "   (warning: tofu destroy on $layer had non-zero exit; continuing)"
  fi
done

# -- 4. SSM parameters under the project prefix -------------------------
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

# -- 5. tofu state backend (full retirement) ----------------------------
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

# -- 6. Compiled output -------------------------------------------------
echo "-- compiled infra/output"
rm -rf "$PROJECT_ROOT/infra/output/dev" \
       "$PROJECT_ROOT/infra/output/test" \
       "$PROJECT_ROOT/infra/output/stage" \
       "$PROJECT_ROOT/infra/output/prod" \
       "$PROJECT_ROOT/infra/output/project"

# -- 7. Local docker artifacts for dev/test envs ------------------------
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
