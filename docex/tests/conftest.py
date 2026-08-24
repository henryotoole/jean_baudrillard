"""Pytest configuration: make ``src/`` importable for tests.

Phase 2 additions: a ``FakeDockerClient`` fixture that records every
call made against it, so the orchestrate-layer unit tests can assert
the exact sequence of docker invocations without spawning subprocesses.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
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
    - ``manifest_inspect_results`` maps full image refs to bool; default
      True (image present) when a ref isn't in the dict.
    """

    available: bool = True
    ps_services: list[str] = field(default_factory=list)
    # Scripted return for ``compose_ps_status``: service → coarse state.
    # Default empty so existing tests (which never inspect it) are
    # unaffected and the partial-bring-up diagnostic stays silent.
    ps_status: dict[str, str] = field(default_factory=dict)
    exit_codes: dict[tuple, int] = field(default_factory=dict)
    default_exit: int = 0
    manifest_inspect_results: dict[str, bool] = field(default_factory=dict)
    # Mod 036: scripted return for ``any_env_compose_up``. Maps project
    # name -> bool; default False (no env stacks up) when unset.
    any_env_compose_up_results: dict[str, bool] = field(default_factory=dict)
    # Mod 042: scripted return for ``network_exists``. Maps network
    # name -> bool. Default True (network present) when unset, so most
    # existing tests don't need to pre-script the ``docex-ingress``
    # bridge to satisfy the new ``envinfra up`` / ``projinfra up``
    # preinfra gate.
    network_exists_results: dict[str, bool] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    # -- protocol ------------------------------------------------------

    def is_available(self) -> bool:
        self.calls.append(("is_available",))
        return self.available

    def compose_up(self, compose_file: Path, *, build: bool = True, detach: bool = True,
                   env_file: Path | None = None,
                   project_dir: Path | None = None,
                   project_name: str | None = None) -> int:
        key = ("compose_up", str(compose_file), build, detach)
        self.calls.append(key)
        if project_dir is not None:
            self.calls.append(("compose_up_project_dir", str(project_dir)))
        if project_name is not None:
            self.calls.append(("compose_up_project_name", project_name))
        return self.exit_codes.get(key, self._fallback("compose_up"))

    def compose_down(self, compose_file: Path, *, preserve_volumes: bool = True,
                     env_file: Path | None = None,
                     project_dir: Path | None = None,
                     project_name: str | None = None) -> int:
        key = ("compose_down", str(compose_file), preserve_volumes)
        self.calls.append(key)
        if project_dir is not None:
            self.calls.append(("compose_down_project_dir", str(project_dir)))
        if project_name is not None:
            self.calls.append(("compose_down_project_name", project_name))
        return self.exit_codes.get(key, self._fallback("compose_down"))

    def compose_run_one_off(
        self,
        compose_file: Path,
        service: str,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        build: bool = False,
        env_file: Path | None = None,
        project_dir: Path | None = None,
        project_name: str | None = None,
    ) -> int:
        key = ("compose_run_one_off", str(compose_file), service, tuple(command))
        self.calls.append(key)
        if project_dir is not None:
            self.calls.append(("compose_run_one_off_project_dir", str(project_dir)))
        if project_name is not None:
            self.calls.append(("compose_run_one_off_project_name", project_name))
        # Mod 103: `--build` is recorded as a SIDE-call, the same way
        # project_dir / project_name are, so the primary tuple key stays
        # exactly as it was — many tests assert on it verbatim.
        if build:
            self.calls.append(
                ("compose_run_one_off_build", service, tuple(command))
            )
        # Mod 099: same finer scripting shape ``compose_exec`` has, now that
        # the per-codebase operations run through here — a test needs to be
        # able to fail one service's ``./migrate.sh`` without failing all
        # one-off runs. Key: ("exit", "compose_run_one_off", svc, cmd_tuple).
        return self.exit_codes.get(
            key, self._fallback("compose_run_one_off", service, tuple(command))
        )

    def compose_exec(self, compose_file: Path, service: str, command: list[str],
                     *, env_file: Path | None = None,
                     project_dir: Path | None = None,
                     project_name: str | None = None) -> int:
        key = ("compose_exec", str(compose_file), service, tuple(command))
        self.calls.append(key)
        if project_dir is not None:
            self.calls.append(("compose_exec_project_dir", str(project_dir)))
        if project_name is not None:
            self.calls.append(("compose_exec_project_name", project_name))
        # Allow scripting failure for ("compose_exec", svc, cmd_tuple).
        return self.exit_codes.get(key, self._fallback("compose_exec", service, tuple(command)))

    def compose_ps(self, compose_file: Path, *,
                   env_file: Path | None = None,
                   project_dir: Path | None = None,
                   project_name: str | None = None) -> list[str]:
        self.calls.append(("compose_ps", str(compose_file)))
        if project_name is not None:
            self.calls.append(("compose_ps_project_name", project_name))
        return list(self.ps_services)

    def compose_ps_status(self, compose_file: Path, *,
                          env_file: Path | None = None,
                          project_dir: Path | None = None,
                          project_name: str | None = None) -> dict[str, str]:
        self.calls.append(("compose_ps_status", str(compose_file)))
        if project_name is not None:
            self.calls.append(("compose_ps_status_project_name", project_name))
        return dict(self.ps_status)

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

    def manifest_inspect(self, ref: str) -> bool:
        self.calls.append(("manifest_inspect", ref))
        return self.manifest_inspect_results.get(ref, True)

    # ------- Mod 036: env-tier still-up detection for projinfra ------

    def any_env_compose_up(self, project_name: str) -> bool:
        self.calls.append(("any_env_compose_up", project_name))
        return self.any_env_compose_up_results.get(project_name, False)

    # ------- Mod 042: preinfra ``network_exists`` probe ---------------

    def network_exists(self, name: str) -> bool:
        self.calls.append(("network_exists", name))
        return self.network_exists_results.get(name, True)

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
    # When non-empty, ``is_clean_excluding`` consults these paths instead of
    # the coarse ``clean`` flag. Lets a test simulate "only infra/output/ is
    # dirty" without breaking other tests that just toggle ``clean``.
    dirty_paths: set[str] = field(default_factory=set)
    branch: str = "feature/x"
    head: str = "abc1234"
    tags: list[str] = field(default_factory=list)
    tag_exists_map: dict[str, bool] = field(default_factory=dict)
    merge_bases: dict[tuple, str] = field(default_factory=dict)
    # Mod 105: scripted content for ``show``. Maps ``(ref, path)`` to the
    # file's content, or to None to model "git show failed" (bad ref,
    # path absent at that ref). A key that is absent entirely falls back
    # to ``default_file_content``.
    file_at_ref: dict[tuple, str | None] = field(default_factory=dict)
    # WHY a permissive default: the fake already models "an established
    # repo" (see ``refs``), and the only production caller reads
    # ``cicl_version`` out of a tag during rollback pre-flight. Defaulting
    # to a compilable stub keeps every rollback test asserting its own
    # subject instead of acquiring boilerplate git-content setup.
    # Boundary tests override per key.
    default_file_content: str | None = 'cicl_version: "3"\n'
    # Refs that ``ref_exists`` should return True for. Tests scripting an
    # empty remote set this to ``set()`` (or omit ``origin/main``); the
    # default models an established repo with a populated main.
    refs: set[str] = field(default_factory=lambda: {"origin/main", "main", "HEAD"})
    # Whether an ``origin`` remote is configured. Default True so existing
    # tests are unaffected; the no-remote merge path sets this False.
    has_origin: bool = True
    exit_codes: dict[tuple, int] = field(default_factory=dict)
    default_exit: int = 0
    calls: list[tuple] = field(default_factory=list)

    # -- reads --------------------------------------------------------

    def is_clean(self, cwd):
        self.calls.append(("is_clean", str(cwd)))
        return self.clean

    def is_clean_excluding(self, cwd, excludes):
        self.calls.append(("is_clean_excluding", str(cwd), tuple(excludes)))
        # When tests have explicitly populated ``dirty_paths``, evaluate
        # path-by-path. Otherwise fall back to the coarse ``clean`` flag
        # so existing tests keep working without modification.
        if self.dirty_paths:
            return all(
                any(p.startswith(ex) for ex in excludes)
                for p in self.dirty_paths
            )
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

    def show(self, cwd, ref, path):
        self.calls.append(("show", str(cwd), ref, path))
        key = (ref, path)
        # WHY ``in`` rather than ``.get(key, default)``: it lets a test map
        # a key explicitly to None to mean "unreadable" without that being
        # confused with "unscripted".
        if key in self.file_at_ref:
            return self.file_at_ref[key]
        return self.default_file_content

    def ref_exists(self, cwd, ref):
        self.calls.append(("ref_exists", str(cwd), ref))
        return ref in self.refs

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

    def ls_remote(self, cwd, *, remote="origin"):
        key = ("ls_remote", remote)
        self.calls.append(("ls_remote", str(cwd), remote))
        return self.exit_codes.get(key, self.default_exit)

    def remote_exists(self, cwd, remote="origin"):
        self.calls.append(("remote_exists", str(cwd), remote))
        return self.has_origin

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

    def worktree_prune(self, cwd):
        self.calls.append(("worktree_prune", str(cwd)))
        return self.exit_codes.get(("worktree_prune",), self.default_exit)

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
    cluster_exists: bool = True
    # Mod 071: env-service existence probe used by the first-release
    # detector and the projinfra-down env-live gate. Defaults True so the
    # steady-state / envs-live paths remain the default.
    cluster_has_services: bool = True
    # Mod 114 / 123: the reconcile reads durable post-apply state, so there is
    # no "before" to script any more — one mapping of endpoint name -> Cloud Map
    # CreateDate, and one of ECS service name -> PRIMARY deployment createdAt.
    # Defaults are the inert case: no endpoints registered, hence no reconcile.
    service_connect_endpoint_ages: dict[str, datetime] = field(default_factory=dict)
    ecs_deployment_times: dict[str, datetime] = field(default_factory=dict)
    ecs_services_stable: bool = True
    ecs_exit_codes: dict[str, int] = field(default_factory=dict)
    raise_on: dict[str, Exception] = field(default_factory=dict)
    # Mod 029: probe results for ``ecr_image_exists``. Maps
    # ``(repository, tag) -> bool``. Defaults to True (image present)
    # when a key isn't in the dict.
    ecr_image_exists_results: dict[tuple[str, str], bool] = field(default_factory=dict)
    # Mod 042: scripted results for the preinfra master VPC discovery
    # methods. ``find_vpc_by_tags_result`` returns the VPC ID (or None
    # for "not found"); ``find_subnet_ids_results`` is a mapping by
    # ``(vpc_id, tags_tuple, az)`` (where ``tags_tuple`` is the sorted
    # tuple of (k, v) pairs and ``az`` is the AZ string or None) to a
    # list of subnet IDs. Default empty list when key absent.
    find_vpc_by_tags_result: str | None = "vpc-fake0001"
    find_subnet_ids_results: dict[tuple, list[str]] = field(default_factory=dict)
    # Mod 052 (Gap F): teardown probe scripting. ``rds_protected_results``
    # maps a prefix -> list of protected RDS identifiers (default empty,
    # i.e. nothing protected). ``ecr_image_count_results`` maps a
    # repository name -> image count (default 0, i.e. empty repo).
    rds_protected_results: dict[str, list[str]] = field(default_factory=dict)
    ecr_image_count_results: dict[str, int] = field(default_factory=dict)
    # Mod 082: in-memory SSM Parameter Store. Maps path -> (value, type).
    # ``ssm_get_parameter`` reads it; ``ssm_put_parameter`` writes it and
    # honours ``overwrite`` (a put-if-absent against a present key raises,
    # modelling boto3's ParameterAlreadyExists) so ``ensure_tte_elastic``'s
    # read-before-mint guard is actually exercised.
    ssm_store: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Mod 128: stagetest's orchestrator read. All three default to EMPTY —
    # "nothing is deployed" — never to a healthy env. See the methods below.
    ecs_service_task_arns: dict[str, list[str]] = field(default_factory=dict)
    ecs_task_records: dict[str, dict[str, str]] = field(default_factory=dict)
    ecs_task_definition_images_results: dict[str, dict[str, str]] = field(
        default_factory=dict
    )
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

    def ssm_get_parameter(self, name: str) -> str | None:
        self._record("ssm_get_parameter", name)
        entry = self.ssm_store.get(name)
        return None if entry is None else entry[0]

    def ssm_put_parameter(
        self,
        name: str,
        value: str,
        *,
        overwrite: bool = True,
        param_type: str = "SecureString",
    ) -> None:
        self._record(
            "ssm_put_parameter", name, value,
            overwrite=overwrite, param_type=param_type,
        )
        if not overwrite and name in self.ssm_store:
            # Models boto3's ParameterAlreadyExists — a put-if-absent must
            # never clobber a live value.
            raise RuntimeError(f"ParameterAlreadyExists: {name!r}")
        self.ssm_store[name] = (value, param_type)

    def ssm_delete_parameters(self, path_prefix: str) -> None:
        self._record("ssm_delete_parameters", path_prefix)

    # -- S3 ------------------------------------------------------------

    def s3_bucket_exists(self, name: str) -> bool:
        self._record("s3_bucket_exists", name)
        return self.bucket_exists

    def s3_create_bucket(
        self, name: str, *, region: str, tags: dict[str, str] | None = None
    ) -> None:
        self._record("s3_create_bucket", name, region=region, tags=tags)
        # After create, subsequent existence checks should see it.
        self.bucket_exists = True

    def s3_enable_versioning(self, name: str) -> None:
        self._record("s3_enable_versioning", name)

    def s3_enable_encryption(self, name: str) -> None:
        self._record("s3_enable_encryption", name)

    def s3_block_public_access(self, name: str) -> None:
        self._record("s3_block_public_access", name)

    def s3_delete_bucket(self, name: str) -> None:
        self._record("s3_delete_bucket", name)
        self.bucket_exists = False

    # -- DynamoDB ------------------------------------------------------

    def ddb_table_exists(self, name: str) -> bool:
        self._record("ddb_table_exists", name)
        return self.table_exists

    def ddb_create_locking_table(
        self, name: str, *, tags: dict[str, str] | None = None
    ) -> None:
        self._record("ddb_create_locking_table", name, tags=tags)
        self.table_exists = True

    def ddb_delete_table(self, name: str) -> None:
        self._record("ddb_delete_table", name)
        self.table_exists = False

    # -- Mod 052 (Gap F): teardown probes ------------------------------

    def rds_protected_instances(self, prefix: str) -> list[str]:
        self._record("rds_protected_instances", prefix)
        return list(self.rds_protected_results.get(prefix, []))

    def ecr_repository_image_count(self, repository: str) -> int:
        self._record("ecr_repository_image_count", repository)
        return self.ecr_image_count_results.get(repository, 0)

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

    def ecr_image_exists(self, repository: str, tag: str) -> bool:
        self._record("ecr_image_exists", repository, tag)
        return self.ecr_image_exists_results.get((repository, tag), True)

    # -- Lookups -------------------------------------------------------

    def lookup_master_vpc(self) -> str:
        """Optional helper used by ``orchestrate.migrate._lookup_master_vpc``
        when present on the fake. Avoids drilling into the boto3 client.
        Mod 047 renamed from ``lookup_project_vpc`` (which assumed a
        per-project VPC pre-mod-041) to ``lookup_master_vpc`` (post-
        mod-041: shared master VPC across all projects)."""
        self._record("lookup_master_vpc")
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

    def ecs_cluster_exists(self, name: str) -> bool:
        self._record("ecs_cluster_exists", name)
        return self.cluster_exists

    def ecs_cluster_has_services(self, name: str) -> bool:
        self._record("ecs_cluster_has_services", name)
        return self.cluster_has_services

    # -- Mod 109 / 114 / 123: Service Connect consumer reconcile ------

    # NOTE: the fake deliberately does NOT filter the `aws-ecs-sc.client.`
    # prefix — that is the adapter's job, and the pipeline-level test must be
    # able to drive the pipeline against an unfiltered namespace.
    def service_connect_endpoints(
        self, namespace_name: str,
    ) -> dict[str, datetime]:
        self._record("service_connect_endpoints", namespace_name)
        return dict(self.service_connect_endpoint_ages)

    def ecs_primary_deployment_times(
        self, cluster: str, services: list[str],
    ) -> dict[str, datetime]:
        self._record(
            "ecs_primary_deployment_times",
            cluster=cluster, services=list(services),
        )
        # Only the requested services, and only those scripted — so a test can
        # exercise "absent from the mapping → fire" by simply omitting one.
        return {
            name: self.ecs_deployment_times[name]
            for name in services
            if name in self.ecs_deployment_times
        }

    # -- Mod 128: stagetest's orchestrator liveness/version read -------
    #
    # Every default here is EMPTY, i.e. "nothing is deployed", and every new
    # test must script its way out of that. Deliberate: a fake whose default is
    # a healthy env is the same defect mod 128 exists to close, one layer down.

    def ecs_list_service_task_arns(self, cluster: str, service: str) -> list[str]:
        self._record("ecs_list_service_task_arns", cluster=cluster, service=service)
        return list(self.ecs_service_task_arns.get(service, []))

    def ecs_describe_tasks(
        self, cluster: str, task_arns: list[str],
    ) -> list[dict[str, str]]:
        self._record(
            "ecs_describe_tasks", cluster=cluster, task_arns=list(task_arns),
        )
        # Requested ARNs with no scripted record are SILENTLY OMITTED — that is
        # how a test models the shrinking-task-set race (list an ARN, give it no
        # record), mirroring real DescribeTasks putting it under `failures`.
        return [
            dict(self.ecs_task_records[arn])
            for arn in task_arns
            if arn in self.ecs_task_records
        ]

    def ecs_task_definition_images(self, task_definition: str) -> dict[str, str]:
        self._record("ecs_task_definition_images", task_definition=task_definition)
        return dict(self.ecs_task_definition_images_results.get(task_definition, {}))

    def ecs_force_new_deployment(self, cluster: str, service: str) -> None:
        self._record("ecs_force_new_deployment", cluster=cluster, service=service)

    def ecs_wait_services_stable(
        self, cluster: str, services: list[str], *, timeout_s: int,
    ) -> bool:
        self._record(
            "ecs_wait_services_stable",
            cluster=cluster, services=list(services), timeout_s=timeout_s,
        )
        return self.ecs_services_stable

    # -- Mod 042: preinfra master VPC discovery -----------------------

    def find_vpc_by_tags(self, tags: dict[str, str]) -> str | None:
        self._record("find_vpc_by_tags", tags)
        return self.find_vpc_by_tags_result

    def find_subnet_ids(
        self,
        *,
        vpc_id: str,
        tags: dict[str, str],
        availability_zone: str | None = None,
    ) -> list[str]:
        self._record(
            "find_subnet_ids",
            vpc_id=vpc_id, tags=tags, availability_zone=availability_zone,
        )
        key = (vpc_id, tuple(sorted(tags.items())), availability_zone)
        return list(self.find_subnet_ids_results.get(key, []))


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


