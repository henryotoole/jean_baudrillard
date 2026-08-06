#!/usr/bin/env bash
# verify_clean.sh — fail loudly if any docex_smoke_elastic resources
# remain in AWS.
#
# Queries every resource type docex emits for elastic projects, filtered
# by project-name prefix. Exits 0 if everything is clean.
#
# THE RULE THIS SCRIPT IS BUILT ON: a check that cannot answer must FAIL,
# not report zero.
#
# Every false green a verify_clean script has produced came from the same
# pattern — a query that errored (401, 404, unparseable body, expired AWS
# credentials) was swallowed with `|| true` / `|| echo '{}'`, produced an
# empty result, and was reported as "clean". A cleanup check that cannot
# fail is worse than no check at all, because it gets cited as proof. Do
# NOT add `|| true` to a query path to quiet a noisy failure; the noise is
# the feature.
#
# This script formerly carried 21 such sites. With expired credentials, the
# wrong region, or one missing IAM permission, every check reported OK and
# the script exited 0 — while RDS instances and ALBs kept billing. The
# structure below (preflight + `aws_query`) exists to make that outcome
# impossible, not merely unlikely.

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

# -- Credential preflight -------------------------------------------------
# WHY this runs first, and why it EXITS rather than marking one failure:
# every check below is an `aws` call, so expired credentials, an
# unconfigured region, or one missing IAM permission makes all of them
# unanswerable at once. Before this existed that produced ~20 `OK:` lines
# and exit 0 — the single most likely false green this script could emit,
# and the most consequential, because D.13 is the gate that certifies the
# AWS account has stopped costing money. Catching the cause once here is
# cheaper and far clearer than catching its twenty symptoms below.
#
# The account id and region are ECHOED deliberately. A perfectly clean run
# against the WRONG ACCOUNT is itself a false green, and it is the only one
# an operator cannot detect by reading this script's output — every line
# says OK and every line is true, of an account nobody asked about.
if ! aws_account="$(aws sts get-caller-identity --query 'Account' --output text 2>&1)"; then
  echo "FAIL: AWS credentials — cannot call sts get-caller-identity:"
  echo "$aws_account" | sed 's/^/   /'
  echo
  echo "verify_clean: ABORTED. Every check below is an AWS call and none could be"
  echo "              answered. This is NOT a clean result. Fix credentials and re-run."
  exit 1
fi
echo "==>   interrogating AWS account ${aws_account} in region ${AWS_REGION}"

# Run one AWS query, test ITS exit status, and hand the raw output to the
# caller in AWS_QUERY_OUT. Returns 1 (after mark_fail) if the call failed.
#
# CALL THIS AS A PLAIN COMMAND AND READ $AWS_QUERY_OUT.
# Never `x="$(aws_query …)"`. A function whose output is captured by
# command substitution runs in a SUBSHELL, so the `mark_fail` below — and
# the `remaining` it increments — are discarded when that subshell exits.
# The check would then be structurally incapable of failing, which is the
# precise bug this whole file is being rewritten to remove. This warning is
# repeated in the fixed seed's `registry_get` rather than shared: these
# scripts are standalone by design and must not acquire a common library.
#
# Post-filtering (`tr`, `grep`, `sort -u`, python) belongs to the CALLER,
# operating on $AWS_QUERY_OUT. That split is the point: `grep` exiting 1
# there means "nothing matched", which is the CLEAN answer and the one case
# where a non-zero status is not an error.
AWS_QUERY_OUT=""
aws_query() {
  local label="$1"; shift
  local err rc
  err="$(mktemp)"
  AWS_QUERY_OUT="$("$@" 2>"$err")"
  rc=$?
  if [[ "$rc" != "0" ]]; then
    mark_fail "$label" "the check could not answer (exit ${rc}):
$(cat "$err")"
    rm -f "$err"
    AWS_QUERY_OUT=""
    return 1
  fi
  rm -f "$err"
  return 0
}

# -- VPC -----------------------------------------------------------------
# WHY the permissive query plus a post-filter: AWS filters are AND across
# multiple `Name=tag:Name` entries, so a single call cannot match either
# name form. We list VPCs and filter locally instead.
#
# (A second, narrower `describe-vpcs --filters …` call used to sit here.
# Its result was assigned to `vpc_ids` and never read by anything — dead
# since the permissive query superseded it. Converting a query nobody reads
# into one that can fail the script would add a failure mode for no
# information, so it is deleted rather than converted.)
if aws_query "VPCs" aws ec2 describe-vpcs \
    --query 'Vpcs[].{Id:VpcId,Tags:Tags}' --output json; then
  # An unparseable AWS response is exactly as unanswerable as a failed
  # call, so the python filter reports rather than yielding an empty list.
  if ! matching_vpcs="$(printf '%s' "$AWS_QUERY_OUT" | python3 -c "
