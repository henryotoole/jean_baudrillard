#!/usr/bin/env bash
# verify_clean.sh — fail loudly if any docex_smoke_elastic resources
# remain in AWS.
#
# Queries every resource type docex emits for elastic projects, filtered
# by project-name prefix. Exits 0 if everything is clean.

set -uo pipefail

PROJECT_NAME="docex_smoke_elastic"
AWS_REGION="us-east-1"
# S3 policy is hyphen+lower+63 (per doctrine naming_policies); DDB policy
# preserves underscores. Match what `projinfra` actually emits.
PROJECT_AWS_PREFIX="${PROJECT_NAME//_/-}"
STATE_BUCKET="${PROJECT_AWS_PREFIX}-tofu-state"
STATE_LOCK_TABLE="${PROJECT_NAME}_tofu_locks"

export AWS_REGION

remaining=0
mark_fail() {
  remaining=$((remaining + 1))
  echo "FAIL: $1"
  echo "$2" | sed 's/^/   /'
}
report_ok() { echo "OK:   $1"; }

# -- VPC -----------------------------------------------------------------
vpc_ids="$(aws ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=${PROJECT_NAME}" "Name=tag:Name,Values=${PROJECT_AWS_PREFIX}" \
  --query 'Vpcs[].VpcId' --output text 2>/dev/null || true)"
# WHY: AWS filters are AND across multiple Name=tag:Name entries; querying
# either-form requires two passes (we run a single more permissive query
# below and post-filter).
all_vpcs="$(aws ec2 describe-vpcs --query 'Vpcs[].{Id:VpcId,Tags:Tags}' --output json 2>/dev/null || echo '[]')"
matching_vpcs="$(echo "$all_vpcs" | python3 -c "
import json, sys
prefixes = ['${PROJECT_NAME}', '${PROJECT_AWS_PREFIX}']
for v in json.load(sys.stdin):
    for t in (v.get('Tags') or []):
        if t.get('Key') == 'Name' and any(t.get('Value','').startswith(p) for p in prefixes):
            print(v['Id'])
            break
" 2>/dev/null || true)"
if [[ -n "$matching_vpcs" ]]; then
  mark_fail "VPCs" "$matching_vpcs"
else
  report_ok "VPCs"
fi

# -- ECS clusters --------------------------------------------------------
ecs_clusters="$(aws ecs list-clusters --query 'clusterArns' --output text 2>/dev/null \
  | tr '\t' '\n' | grep -F "cluster/${PROJECT_AWS_PREFIX}" || true)"
if [[ -n "$ecs_clusters" ]]; then mark_fail "ECS clusters" "$ecs_clusters"; else report_ok "ECS clusters"; fi

# -- RDS instances -------------------------------------------------------
rds_ids="$(aws rds describe-db-instances \
  --query "DBInstances[?starts_with(DBInstanceIdentifier, \`${PROJECT_AWS_PREFIX}\`)].DBInstanceIdentifier" \
  --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
if [[ -n "$rds_ids" ]]; then mark_fail "RDS instances" "$rds_ids"; else report_ok "RDS instances"; fi

# -- Load balancers ------------------------------------------------------
albs="$(aws elbv2 describe-load-balancers \
  --query "LoadBalancers[?starts_with(LoadBalancerName, \`${PROJECT_AWS_PREFIX}\`)].LoadBalancerName" \
  --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
if [[ -n "$albs" ]]; then mark_fail "ALBs" "$albs"; else report_ok "ALBs"; fi

# -- ECR repositories ----------------------------------------------------
ecr_repos="$(aws ecr describe-repositories \
  --query "repositories[?starts_with(repositoryName, \`${PROJECT_NAME}/\`)].repositoryName" \
  --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
if [[ -n "$ecr_repos" ]]; then mark_fail "ECR repositories" "$ecr_repos"; else report_ok "ECR repositories"; fi

# -- SSM parameters ------------------------------------------------------
ssm_params="$(aws ssm describe-parameters \
  --parameter-filters "Key=Name,Option=BeginsWith,Values=/${PROJECT_NAME}/" \
  --query 'Parameters[*].Name' --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
if [[ -n "$ssm_params" ]]; then mark_fail "SSM parameters" "$ssm_params"; else report_ok "SSM parameters"; fi

# -- Route53 hosted zone -------------------------------------------------
zones="$(aws route53 list-hosted-zones \
  --query "HostedZones[?Name==\`docex-smoke-elastic.luxrnd.tech.\`].Id" \
  --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
if [[ -n "$zones" ]]; then mark_fail "Route53 zones" "$zones"; else report_ok "Route53 zones"; fi

# -- ACM certificate -----------------------------------------------------
certs="$(aws acm list-certificates \
  --query "CertificateSummaryList[?contains(DomainName, \`docex-smoke-elastic.luxrnd.tech\`)].CertificateArn" \
  --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
if [[ -n "$certs" ]]; then mark_fail "ACM certificates" "$certs"; else report_ok "ACM certificates"; fi

# -- IAM execution role --------------------------------------------------
iam_roles="$(aws iam list-roles \
  --query "Roles[?starts_with(RoleName, \`${PROJECT_AWS_PREFIX}-\`)].RoleName" \
  --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
if [[ -n "$iam_roles" ]]; then mark_fail "IAM roles" "$iam_roles"; else report_ok "IAM roles"; fi

# -- Tofu state backend --------------------------------------------------
if aws s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1; then
  mark_fail "Tofu state bucket" "$STATE_BUCKET"
else
  report_ok "Tofu state bucket"
fi
if aws dynamodb describe-table --table-name "$STATE_LOCK_TABLE" >/dev/null 2>&1; then
  mark_fail "Tofu lock table" "$STATE_LOCK_TABLE"
else
  report_ok "Tofu lock table"
fi

if [[ "$remaining" != "0" ]]; then
  echo
  echo "verify_clean: $remaining resource type(s) still present. teardown did not fully complete."
  exit 1
fi

echo
echo "verify_clean: clean."