@pytest.fixture
def fake_tofu_plan() -> RecordingTofuRunner:
    return RecordingTofuRunner(name="tofu_plan")


# ---------------------------------------------------------------------------
# Fake SSH client (mod 050).
# ---------------------------------------------------------------------------


@dataclass
class FakeSSHClient:
    """Recording, scriptable stand-in for ``SSHClient``.

    ``results`` maps a host to the exit code ``run`` should return for
    that host (e.g. ``{"stage.sample.example.com": 0,
    "sample.example.com": 1}``). Hosts not in the map fall back to
    ``default_exit`` (0). Every invocation is recorded in ``calls`` so
    tests can assert which hosts were (and weren't) probed.

    ``capture`` (mod 081) reads a remote file into docex. It returns
    ``(capture_rc, capture_out)`` — ``capture_out`` is the canned host
    ``tte.env`` string (default empty = an unprovisioned first-release
    store). Every capture is recorded in ``calls`` too.

    ``capture_results`` (mod 128) maps a *command substring* to the stdout that
    command should produce, so a test can script a different answer per
    container for ``stagetest``'s per-container ``docker inspect``. It is
    consulted first; ``capture_out`` remains the uniform fallback, so no
    existing caller changes. ``capture_rc`` still applies to every capture —
    a test that needs a per-command rc scripts the rc case on its own.
    """

    results: dict[str, int] = field(default_factory=dict)
    default_exit: int = 0
    capture_out: str = ""
    capture_rc: int = 0
    capture_results: dict[str, str] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    def run(self, host, key_path, command, *, user="deploy"):
        self.calls.append(("run", host, str(key_path), command, user))
        return self.results.get(host, self.default_exit)

    def capture(self, host, key_path, command, *, user="deploy"):
        self.calls.append(("capture", host, str(key_path), command, user))
        for needle, out in self.capture_results.items():
            if needle in command:
                return (self.capture_rc, out)
        return (self.capture_rc, self.capture_out)


