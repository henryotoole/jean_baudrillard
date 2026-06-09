# Implementation — Mod 044 — EC2-Traefik Reverse-Proxy Variant

## Context for fresh-context implementer

You are executing mod 044 — the campaign's largest mod. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`projinfra/ec2_traefik.md`](../../../../doctrine/infrastructure/specifics/projinfra/ec2_traefik.md) — exhaustive resource spec, IAM scoping, user_data behavior, lifecycle. Read it end-to-end before starting.
- [`cicl.md § Reverse Proxy`](../../../../doctrine/infrastructure/cicl.md#reverse-proxy) — the `reverse_proxy:` field values.

## Operator decisions binding on this implementation

Per [`overview.md § Operator Decisions`](./overview.md#operator-decisions):

- Both variants (EIP + PIP) in one mod, gated by Jinja conditionals.
- Polymorphic `reverse_proxy_security_group_id` output.
- user_data in a separate template file (`templates/ec2_traefik_user_data.sh.j2`).
- Initial SSM config: empty stub `http: { routers: {}, services: {} }`.
- Env-tier release SSM rerender: **stubbed out**. Mod 044 emits the SSM Parameter; release-flow push is a known v1 gap for follow-up.

## Step-by-step plan

### Step 1 — Propagate `reverse_proxy` to template render context

`reverse_proxy` is on `CICLDocument` (mod 031). Verify it flows into `emit_hcl_project`'s render context. If not present, add it via `compile.py`'s `run_compile` and `emit_hcl_project`'s kwargs.

The template needs `reverse_proxy` as a Jinja variable. After step 1, the template can conditional on `{% if reverse_proxy == "alb" %}` and `{% if reverse_proxy in ("ec2_traefik_eip", "ec2_traefik_pip") %}`.

Note: `reverse_proxy` defaults to `"alb"` for elastic projects when unset (per mod 031's `_validate_reverse_proxy_field`). Apply the same default in `compile.py` before passing to the template — or use `reverse_proxy or "alb"` in the call site. Pick one location and document it.

### Step 2 — Branch `project.tf.j2`

The ALB block from mod 038 (lines ~252+ after the ACM cert block) gets wrapped in `{% if reverse_proxy == "alb" %}...{% endif %}`. Below it, add:

```jinja
{% elif reverse_proxy in ("ec2_traefik_eip", "ec2_traefik_pip") %}
# EC2-traefik resource set — see implementation.md § Step 3
{% endif %}
```

Same for the ACM cert block from mod 037 — EC2-traefik uses traefik's built-in Let's Encrypt, NOT ACM, so the `aws_acm_certificate.stage`/`prod`, the validation records, and the cert outputs are all gated on `{% if reverse_proxy == "alb" %}`.

### Step 3 — Emit the EC2-traefik resource set

Inside the `{% elif reverse_proxy in (...) %}` branch, emit (in order):

1. **Ubuntu AMI lookup**:
   ```hcl
   data "aws_ami" "ubuntu" {
     most_recent = true
     owners      = ["099720109477"]
     filter {
       name   = "name"
       values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
     }
   }
   ```

2. **`aws_security_group.project_traefik`** — ingress 80/443 from `0.0.0.0/0`, egress allow-all, in `data.aws_vpc.master.id` (from mod 041), tagged `purpose = "ec2_traefik"`.

3. **IAM role + instance profile + policy** — see [`elastic_iam.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_iam.md) and the doctrine's `ec2_traefik.md § IAM Role` for the four scoped statement groups. Distinct from the task-execution role (different principal `ec2.amazonaws.com`).

4. **CloudWatch Log Group** — `/<project>/ec2_traefik`, `retention_in_days = 30`.

5. **SSM Parameter** — `name = "/<project>/ec2_traefik/config.yml"`, `type = "SecureString"`, `value` is the stub:
   ```yaml
   http:
     routers: {}
     services: {}
   ```
   Hardcode the stub value as a literal string in the HCL (Tofu will create the param with this value; future env-tier release will overwrite).
   
   Use `lifecycle { ignore_changes = [value] }` so subsequent `tofu apply` invocations don't fight with the (eventual) env-tier release-side updates.

6. **EBS volume** — `aws_ebs_volume.project_traefik_acme`, 8 GB gp3, in `us-east-1a` (use the primary-AZ subnet's AZ via `data.aws_subnet.primary_private.availability_zone`), tagged `purpose = "ec2_traefik_acme"` + `project = "<project>"` for discovery by the instance.

7. **EIP (variant-gated)**:
   ```jinja
   {% if reverse_proxy == "ec2_traefik_eip" %}
   resource "aws_eip" "project_traefik" {
     domain = "vpc"
     tags = { project = "{{ project }}", managed_by = "doctrine" }
   }
   {% endif %}
   ```

8. **`aws_instance.project_traefik`** — `t3.nano`, Ubuntu AMI, public subnet in `us-east-1a` (need to look up by AZ + tier=public). Pass the user_data from Step 4:
   ```hcl
   user_data = templatefile("${path.module}/ec2_traefik_user_data.sh", { ... })
   ```
   Actually — better since we're rendering via Jinja from docex: render the user_data inside Python and inject as a literal HEREDOC. See Step 4 for the file delivery mechanism.

   Attach the instance profile; specify the security group; set `associate_public_ip_address = true` (PIP variant) or `false` (EIP variant, where EIP attaches separately).

9. **EIP association (variant-gated)** — only for `ec2_traefik_eip`:
   ```hcl
   resource "aws_eip_association" "project_traefik" {
     instance_id   = aws_instance.project_traefik.id
     allocation_id = aws_eip.project_traefik.id
   }
   ```

10. **Five Route53 A-records** — for each of the 5 doctrine hosts. Records point at:
    - `aws_eip.project_traefik.public_ip` for EIP variant.
    - `aws_instance.project_traefik.public_ip` for PIP variant.
    
    TTL = 60s for PIP variant (fast propagation on IP changes); 60s also fine for EIP variant (consistency).

### Step 4 — Add `templates/ec2_traefik_user_data.sh.j2`

Create a new file with the bash script. Sketch:

```bash
#!/bin/bash
set -euo pipefail

# === Mount EBS cert volume ===
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
VOLUME_ID=$(aws ec2 describe-volumes --region "$REGION" \
  --filters "Name=tag:purpose,Values=ec2_traefik_acme" \
            "Name=tag:project,Values={{ project }}" \
  --query 'Volumes[0].VolumeId' --output text)
aws ec2 attach-volume --region "$REGION" \
  --volume-id "$VOLUME_ID" --instance-id "$INSTANCE_ID" --device /dev/sdh
# Wait, format if needed, mount
sleep 10
DEVICE=$(lsblk -o NAME,SERIAL | grep "$(echo $VOLUME_ID | tr -d -)" | awk '{print $1}')
if ! blkid /dev/$DEVICE; then mkfs.ext4 /dev/$DEVICE; fi
mkdir -p /etc/traefik/acme
mount /dev/$DEVICE /etc/traefik/acme

# === Install traefik ===
TRAEFIK_VERSION=v3.3.1
wget "https://github.com/traefik/traefik/releases/download/${TRAEFIK_VERSION}/traefik_${TRAEFIK_VERSION}_linux_amd64.tar.gz" -O /tmp/traefik.tar.gz
tar -xzf /tmp/traefik.tar.gz -C /usr/local/bin/ traefik
chmod +x /usr/local/bin/traefik

# === Static traefik config ===
cat > /etc/traefik/traefik.yml <<'EOF'
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

certificatesResolvers:
  doctrine:
    acme:
      email: {{ traefik_acme_email }}
      storage: /etc/traefik/acme/acme.json
      dnsChallenge:
        provider: route53

providers:
  file:
    filename: /etc/traefik/dynamic.yml
    watch: true

log:
  level: INFO
  filePath: /var/log/traefik/traefik.log

accessLog:
  filePath: /var/log/traefik/access.log
EOF

# === Initial dynamic config (will be overwritten by systemd timer) ===
mkdir -p /etc/traefik
cat > /etc/traefik/dynamic.yml <<'EOF'
http:
  routers: {}
  services: {}
EOF

# === systemd config-fetch timer ===
cat > /etc/systemd/system/docex-traefik-config.service <<'EOF'
[Unit]
Description=Fetch traefik dynamic config from SSM
[Service]
Type=oneshot
ExecStart=/usr/local/bin/aws ssm get-parameter \
  --name /{{ project }}/ec2_traefik/config.yml --with-decryption \
  --query 'Parameter.Value' --output text > /etc/traefik/dynamic.yml.new
ExecStartPost=/bin/sh -c 'cmp -s /etc/traefik/dynamic.yml /etc/traefik/dynamic.yml.new || mv /etc/traefik/dynamic.yml.new /etc/traefik/dynamic.yml'
EOF
cat > /etc/systemd/system/docex-traefik-config.timer <<'EOF'
[Unit]
Description=Fetch traefik dynamic config every 30s
[Timer]
OnBootSec=10s
OnUnitActiveSec=30s
[Install]
WantedBy=timers.target
EOF

{% if reverse_proxy == "ec2_traefik_pip" %}
# === systemd boot DNS update (PIP variant only) ===
cat > /etc/systemd/system/docex-traefik-dns-update.service <<'EOF'
[Unit]
Description=Update Route53 A-records to current public IP
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/docex-traefik-dns-update.sh
[Install]
WantedBy=multi-user.target
EOF
cat > /usr/local/bin/docex-traefik-dns-update.sh <<'EOF'
#!/bin/bash
set -euo pipefail
IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
HOSTED_ZONE_ID="{{ hosted_zone_id }}"
# ... ChangeResourceRecordSets batch for the 5 records pointing at $IP ...
EOF
chmod +x /usr/local/bin/docex-traefik-dns-update.sh
systemctl enable docex-traefik-dns-update.service
{% endif %}

# === Start traefik (with systemd) ===
cat > /etc/systemd/system/traefik.service <<'EOF'
[Unit]
Description=Traefik
After=network-online.target docex-traefik-config.service
[Service]
ExecStart=/usr/local/bin/traefik --configFile=/etc/traefik/traefik.yml
Restart=always
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now docex-traefik-config.timer
systemctl enable --now traefik
```

The implementer should refine this — it's an illustrative starting point. The key complexities:
- EBS volume attach by tag (the `lsblk + blkid` device lookup is finicky on different kernels).
- IDempotence (the script runs once on first boot; re-runs after instance replacement reuse the EBS volume).
- PIP boot DNS update — the inner Route53 batch script is non-trivial.

Render this template inside `emit_hcl_project` via Jinja's `env.get_template("ec2_traefik_user_data.sh.j2").render(...)`. Pass the rendered text to the HCL template as a context var (e.g. `traefik_user_data`), which `project.tf.j2` injects via:

```hcl
user_data = <<-USER_DATA
{{ traefik_user_data }}
USER_DATA
```

### Step 5 — Polymorphic `reverse_proxy_security_group_id` output

Add at the bottom of `project.tf.j2` (outside the variant-gated blocks):

```hcl
output "reverse_proxy_security_group_id" {
  value = {% if reverse_proxy == "alb" -%}
    aws_security_group.project_alb.id
  {%- else -%}
    aws_security_group.project_traefik.id
  {%- endif %}
}
```

Keep the existing `alb_security_group_id` output but gate it on `{% if reverse_proxy == "alb" %}` so it's only emitted for ALB.

Add similar gating to the other ALB-specific outputs (alb_arn, alb_dns_name, alb_zone_id, alb_https_listener_arn, alb_http_listener_arn, stage_cert_arn, prod_cert_arn) — wrap in `{% if reverse_proxy == "alb" %}` blocks.

### Step 6 — Env-tier emission changes

`main.tf.j2`:
- Line ~82: change `source_security_group_id = data.terraform_remote_state.project.outputs.alb_security_group_id` → `source_security_group_id = data.terraform_remote_state.project.outputs.reverse_proxy_security_group_id`.
- Lines ~141–164 (Route53 alias records): wrap in `{% if reverse_proxy == "alb" %}...{% endif %}`. EC2-traefik puts those records at project tier.

`hcl.py`:
- `_emit_listener_rule` (around line 510): wrap in a `reverse_proxy == "alb"` guard. EC2-traefik routes via SSM-pushed dynamic config, not env-tier listener rules.
- The `reverse_proxy` value needs to be threadable into `_emit_listener_rule`'s context. If `CompiledEnv` already carries it (verify), thread through.

### Step 7 — Tests

`tests/integration/test_compile.py`:

- New test_fixture: a project with `reverse_proxy: ec2_traefik_eip`. Compile it. Assert:
  - Project main.tf has the EC2-traefik resources (instance, EIP, EBS volume, IAM, SG, SSM param, log group, 5 A-records).
  - Project main.tf does NOT have ALB resources or ACM cert resources.
  - The `reverse_proxy_security_group_id` output exists; the `alb_*` outputs do NOT.
  - Env main.tf SG ingress source references `reverse_proxy_security_group_id`.
  - Env main.tf has no Route53 alias records (records are project-tier for EC2-traefik).
  - Env main.tf has no listener-rule resources.

- Same for `ec2_traefik_pip` variant, plus assert no EIP resource + assert the boot DNS-update systemd unit appears in user_data.

- Existing `reverse_proxy: alb` test fixture continues to work (default).

### Step 8 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

### Step 9 — Sanity sweep

```bash
# Variant gating in place
grep -n 'reverse_proxy' src/docex/emit/templates/project.tf.j2 src/docex/emit/templates/main.tf.j2 src/docex/emit/hcl.py

# user_data template file exists and is referenced
ls src/docex/emit/templates/ec2_traefik_user_data.sh.j2
grep -n 'ec2_traefik_user_data' src/docex/emit/hcl.py

# Polymorphic output present
grep -n 'reverse_proxy_security_group_id' src/docex/emit/templates/project.tf.j2 src/docex/emit/templates/main.tf.j2
```

## Out of scope

- **No env-tier SSM rerender on release.** Mod 044 emits the SSM Parameter with a stub config; the runtime push is a known v1 gap.
- **No ALB removal** — `alb` stays the default variant.
- **No HTTP-01 fallback config** — DNS-01 only.
- **No multi-region.**
- **No `test_projects/{fixed,elastic}/` edits.**

## Done criteria

- [ ] `reverse_proxy` available in project template render context (defaulting to `"alb"` for elastic).
- [ ] `project.tf.j2` branches: ALB resources gated on `reverse_proxy == "alb"`; EC2-traefik resources gated on `reverse_proxy in ("ec2_traefik_eip", "ec2_traefik_pip")`; EIP only when `"ec2_traefik_eip"`.
- [ ] `templates/ec2_traefik_user_data.sh.j2` exists, rendered + injected into `aws_instance.project_traefik.user_data`.
- [ ] Polymorphic `reverse_proxy_security_group_id` output present; ALB-specific outputs gated on `reverse_proxy == "alb"`.
- [ ] Env-tier per-network SG ingress consumes `reverse_proxy_security_group_id`; Route53 alias records and listener rules gated on `reverse_proxy == "alb"`.
- [ ] Tests cover all three variants (alb, ec2_traefik_eip, ec2_traefik_pip) at project tier and env tier.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/{fixed,elastic}/` edits.

Working tree dirty when finished. Do not commit.

**This mod is large. Plan ~3-4 hours of focused work. If you hit a wall — STOP and report.**