import json, sys
prefixes = ['${PROJECT_NAME}', '${PROJECT_AWS_PREFIX}']
for v in json.load(sys.stdin):
    for t in (v.get('Tags') or []):
        if t.get('Key') == 'Name' and any(t.get('Value','').startswith(p) for p in prefixes):
            print(v['Id'])
            break
")"; then
    mark_fail "VPCs" "describe-vpcs returned a body python could not parse"
  elif [[ -n "$matching_vpcs" ]]; then
    mark_fail "VPCs" "$matching_vpcs"
  else
    report_ok "VPCs"
  fi
fi

# -- ECS clusters --------------------------------------------------------
if aws_query "ECS clusters" aws ecs list-clusters --query 'clusterArns' --output text; then
  ecs_clusters="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep -F "cluster/${PROJECT_AWS_PREFIX}" || true)"
  if [[ -n "$ecs_clusters" ]]; then mark_fail "ECS clusters" "$ecs_clusters"; else report_ok "ECS clusters"; fi
fi

# -- RDS instances -------------------------------------------------------
if aws_query "RDS instances" aws rds describe-db-instances \
    --query "DBInstances[?starts_with(DBInstanceIdentifier, \`${PROJECT_AWS_PREFIX}\`)].DBInstanceIdentifier" \
    --output text; then
  rds_ids="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep -v '^$' || true)"
  if [[ -n "$rds_ids" ]]; then mark_fail "RDS instances" "$rds_ids"; else report_ok "RDS instances"; fi
fi

# -- Load balancers ------------------------------------------------------
if aws_query "ALBs" aws elbv2 describe-load-balancers \
    --query "LoadBalancers[?starts_with(LoadBalancerName, \`${PROJECT_AWS_PREFIX}\`)].LoadBalancerName" \
    --output text; then
  albs="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep -v '^$' || true)"
  if [[ -n "$albs" ]]; then mark_fail "ALBs" "$albs"; else report_ok "ALBs"; fi
fi

# -- ECR repositories ----------------------------------------------------
if aws_query "ECR repositories" aws ecr describe-repositories \
    --query "repositories[?starts_with(repositoryName, \`${PROJECT_NAME}/\`)].repositoryName" \
    --output text; then
  ecr_repos="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep -v '^$' || true)"
  if [[ -n "$ecr_repos" ]]; then mark_fail "ECR repositories" "$ecr_repos"; else report_ok "ECR repositories"; fi
fi

# -- SSM parameters ------------------------------------------------------
# Mod 053 (F15): SSM parameter paths use the underscore project form
# (`/${PROJECT_NAME}/…`, the `ssm_path` policy), but check the hyphenated
# form too in case any path slipped through under the DNS-labeled name.
ssm_params=""
ssm_answered=1
for prefix in "$PROJECT_NAME" "$PROJECT_AWS_PREFIX"; do
  if ! aws_query "SSM parameters" aws ssm describe-parameters \
      --parameter-filters "Key=Name,Option=BeginsWith,Values=/${prefix}/" \
      --query 'Parameters[*].Name' --output text; then
    # One unanswerable pass makes the whole check unanswerable: a partial
    # scan cannot prove absence.
    ssm_answered=0
    break
  fi
  found="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep -v '^$' || true)"
  [[ -n "$found" ]] && ssm_params="${ssm_params}${found}"$'\n'
done
if [[ "$ssm_answered" == "1" ]]; then
  ssm_params="$(printf '%s' "$ssm_params" | grep -v '^$' | sort -u || true)"
  if [[ -n "$ssm_params" ]]; then mark_fail "SSM parameters" "$ssm_params"; else report_ok "SSM parameters"; fi
fi

# -- Route53 hosted zone -------------------------------------------------
if aws_query "Route53 zones" aws route53 list-hosted-zones \
    --query "HostedZones[?Name==\`docex-smoke-elastic.luxrnd.tech.\`].Id" \
    --output text; then
  zones="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep -v '^$' || true)"
  if [[ -n "$zones" ]]; then mark_fail "Route53 zones" "$zones"; else report_ok "Route53 zones"; fi
fi

# -- ACM certificate -----------------------------------------------------
if aws_query "ACM certificates" aws acm list-certificates \
    --query "CertificateSummaryList[?contains(DomainName, \`docex-smoke-elastic.luxrnd.tech\`)].CertificateArn" \
    --output text; then
  certs="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep -v '^$' || true)"
  if [[ -n "$certs" ]]; then mark_fail "ACM certificates" "$certs"; else report_ok "ACM certificates"; fi
