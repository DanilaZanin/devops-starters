"""Trap tests: the shipped pipeline passes the policy, and each known mistake fails it.

A "broken" pipeline is the shipped one with exactly one mistake introduced by
a mutation below. The test fails if a broken variant is NOT reported, so the
policy cannot silently stop protecting anything.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pipeline_policy
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_FILE = ROOT / ".gitlab-ci.yml"


def _load() -> dict:
    return yaml.safe_load(CI_FILE.read_text(encoding="utf-8"))


def _codes(root: Path, ci_doc: dict | None = None) -> set[str]:
    ci_file = None
    if ci_doc is not None:
        ci_file = root / "mutated-ci.yml"
        ci_file.write_text(yaml.safe_dump(ci_doc, sort_keys=False), encoding="utf-8")
    return {code for code, _ in pipeline_policy.check(root, ci_file)}


# ---- mutations of the pipeline file -----------------------------------------


def drop_entrypoint(doc: dict) -> None:
    # THE TRAP: the terraform image runs `terraform <script>` instead of a shell.
    del doc[".terraform"]["image"]["entrypoint"]


def apply_in_merge_requests(doc: dict) -> None:
    doc["apply:staging"]["rules"].append({"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'})


def plan_only_on_default_branch(doc: dict) -> None:
    doc[".plan"]["rules"] = [{"if": "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH"}]


def production_applies_automatically(doc: dict) -> None:
    del doc["apply:production"]["rules"][0]["when"]


def production_can_fail(doc: dict) -> None:
    del doc["apply:production"]["allow_failure"]


def apply_without_resource_group(doc: dict) -> None:
    del doc["apply:staging"]["resource_group"]


def apply_without_plan(doc: dict) -> None:
    doc["apply:staging"]["needs"] = []


def build_without_push(doc: dict) -> None:
    doc["build"]["script"] = [line for line in doc["build"]["script"] if "docker push" not in line]


def init_without_readonly_lock(doc: dict) -> None:
    doc[".terraform"]["before_script"] = ["cd \"$TF_ROOT\"", "terraform init"]


def local_state(doc: dict) -> None:
    for key in [k for k in doc[".terraform"]["variables"] if k.startswith("TF_HTTP_ADDRESS")]:
        del doc[".terraform"]["variables"][key]


PIPELINE_MUTATIONS = [
    (drop_entrypoint, "TF_ENTRYPOINT"),
    (apply_in_merge_requests, "APPLY_MAIN_ONLY"),
    (plan_only_on_default_branch, "PLAN_RULES"),
    (production_applies_automatically, "PROD_GATE"),
    (production_can_fail, "PROD_GATE"),
    (apply_without_resource_group, "RESOURCE_GROUP"),
    (apply_without_plan, "APPLY_NEEDS_PLAN"),
    (build_without_push, "REGISTRY_PUSH"),
    (init_without_readonly_lock, "LOCKFILE"),
    (local_state, "STATE_BACKEND"),
]


# ---- mutations of other files -----------------------------------------------


def remove_backend(root: Path) -> None:
    (root / "terraform" / "backend.tf").unlink()


def ignore_lock_file(root: Path) -> None:
    with (root / ".gitignore").open("a", encoding="utf-8") as fh:
        fh.write("\n.terraform.lock.hcl\n")


def delete_lock_file(root: Path) -> None:
    (root / "terraform" / ".terraform.lock.hcl").unlink()


def run_as_root(root: Path) -> None:
    dockerfile = root / "app" / "Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8").replace("USER 10001", "USER root"), encoding="utf-8"
    )


def no_cmd(root: Path) -> None:
    dockerfile = root / "app" / "Dockerfile"
    lines = [ln for ln in dockerfile.read_text(encoding="utf-8").splitlines() if not ln.startswith("CMD")]
    dockerfile.write_text("\n".join(lines) + "\n", encoding="utf-8")


FILE_MUTATIONS = [
    (remove_backend, "STATE_BACKEND"),
    (ignore_lock_file, "LOCKFILE"),
    (delete_lock_file, "LOCKFILE"),
    (run_as_root, "DOCKERFILE"),
    (no_cmd, "DOCKERFILE"),
]


@pytest.fixture
def module_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "module"
    shutil.copytree(
        ROOT,
        dest,
        ignore=shutil.ignore_patterns(".venv", ".terraform", "__pycache__", ".pytest_cache", ".ruff_cache"),
    )
    return dest


def test_shipped_pipeline_passes_the_policy():
    assert pipeline_policy.check(ROOT) == []


@pytest.mark.parametrize(("mutate", "expected"), PIPELINE_MUTATIONS, ids=lambda v: getattr(v, "__name__", v))
def test_broken_pipeline_is_caught(mutate, expected, module_copy):
    doc = _load()
    mutate(doc)
    assert expected in _codes(module_copy, doc), f"{mutate.__name__} was not reported as {expected}"


@pytest.mark.parametrize(("mutate", "expected"), FILE_MUTATIONS, ids=lambda v: getattr(v, "__name__", v))
def test_broken_files_are_caught(mutate, expected, module_copy):
    mutate(module_copy)
    assert expected in _codes(module_copy), f"{mutate.__name__} was not reported as {expected}"


def test_extends_is_resolved_like_gitlab():
    """The entrypoint lives in a hidden job that jobs inherit; the check must see it."""
    _, raw = pipeline_policy.load_jobs(CI_FILE)
    resolved = pipeline_policy.resolve("plan:production", raw)
    assert resolved["image"]["entrypoint"] == [""]
    assert resolved["variables"]["TF_STATE_NAME"] == "production"
