# docex Phase 4 image.
#
# Phase 2 added Docker CLI + compose plugin so the orchestrate package
# could shell out to docker. Phase 3 added git + openssh + ansible.
# Phase 4 adds:
#   - opentofu CLI 1.8.x (used by `release` and `migrate` against
#     elastic-foundation envs; also used in tests to validate emitted HCL)
#   - aws CLI v2 (operator-debugging only; docex's code path uses boto3)
#   - boto3 / botocore (the AWSClient chokepoint — see src/docex/aws/)
#
# The daemon itself is reached via a bind-mounted /var/run/docker.sock
# (configured in bin/docex).
#
# Base image is pinned by digest, not tag. To refresh the digest:
#   docker pull python:3.12-slim
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim
# The digest below was captured 2026-05-21. If your `docker build` fails
# with a manifest pull error, recapture the current digest and update.
FROM python:3.12-slim@sha256:9d3abd9fc11d06998ccdbdd93b4dd49b5ad7d67fcbbc11c016eb0eb2c2194891

WORKDIR /opt/docex

# Install docker CLI + compose plugin from Docker's apt repository, plus
# git and openssh-client from Debian.
#
# We pin the major versions baked into docex 0.3.0:
#   - docker-ce-cli 27.x, docker-compose-plugin 2.x
#   - git 2.x (debian bookworm provides 2.39.x)
#   - openssh-client 9.x (bookworm provides 9.2.x)
#
# We intentionally do NOT pin the exact patch versions because Debian's
# apt index does not retain historical minor releases indefinitely; the
# major-version pin is enough to make the image reproducible within a
# docex point release.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg git openssh-client \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && chmod a+r /etc/apt/keyrings/docker.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*

# Install ansible via pip with pinned transitive deps. We pin
# ansible-core 2.17.x (the LTS line as of docex 0.3.0); ansible-core
# rather than the full `ansible` package keeps the image lean — we
# install just the community.docker collection separately below.
RUN pip install --no-cache-dir "ansible-core==2.17.6"

# Install the community.docker Ansible collection. The emitted
# playbook templates use community.docker.docker_compose_v2 and
# community.docker.docker_container; ansible-galaxy installs them
# into the standard system collections path.
RUN ansible-galaxy collection install community.docker:==3.10.4

# ---------------------------------------------------------------------------
# Phase 4 additions
# ---------------------------------------------------------------------------
#
# OpenTofu CLI. Installed from the official release tarball so we can
# pin a specific version. 1.8.x is the current LTS line as of
# docex 0.4.0. unzip is required for the install script + the tarball.
ARG TOFU_VERSION=1.8.7
RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip \
 && curl -fsSL "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_linux_$(dpkg --print-architecture).zip" -o /tmp/tofu.zip \
 && unzip -q /tmp/tofu.zip -d /tmp/tofu \
 && install -m 0755 /tmp/tofu/tofu /usr/local/bin/tofu \
 && rm -rf /tmp/tofu /tmp/tofu.zip \
 && rm -rf /var/lib/apt/lists/* \
 && tofu version

# AWS CLI v2. Useful for operator debugging from inside the container;
# docex's own code uses boto3. We install via the upstream zip
# installer because Debian's repository AWS CLI is v1.
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscliv2.zip \
 && (cd /tmp && unzip -q awscliv2.zip) \
 && /tmp/aws/install \
 && rm -rf /tmp/aws /tmp/awscliv2.zip \
 && aws --version

# boto3 / botocore. Pinned in pyproject.toml so the pip install below
# picks them up; we don't pin them separately here. (Listed in
# dependencies block above.)

# Layer: project metadata. Changes least often, allows pip cache.
COPY pyproject.toml ./
COPY src/ ./src/
COPY tables/ /opt/docex/tables/
COPY doctrine_excerpts/ /opt/docex/doctrine_excerpts/
COPY ansible/ /opt/docex/ansible/

# Install docex itself with the [test] extra so the in-container test
# loop (``docker run --entrypoint pytest docex /opt/docex/tests``)
# works for CI. ``--no-cache-dir`` keeps the image lean.
RUN pip install --no-cache-dir ".[test]"

# Bake `safe.directory = *` into the image's system gitconfig. With
# the shim's --user uid mapping the in-container uid matches the host
# file owner and git's dubious-ownership check is satisfied anyway,
# but baking this in costs nothing and protects against edge cases
# where the image is run without --user (e.g. ad-hoc `docker run
# docex bash` for debugging).
RUN git config --system --add safe.directory '*'

# The shim sets `-w "$PROJECT_ROOT"` at runtime — bind-mounting the
# host project at the same path inside the container so DooD path
# resolution agrees in both directions. The image's WORKDIR is a
# sensible default for ad-hoc `docker run docex bash` debugging
# sessions; the shim overrides it.
WORKDIR /

ENTRYPOINT ["docex"]