fi

# -- IAM execution role --------------------------------------------------
# Mod 053 (F15): IAM role names are hyphenated (`${PROJECT_AWS_PREFIX}-…`),
# but a prior walk left an *underscored* orphan
# (`docex_smoke_elastic_task_execution`) that the hyphen-only query
# reported "clean" — masking the orphan that then blocked the next walk's
# projinfra phase-2 with EntityAlreadyExists. Scan BOTH forms so any
# orphaned role is reported, not hidden.
iam_roles=""
iam_answered=1
for prefix in "$PROJECT_AWS_PREFIX" "$PROJECT_NAME"; do
  [[ "$iam_answered" == "1" ]] || break
  for sep in "-" "_"; do
    if ! aws_query "IAM roles" aws iam list-roles \
        --query "Roles[?starts_with(RoleName, \`${prefix}${sep}\`)].RoleName" \
        --output text; then
      iam_answered=0
      break
    fi
    found="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep -v '^$' || true)"
    [[ -n "$found" ]] && iam_roles="${iam_roles}${found}"$'\n'
  done
done
if [[ "$iam_answered" == "1" ]]; then
  iam_roles="$(printf '%s' "$iam_roles" | grep -v '^$' | sort -u || true)"
  if [[ -n "$iam_roles" ]]; then mark_fail "IAM roles" "$iam_roles"; else report_ok "IAM roles"; fi
fi

# -- Tofu state backend --------------------------------------------------
# PRESENCE CHECKS — READ THIS BEFORE SIMPLIFYING.
#
# `head-bucket` and `describe-table` both exit non-zero for TWO completely
# different situations: the resource is absent (CLEAN — what we want), or
# the call could not be made at all (UNANSWERABLE — expired token, denied
# permission, wrong region, network failure). The old form
# `if aws … >/dev/null 2>&1; then mark_fail; else report_ok; fi` mapped
# BOTH onto `report_ok`, so a credentials problem printed a clean bucket.
#
# The only way to tell them apart is the error text, so it is inspected
# rather than discarded. Do NOT collapse this back into the one-liner.
s3_err="$(aws s3api head-bucket --bucket "$STATE_BUCKET" 2>&1 >/dev/null)"
s3_rc=$?
if [[ "$s3_rc" == "0" ]]; then
  mark_fail "Tofu state bucket" "$STATE_BUCKET"
elif printf '%s' "$s3_err" | grep -qE '404|NoSuchBucket|Not Found'; then
  report_ok "Tofu state bucket"
else
  mark_fail "Tofu state bucket" "the check could not answer:
$s3_err"
fi

ddb_err="$(aws dynamodb describe-table --table-name "$STATE_LOCK_TABLE" 2>&1 >/dev/null)"
ddb_rc=$?
if [[ "$ddb_rc" == "0" ]]; then
  mark_fail "Tofu lock table" "$STATE_LOCK_TABLE"
elif printf '%s' "$ddb_err" | grep -q 'ResourceNotFoundException'; then
  report_ok "Tofu lock table"
else
  mark_fail "Tofu lock table" "the check could not answer:
$ddb_err"
fi

# -- DynamoDB tables (underscored + hyphenated prefixes) -----------------
# Mod 053 (F15): DynamoDB table names preserve underscores (the `ddb`
# policy), so an orphaned table other than the known lock table would be
# missed by the single-name check above. Scan the full table list for
# either project-name form.
if aws_query "DynamoDB tables" aws dynamodb list-tables --query 'TableNames[]' --output text; then
  ddb_tables="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' \
    | grep -E "^(${PROJECT_NAME}|${PROJECT_AWS_PREFIX})[-_]" || true)"
  if [[ -n "$ddb_tables" ]]; then mark_fail "DynamoDB tables" "$ddb_tables"; else report_ok "DynamoDB tables"; fi
fi

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

if aws_query "Security groups" aws ec2 describe-security-groups \
    --query "SecurityGroups[?starts_with(GroupName, '${PROJECT_AWS_PREFIX}')].GroupName" \
    --output text; then
  sgs="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep . || true)"
  if [[ -n "$sgs" ]]; then mark_fail "Security groups" "$sgs"; else report_ok "Security groups"; fi
fi

if aws_query "Service Discovery namespaces" aws servicediscovery list-namespaces \
    --query "Namespaces[?starts_with(Name, '${PROJECT_AWS_PREFIX}')].Name" \
    --output text; then
  sd_ns="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep . || true)"
  if [[ -n "$sd_ns" ]]; then
    mark_fail "Service Discovery namespaces" "$sd_ns"
  else
    report_ok "Service Discovery namespaces"
  fi
