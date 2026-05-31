# Fixed Infra - Specific Gaps

These are notes I am making during the first roll-out process on gaps I encountered. The idea here is that `fixed` prerequisite infrastructure MUST be setup manually outside of project scope but `docex` and the doctrine must still provide guidance for this. `docex` needs good descriptive failure modes and the doctrine probably needs a "setup guide" for fixed infrastructure.

### 1. Missing Stuff Manifest
We need a real manifest of what's missing on startup. The below is a sort of toplevel summary.

| Component | Fixed needs it? | Elastic needs it? |
| --------- | --------------- | ----------------- |
| Registry at `registry.luxrnd.tech` | ✓ — `infra.yml` declares it as `container_registry`; `docex containerize` pushes there | ✗ — elastic auto-provisions ECR via `docex bootstrap`; AWS creds handle auth |
| `~/.docker/config.json` | ✓ — `docker push` reads creds from here for the V2 registry | ✗ — ECR uses `aws ecr get-login-password` |
| SSH deploy keys in `infra/deploy_creds/` | ✓ — `docex release stage/prod` runs Ansible over SSH | ✗ — elastic releases use AWS APIs (SSM + `tofu apply`), no SSH |
| Traefik DNS-01 challenge | ✓ — needed for the `*.<env>.doctrine-fixed.luxrnd.tech` wildcard certs | ✗ — elastic uses an AWS ALB + ACM cert that DNS-validates through Route53 (AWS-internal) |
| IAM user for Traefik | ✓ — only exists to feed (4) | ✗ — same |


### 2. Central Traefik Instance

We're going to need a cert resolver specified in traefik by a standard name that docex uses to create stuff that sits on its network.

We're going to need a plan for network handling.