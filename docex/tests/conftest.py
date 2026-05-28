"""Pytest configuration: make ``src/`` importable for tests.

Phase 2 additions: a ``FakeDockerClient`` fixture that records every
call made against it, so the orchestrate-layer unit tests can assert
the exact sequence of docker invocations without spawning subprocesses.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# Fake docker client
# ---------------------------------------------------------------------------


@dataclass
class FakeDockerClient:
    """Recording, scriptable stand-in for ``DockerClient``.

    - ``calls`` records every invocation as a tuple. Tests assert against
      this list directly.
    - ``available`` controls what ``is_available()`` returns.
    - ``ps_services`` controls what ``compose_ps()`` returns.
    - ``exit_codes`` is a dict keyed by ``(method, *positional_strs)``
      that overrides the default exit code of 0. Useful for scripting
      "the second migrate.sh fails" scenarios.
    - ``default_exit`` is the fallback exit code (0 unless overridden).
    """

    available: bool = True
    ps_services: list[str] = field(default_factory=list)
    exit_codes: dict[tuple, int] = field(default_factory=dict)
    default_exit: int = 0
    calls: list[tuple] = field(default_factory=list)

    # -- protocol ------------------------------------------------------

    def is_available(self) -> bool:
        self.calls.append(("is_available",))
        return self.available

    def compose_up(self, compose_file: Path, *, build: bool = True, detach: bool = True,
                   env_file: Path | None = None) -> int:
        key = ("compose_up", str(compose_file), build, detach)
        self.calls.append(key)
        return self.exit_codes.get(key, self._fallback("compose_up"))

    def compose_down(self, compose_file: Path, *, preserve_volumes: bool = True,
                     env_file: Path | None = None) -> int:
        key = ("compose_down", str(compose_file), preserve_volumes)
        self.calls.append(key)
        return self.exit_codes.get(key, self._fallback("compose_down"))

    def compose_run_one_off(
        self,
        compose_file: Path,
        service: str,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        env_file: Path | None = None,
    ) -> int:
        key = ("compose_run_one_off", str(compose_file), service, tuple(command))
        self.calls.append(key)
        return self.exit_codes.get(key, self._fallback("compose_run_one_off"))

    def compose_exec(self, compose_file: Path, service: str, command: list[str],
                     *, env_file: Path | None = None) -> int:
        key = ("compose_exec", str(compose_file), service, tuple(command))
        self.calls.append(key)
        # Allow scripting failure for ("compose_exec", svc, cmd_tuple).
        return self.exit_codes.get(key, self._fallback("compose_exec", service, tuple(command)))

    def compose_ps(self, compose_file: Path, *, env_file: Path | None = None) -> list[str]:
        self.calls.append(("compose_ps", str(compose_file)))
        return list(self.ps_services)

    def build_image(self, context: Path, *, target: str, tag: str) -> int:
        key = ("build_image", str(context), target, tag)
        self.calls.append(key)
        return self.exit_codes.get(key, self._fallback("build_image"))

    def run_one_shot(
        self,
        image: str,
        command: list[str],
        *,
        mounts: list[tuple[Path, str]] | None = None,
        remove: bool = True,
        env: dict[str, str] | None = None,
        network: str | None = None,
    ) -> int:
        # Record env + network on Phase 3 calls (stagetest needs them).
        key = ("run_one_shot", image, tuple(command))
        full = (
            "run_one_shot",
            image,
            tuple(command),
            tuple(sorted((env or {}).items())),
            network,
            tuple(f"{h}:{c}" for h, c in (mounts or [])),
        )
        self.calls.append(full)
        return self.exit_codes.get(key, self._fallback("run_one_shot"))

    # ------- Phase 3 additions: buildx + push + image inspect --------

    def buildx_build(
        self,
        *,
        context: Path,
        dockerfile: Path,
        target: str,
        platform: str,
        tag: str,
    ) -> int:
        key = ("buildx_build", str(context), str(dockerfile), target, platform, tag)
        self.calls.append(key)
        return self.exit_codes.get(key, self._fallback("buildx_build"))

    def push(self, tag: str) -> int:
        key = ("push", tag)
        self.calls.append(key)
        return self.exit_codes.get(key, self._fallback("push"))

    def login(self, registry: str, *, username: str, password: str) -> int:
        key = ("login", registry, username)
        self.calls.append(key)
        return self.exit_codes.get(key, self._fallback("login"))

    def inspect_image_digest(self, tag: str) -> str:
        self.calls.append(("inspect_image_digest", tag))
        return f"sha256:fakedigest-for-{tag}"

    # -- internals -----------------------------------------------------

    def _fallback(self, method: str, *parts) -> int:
        # Lookup by (method, *parts) shape for finer scripting.
        if parts:
            short = ("exit", method, *parts)
            if short in self.exit_codes:
                return self.exit_codes[short]
        return self.exit_codes.get(("exit", method), self.default_exit)


@pytest.fixture
def fake_docker() -> FakeDockerClient:
    """Pytest fixture for a fresh FakeDockerClient per test."""
    return FakeDockerClient()


# ---------------------------------------------------------------------------
# Sample-project context loader for orchestrate-layer tests.
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_ctx(tmp_path: Path):
    """Load a ProjectContext from a fresh copy of the sample fixture.

    The fixture is copied into ``tmp_path`` so orchestrate tests that
    invoke ``ensure_compiled`` (which writes infra/output/) don't dirty
    the on-disk fixture.
    """
    from docex.context import load_project_context

    fixture = _REPO_ROOT / "tests" / "fixtures" / "sample_project"
    dest = tmp_path / "project"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return load_project_context(dest)


@pytest.fixture
def elastic_ctx(tmp_path: Path):
    """Same shape as ``sample_ctx`` but loads the elastic fixture.

    Phase 3's unit tests use this to verify elastic stage/prod paths
    still print stub messages.
    """
    from docex.context import load_project_context

    fixture = _REPO_ROOT / "tests" / "fixtures" / "sample_project_elastic"
    dest = tmp_path / "project_elastic"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return load_project_context(dest)


# ---------------------------------------------------------------------------
# Fake git client (Phase 3).
# ---------------------------------------------------------------------------


@dataclass
class FakeGitClient:
    """Recording, scriptable stand-in for ``GitClient``.

    Each method records its arguments into ``calls`` so tests can
    assert the exact git invocations made by ``check`` / ``merge`` /
    ``containerize``. The exit-code map ``exit_codes`` lets tests
    script failures: e.g. ``exit_codes[("rebase",)] = 1`` makes the
    next rebase return 1.

    Several inspect-style methods return values rather than exit codes;
    those are scripted via attributes (``branch``, ``head``, ``clean``,
    ``tags``, ``tag_exists_map``).
    """

    clean: bool = True
    branch: str = "feature/x"
    head: str = "abc1234"
    tags: list[str] = field(default_factory=list)
    tag_exists_map: dict[str, bool] = field(default_factory=dict)
    merge_bases: dict[tuple, str] = field(default_factory=dict)
    file_at_ref: dict[tuple, str] = field(default_factory=dict)
    exit_codes: dict[tuple, int] = field(default_factory=dict)
    default_exit: int = 0
    calls: list[tuple] = field(default_factory=list)

    # -- reads --------------------------------------------------------

    def is_clean(self, cwd):
        self.calls.append(("is_clean", str(cwd)))
        return self.clean

    def current_branch(self, cwd):
        self.calls.append(("current_branch", str(cwd)))
        return self.branch

    def head_sha(self, cwd, *, short=False):
        self.calls.append(("head_sha", str(cwd), short))
        return self.head[:7] if short else self.head

    def merge_base(self, cwd, a, b):
        self.calls.append(("merge_base", str(cwd), a, b))
        return self.merge_bases.get((a, b), "")

    def tag_exists(self, cwd, name):
        self.calls.append(("tag_exists", str(cwd), name))
        if name in self.tag_exists_map:
            return self.tag_exists_map[name]
        return name in self.tags

    def list_tags(self, cwd, *, pattern=None):
        self.calls.append(("list_tags", str(cwd), pattern))
        return list(self.tags)

    # -- writes -------------------------------------------------------

    def fetch(self, cwd, *, remote="origin"):
        key = ("fetch", remote)
        self.calls.append(("fetch", str(cwd), remote))
        return self.exit_codes.get(key, self.default_exit)

    def rebase(self, cwd, onto):
        key = ("rebase", onto)
        self.calls.append(("rebase", str(cwd), onto))
        return self.exit_codes.get(key, self.default_exit)

    def rebase_abort(self, cwd):
        self.calls.append(("rebase_abort", str(cwd)))
        return self.exit_codes.get(("rebase_abort",), self.default_exit)

    def fast_forward(self, cwd, branch, to_ref):
        key = ("fast_forward", branch, to_ref)
        self.calls.append(("fast_forward", str(cwd), branch, to_ref))
        return self.exit_codes.get(key, self.default_exit)

    def tag(self, cwd, name, *, ref="HEAD"):
        key = ("tag", name, ref)
        self.calls.append(("tag", str(cwd), name, ref))
        # Once we successfully tag, record it.
        rc = self.exit_codes.get(key, self.default_exit)
        if rc == 0:
            self.tags.append(name)
        return rc

    def push(self, cwd, *, remote="origin", refs):
        key = ("push", remote, tuple(refs))
        self.calls.append(("push", str(cwd), remote, tuple(refs)))
        return self.exit_codes.get(key, self.default_exit)

    def delete_branch(self, cwd, name, *, remote=False):
        key = ("delete_branch", name, remote)
        self.calls.append(("delete_branch", str(cwd), name, remote))
        return self.exit_codes.get(key, self.default_exit)

    def worktree_add(self, cwd, path, *, branch=None, ref="HEAD"):
        key = ("worktree_add", str(path))
        self.calls.append(("worktree_add", str(cwd), str(path), branch, ref))
        rc = self.exit_codes.get(key, self.default_exit)
        # Materialize the worktree directory so the orchestrate layer's
        # filesystem checks find something there.
        if rc == 0:
            Path(path).mkdir(parents=True, exist_ok=True)
        return rc

    def worktree_remove(self, cwd, path, *, force=False):
        key = ("worktree_remove", str(path))
        self.calls.append(("worktree_remove", str(cwd), str(path), force))
        rc = self.exit_codes.get(key, self.default_exit)
        if rc == 0 and Path(path).exists():
            shutil.rmtree(path, ignore_errors=True)
        return rc

    def checkout(self, cwd, ref):
        self.calls.append(("checkout", str(cwd), ref))
        return self.exit_codes.get(("checkout", ref), self.default_exit)


@pytest.fixture
def fake_git() -> FakeGitClient:
    """Pytest fixture: fresh FakeGitClient per test."""
    return FakeGitClient()


# ---------------------------------------------------------------------------
# Fake ansible runner (Phase 3).
# ---------------------------------------------------------------------------


@dataclass
class RecordingAnsibleRunner:
    """Recording callable for ``run_playbook``. Returns ``exit_code``
    on every call; records args for assertion."""

    exit_code: int = 0
    calls: list[dict] = field(default_factory=list)

    def __call__(self, playbook, inventory, **kwargs):
        self.calls.append(
            {"playbook": playbook, "inventory": inventory, **kwargs}
        )
        return self.exit_code


@pytest.fixture
def fake_ansible() -> RecordingAnsibleRunner:
    return RecordingAnsibleRunner()


# ---------------------------------------------------------------------------
# Fake AWS client (Phase 4).
# ---------------------------------------------------------------------------


@dataclass
class FakeAWSClient:
    """Recording, scriptable stand-in for ``AWSClient``.

    Same recorder pattern as :class:`FakeDockerClient` / :class:`FakeGitClient`.

    - ``calls`` records every method invocation as ``(name, args, kwargs)``.
    - ``account_id`` controls what ``caller_identity()`` returns.
    - ``bucket_exists`` / ``table_exists`` control the bootstrap probes.
    - ``ecs_exit_codes`` maps task-arn → container exit code; the first
      RunTask returns ``task-<n>`` so a test can script multi-call flows.
    - ``raise_on`` is a dict ``{method_name: Exception}``; first call to
      that method raises (used to test idempotence + error paths).
    - ``vpc_id``, ``subnets``, ``sg_id``, ``cluster_arn`` are scripted
      lookup return values.
    """

    account_id: str = "123456789012"
    bucket_exists: bool = False
    table_exists: bool = False
    vpc_id: str = "vpc-fake0001"
    subnets: list[str] = field(default_factory=lambda: ["subnet-a", "subnet-b"])
    sg_id: str = "sg-fake0001"
    cluster_arn: str = "arn:aws:ecs:us-east-1:123456789012:cluster/fake"
    ecs_exit_codes: dict[str, int] = field(default_factory=dict)
    raise_on: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)
    _task_counter: int = 0

    # -- internals -----------------------------------------------------

    def _record(self, _method, *args, **kwargs) -> None:
        self.calls.append((_method, args, kwargs))
        if _method in self.raise_on:
            exc = self.raise_on.pop(_method)
            raise exc

    # -- identity ------------------------------------------------------

    def caller_identity(self) -> str:
        self._record("caller_identity")
        return self.account_id

    # -- SSM -----------------------------------------------------------

    def ssm_put_parameter(
        self, name: str, value: str, *, overwrite: bool = True
    ) -> None:
        self._record("ssm_put_parameter", name, value, overwrite=overwrite)

    # -- S3 ------------------------------------------------------------

    def s3_bucket_exists(self, name: str) -> bool:
        self._record("s3_bucket_exists", name)
        return self.bucket_exists

    def s3_create_bucket(self, name: str, *, region: str) -> None:
        self._record("s3_create_bucket", name, region=region)
        # After create, subsequent existence checks should see it.
        self.bucket_exists = True

    def s3_enable_versioning(self, name: str) -> None:
        self._record("s3_enable_versioning", name)

    def s3_enable_encryption(self, name: str) -> None:
        self._record("s3_enable_encryption", name)

    def s3_block_public_access(self, name: str) -> None:
        self._record("s3_block_public_access", name)

    # -- DynamoDB ------------------------------------------------------

    def ddb_table_exists(self, name: str) -> bool:
        self._record("ddb_table_exists", name)
        return self.table_exists

    def ddb_create_locking_table(self, name: str) -> None:
        self._record("ddb_create_locking_table", name)
        self.table_exists = True

    # -- ECS -----------------------------------------------------------

    def ecs_register_task_definition(self, family: str, definition: dict) -> str:
        self._record("ecs_register_task_definition", family, definition)
        return f"arn:aws:ecs:us-east-1:123456789012:task-definition/{family}:1"

    def ecs_run_task(
        self,
        *,
        cluster: str,
        task_definition: str,
        subnets: list[str],
        security_groups: list[str],
    ) -> str:
        self._task_counter += 1
        arn = f"arn:aws:ecs:us-east-1:123456789012:task/fake/{self._task_counter:08d}"
        self._record(
            "ecs_run_task",
            cluster=cluster,
            task_definition=task_definition,
            subnets=list(subnets),
            security_groups=list(security_groups),
            task_arn=arn,
        )
        return arn

    def ecs_wait_for_task(
        self, *, cluster: str, task_arn: str, timeout_s: int = 600
    ) -> int:
        self._record(
            "ecs_wait_for_task",
            cluster=cluster, task_arn=task_arn, timeout_s=timeout_s,
        )
        # Scripted exit codes by task ARN; default 0 if unset.
        return self.ecs_exit_codes.get(task_arn, 0)

    # -- ECR -----------------------------------------------------------

    def ecr_authorization_token(self) -> tuple[str, str]:
        self._record("ecr_authorization_token")
        return ("AWS", "fake-ecr-token")

    # -- Lookups -------------------------------------------------------

    def lookup_project_vpc(self, *, project: str) -> str:
        """Optional helper used by ``orchestrate.migrate._lookup_project_vpc``
        when present on the fake. Avoids drilling into the boto3 client."""
        self._record("lookup_project_vpc", project=project)
        return self.vpc_id

    def get_default_subnets(self, *, vpc_id: str, tier: str) -> list[str]:
        self._record("get_default_subnets", vpc_id=vpc_id, tier=tier)
        return list(self.subnets)

    def get_security_group_id(self, *, vpc_id: str, name: str) -> str:
        self._record("get_security_group_id", vpc_id=vpc_id, name=name)
        return self.sg_id

    def get_ecs_cluster_arn(self, name: str) -> str:
        self._record("get_ecs_cluster_arn", name)
        return self.cluster_arn


@pytest.fixture
def fake_aws() -> FakeAWSClient:
    """Pytest fixture: fresh FakeAWSClient per test."""
    return FakeAWSClient()


# ---------------------------------------------------------------------------
# Recording OpenTofu runners (Phase 4).
# ---------------------------------------------------------------------------


@dataclass
class RecordingTofuRunner:
    """Recording callable for ``tofu_init`` / ``tofu_apply``.

    Same shape as ``RecordingAnsibleRunner`` — returns ``exit_code`` on
    each call and stores args for assertion.
    """

    exit_code: int = 0
    calls: list[dict] = field(default_factory=list)
    name: str = "tofu"

    def __call__(self, workdir, **kwargs):
        self.calls.append({"workdir": workdir, **kwargs})
        return self.exit_code


@pytest.fixture
def fake_tofu_init() -> RecordingTofuRunner:
    return RecordingTofuRunner(name="tofu_init")


@pytest.fixture
def fake_tofu_apply() -> RecordingTofuRunner:
    return RecordingTofuRunner(name="tofu_apply")