fi

if aws_query "RDS DB subnet groups" aws rds describe-db-subnet-groups \
    --query "DBSubnetGroups[?starts_with(DBSubnetGroupName, '${PROJECT_AWS_PREFIX}')].DBSubnetGroupName" \
    --output text; then
  db_subnet_groups="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep . || true)"
  if [[ -n "$db_subnet_groups" ]]; then
    mark_fail "RDS DB subnet groups" "$db_subnet_groups"
  else
    report_ok "RDS DB subnet groups"
  fi
fi

# Log-group names use the ssm_path policy, which PRESERVES underscores.
if aws_query "CloudWatch log groups" aws logs describe-log-groups \
    --log-group-name-prefix "/${PROJECT_NAME}" \
    --query 'logGroups[].logGroupName' --output text; then
  log_groups="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep . || true)"
  if [[ -n "$log_groups" ]]; then mark_fail "CloudWatch log groups" "$log_groups"; else report_ok "CloudWatch log groups"; fi
fi

if aws_query "EFS file systems" aws efs describe-file-systems \
    --query "FileSystems[?starts_with(CreationToken, '${PROJECT_AWS_PREFIX}')].CreationToken" \
    --output text; then
  efs="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep . || true)"
  if [[ -n "$efs" ]]; then mark_fail "EFS file systems" "$efs"; else report_ok "EFS file systems"; fi
fi

# Target-group names are truncated to fit ELB's 32-char cap, so match on the
# hyphenated project prefix rather than a full emitted name.
if aws_query "ALB target groups" aws elbv2 describe-target-groups \
    --query "TargetGroups[?starts_with(TargetGroupName, '${PROJECT_AWS_PREFIX}')].TargetGroupName" \
    --output text; then
  tgs="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep . || true)"
  if [[ -n "$tgs" ]]; then mark_fail "ALB target groups" "$tgs"; else report_ok "ALB target groups"; fi
fi

# A task-definition family stays ACTIVE until every revision is deregistered;
# `tofu destroy` deregisters only the revisions it owns, so families created
# by an earlier walk (and revisions superseded mid-walk) linger. Harmless to
# AWS, but they are project state and they mask what a walk actually left.
if aws_query "ECS task-definition families (ACTIVE)" aws ecs list-task-definition-families \
    --status ACTIVE --query "families[?starts_with(@, '${PROJECT_AWS_PREFIX}')]" \
    --output text; then
  td_families="$(printf '%s' "$AWS_QUERY_OUT" | tr '\t' '\n' | grep . || true)"
  if [[ -n "$td_families" ]]; then
    mark_fail "ECS task-definition families (ACTIVE)" "$td_families"
  else
    report_ok "ECS task-definition families"
  fi
fi

# -- Local docker images -------------------------------------------------
# WHY an AWS-facing script checks the local daemon: an elastic project's
# `dev` and `test` envs compile to fixed-style compose stacks on this
# machine, and `containerize` tags images locally before pushing to ECR.
# This script had NO local-image check at all, and `teardown.sh` step 9
# swept containers, networks and volumes but not images — so every walk
# left stale images behind (13 of them at the time this was written,
# including retired `reaper` images at 0.0.15–0.0.18) while reporting
# clean. Same defect class as the fixed seed's image grep.
#
# Both name forms, and NO left anchor: the project name appears
# MID-STRING in the ECR-prefixed, stage-tester and docex-test forms.
# The docker call and the grep are deliberately SEPARATE statements. `grep`
# exits 1 when nothing matches, which is the CLEAN answer and the one case
# where a non-zero status is not an error — but a single piped `|| true`
# cannot tell "nothing matched" from "the docker daemon is not running",
# and would report the second as clean. See the rule at the top of this file.
docker_err="$(mktemp)"
if ! all_images="$(docker images --format '{{.Repository}}:{{.Tag}}' 2>"$docker_err")"; then
  mark_fail "local docker images" "the check could not answer:
$(cat "$docker_err")"
else
  local_images="$(printf '%s\n' "$all_images" \
    | grep -E "(${PROJECT_NAME}|${PROJECT_AWS_PREFIX})[-_/:]" || true)"
  if [[ -n "$local_images" ]]; then
    mark_fail "local docker images" "$local_images"
  else
    report_ok "local docker images"
  fi
fi
rm -f "$docker_err"

if [[ "$remaining" != "0" ]]; then
  echo
  echo "verify_clean: $remaining resource type(s) still present. teardown did not fully complete."
  exit 1
fi

echo
echo "verify_clean: clean."