@pytest.fixture
def fake_ssh() -> FakeSSHClient:
    """Pytest fixture: fresh FakeSSHClient per test."""
    return FakeSSHClient()


# ---------------------------------------------------------------------------
# Fake DNS resolver (mod 054).
# ---------------------------------------------------------------------------


@dataclass
class FakeDnsResolver:
    """Recording, scriptable stand-in for ``DnsResolver``.

    - ``results`` maps a hostname to the verdict ``resolves`` returns for
      it. Hosts not in the map fall back to ``default`` (True), so a test
      only has to script the hosts it cares about.
    - ``raise_on`` is a set of hostnames for which ``resolves`` raises —
      models a transient/network resolver error (distinct from a
      confirmed NXDOMAIN, which is ``results[host] = False``).
    - ``asked`` records every hostname queried, in order, so tests can
      assert *which* hosts were probed (e.g. only ``dev`` ones).
    """

    results: dict[str, bool] = field(default_factory=dict)
    default: bool = True
    raise_on: set[str] = field(default_factory=set)
    asked: list[str] = field(default_factory=list)

    def resolves(self, hostname: str) -> bool:
        self.asked.append(hostname)
        if hostname in self.raise_on:
            raise RuntimeError(f"resolver blew up for {hostname}")
        return self.results.get(hostname, self.default)


