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
# Mod 053 (F15): SSM parameter paths use the underscore project form
# (`/${PROJECT_NAME}/…`, the `ssm_path` policy), but check the hyphenated
# form too in case any path slipped through under the DNS-labeled name.
ssm_params=""
for prefix in "$PROJECT_NAME" "$PROJECT_AWS_PREFIX"; do
  found="$(aws ssm describe-parameters \
    --parameter-filters "Key=Name,Option=BeginsWith,Values=/${prefix}/" \
    --query 'Parameters[*].Name' --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
  [[ -n "$found" ]] && ssm_params="${ssm_params}${found}"$'\n'
done
ssm_params="$(echo "$ssm_params" | grep -v '^$' | sort -u || true)"
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
# Mod 053 (F15): IAM role names are hyphenated (`${PROJECT_AWS_PREFIX}-…`),
# but a prior walk left an *underscored* orphan
# (`docex_smoke_elastic_task_execution`) that the hyphen-only query
# reported "clean" — masking the orphan that then blocked the next walk's
# projinfra phase-2 with EntityAlreadyExists. Scan BOTH forms so any
# orphaned role is reported, not hidden.
iam_roles=""
for prefix in "$PROJECT_AWS_PREFIX" "$PROJECT_NAME"; do
  for sep in "-" "_"; do
    found="$(aws iam list-roles \
      --query "Roles[?starts_with(RoleName, \`${prefix}${sep}\`)].RoleName" \
      --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
    [[ -n "$found" ]] && iam_roles="${iam_roles}${found}"$'\n'
  done
done
iam_roles="$(echo "$iam_roles" | grep -v '^$' | sort -u || true)"
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

# -- DynamoDB tables (underscored + hyphenated prefixes) -----------------
# Mod 053 (F15): DynamoDB table names preserve underscores (the `ddb`
# policy), so an orphaned table other than the known lock table would be
# missed by the single-name check above. Scan the full table list for
# either project-name form.
ddb_tables="$(aws dynamodb list-tables --query 'TableNames[]' --output text 2>/dev/null \
  | tr '\t' '\n' | grep -E "^(${PROJECT_NAME}|${PROJECT_AWS_PREFIX})[-_]" || true)"
if [[ -n "$ddb_tables" ]]; then mark_fail "DynamoDB tables" "$ddb_tables"; else report_ok "DynamoDB tables"; fi

# -- Env-tier resource types added after the 1.6.0 walk ------------------
# WHY these exist: the 1.6.0 pre-cut elastic walk's FIRST `release stage`
# died on seven `AlreadyExists` errors from orphans left by an earlier walk
# — and this script had reported "clean" beforehand. None of the types below
# were checked. Every one of them blocks a re-apply, so a false "clean" here
# converts into a failed release later, at the least convenient moment.
#
# The Service Discovery namespace is the sharpest case: its backing Route53
# hosted zone is named bare (`docex-smoke-elastic-stage.`, no parent suffix),
# so it looks like a stray artifact rather than a project resource, and the
# Route53 check above only looks for the project *zone*. It surfaced as
# `CANNOT_CREATE_HOSTED_ZONE … already been associated with the hosted zone`.

sgs="$(aws ec2 describe-security-groups \
  --query "SecurityGroups[?starts_with(GroupName, '${PROJECT_AWS_PREFIX}')].GroupName" \
  --output text 2>/dev/null | tr '\t' '\n' | grep . || true)"
if [[ -n "$sgs" ]]; then mark_fail "Security groups" "$sgs"; else report_ok "Security groups"; fi

sd_ns="$(aws servicediscovery list-namespaces \
  --query "Namespaces[?starts_with(Name, '${PROJECT_AWS_PREFIX}')].Name" \
  --output text 2>/dev/null | tr '\t' '\n' | grep . || true)"
if [[ -n "$sd_ns" ]]; then
  mark_fail "Service Discovery namespaces" "$sd_ns"
else
  report_ok "Service Discovery namespaces"
fi

db_subnet_groups="$(aws rds describe-db-subnet-groups \
  --query "DBSubnetGroups[?starts_with(DBSubnetGroupName, '${PROJECT_AWS_PREFIX}')].DBSubnetGroupName" \
  --output text 2>/dev/null | tr '\t' '\n' | grep . || true)"
if [[ -n "$db_subnet_groups" ]]; then
  mark_fail "RDS DB subnet groups" "$db_subnet_groups"
else
  report_ok "RDS DB subnet groups"
fi

# Log-group names use the ssm_path policy, which PRESERVES underscores.
log_groups="$(aws logs describe-log-groups --log-group-name-prefix "/${PROJECT_NAME}" \
  --query 'logGroups[].logGroupName' --output text 2>/dev/null | tr '\t' '\n' | grep . || true)"
if [[ -n "$log_groups" ]]; then mark_fail "CloudWatch log groups" "$log_groups"; else report_ok "CloudWatch log groups"; fi

efs="$(aws efs describe-file-systems \
  --query "FileSystems[?starts_with(CreationToken, '${PROJECT_AWS_PREFIX}')].CreationToken" \
  --output text 2>/dev/null | tr '\t' '\n' | grep . || true)"
if [[ -n "$efs" ]]; then mark_fail "EFS file systems" "$efs"; else report_ok "EFS file systems"; fi

# Target-group names are truncated to fit ELB's 32-char cap, so match on the
# hyphenated project prefix rather than a full emitted name.
tgs="$(aws elbv2 describe-target-groups \
  --query "TargetGroups[?starts_with(TargetGroupName, '${PROJECT_AWS_PREFIX}')].TargetGroupName" \
  --output text 2>/dev/null | tr '\t' '\n' | grep . || true)"
if [[ -n "$tgs" ]]; then mark_fail "ALB target groups" "$tgs"; else report_ok "ALB target groups"; fi

# A task-definition family stays ACTIVE until every revision is deregistered;
# `tofu destroy` deregisters only the revisions it owns, so families created
# by an earlier walk (and revisions superseded mid-walk) linger. Harmless to
# AWS, but they are project state and they mask what a walk actually left.
td_families="$(aws ecs list-task-definition-families --status ACTIVE \
  --query "families[?starts_with(@, '${PROJECT_AWS_PREFIX}')]" \
  --output text 2>/dev/null | tr '\t' '\n' | grep . || true)"
if [[ -n "$td_families" ]]; then
  mark_fail "ECS task-definition families (ACTIVE)" "$td_families"
else
  report_ok "ECS task-definition families"
fi

if [[ "$remaining" != "0" ]]; then
  echo
  echo "verify_clean: $remaining resource type(s) still present. teardown did not fully complete."
  exit 1
fi

echo
echo "verify_clean: clean."
