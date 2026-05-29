#!/usr/bin/env bash
# teardown.sh — fully retire docex_smoke_elastic from AWS.
#
# Idempotent: safe to re-run. Runs `tofu destroy` for each env (prod →
# stage → project tier), then boto3-driven cleanup of resources tofu
# doesn't catch (ECR image tags, SSM parameters under the project
# prefix). Finally deletes the tofu state backend bucket and lock table
# since this project is being fully retired between cuts.
#
# AWS_REGION pinned to us-east-1 (doctrine).

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="docex_smoke_elastic"
AWS_REGION="us-east-1"
STATE_BUCKET="${PROJECT_NAME}-tofu-state"
STATE_LOCK_TABLE="${PROJECT_NAME}-tofu-locks"

# Project name as it shows up in AWS resource names (hyphenated form).
# docex names resources by replacing _ with - per the `web` role's
# naming defaults; mirror that here.
PROJECT_AWS_PREFIX="${PROJECT_NAME//_/-}"

export AWS_REGION

echo "==> tearing down $PROJECT_NAME in AWS region $AWS_REGION"

# -- 1. tofu destroy each env, then project tier -------------------------
for layer in prod stage project; do
  dir="$PROJECT_ROOT/infra/output/$layer"
  if [[ -f "$dir/main.tf" ]]; then
    echo "-- tofu destroy: $layer"
    (cd "$dir" && tofu init -input=false -upgrade >/dev/null 2>&1 || true)
    (cd "$dir" && tofu destroy -auto-approve -input=false) \
      || echo "   (warning: tofu destroy on $layer had non-zero exit; continuing)"
  fi
done

# -- 2. ECR images that tofu didn't catch --------------------------------
# WHY: aws_ecr_repository with `force_delete = false` won't destroy a
# repo that still holds images. docex sets force_delete on the project's
# ECR repos, but a partial destroy can leave images stranded — purge by
# name prefix as belt-and-suspenders.
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

# -- 3. SSM parameters under the project prefix --------------------------
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

# -- 4. tofu state backend (full retirement) -----------------------------
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

# -- 5. Compiled output --------------------------------------------------
echo "-- compiled infra/output"
rm -rf "$PROJECT_ROOT/infra/output/dev" \
       "$PROJECT_ROOT/infra/output/test" \
       "$PROJECT_ROOT/infra/output/stage" \
       "$PROJECT_ROOT/infra/output/prod" \
       "$PROJECT_ROOT/infra/output/project"

# -- 6. Local docker artifacts for dev/test envs -------------------------
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