@pytest.fixture
def fake_dns() -> FakeDnsResolver:
    """Pytest fixture: fresh FakeDnsResolver per test."""
    return FakeDnsResolver()


# ---------------------------------------------------------------------------
# Fake registry client (mod 133).
# ---------------------------------------------------------------------------


def _passing_manifest_delete_result():
    """The observation that proves the capability is present: the delete
    gate was passed and the (nonexistent) manifest lookup was reached."""
    # Lazy: `src/` only joins sys.path above, so docex imports stay
    # function-local throughout this module.
    from docex.registry.client import ManifestDeleteResult

    return ManifestDeleteResult(
        status=404, error_code="MANIFEST_UNKNOWN",
        detail="404 from fake registry",
    )


@dataclass
class FakeRegistryClient:
    """Recording, scriptable stand-in for ``RegistryClient``.

    - ``result`` is what ``delete_manifest`` returns by default. It
      defaults to the *passing* observation (``404 MANIFEST_UNKNOWN``) so
      the existing development-side tests only need the fixture threaded
      through, not a scripted result.
    - ``results`` maps ``(host, repository)`` to a per-target result and is
      consulted before ``result``.
    - ``calls`` records every invocation so a test can assert the probe
      targeted the reserved repository and the zero digest — and, on the
      elastic / no-registry paths, that it was never called at all.
    """

    result: ManifestDeleteResult = field(
        default_factory=_passing_manifest_delete_result
    )
    results: dict[tuple[str, str], ManifestDeleteResult] = field(
        default_factory=dict
    )
    calls: list[tuple] = field(default_factory=list)

    def delete_manifest(self, host, repository, reference):
        self.calls.append(("delete_manifest", host, repository, reference))
        return self.results.get((host, repository), self.result)


@pytest.fixture
def fake_registry() -> FakeRegistryClient:
    """Pytest fixture: fresh FakeRegistryClient per test."""
    return FakeRegistryClient()
