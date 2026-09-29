"""Static policy checks for this module's GitLab pipeline.

GitLab itself is not needed: the pipeline file is parsed (with `extends`
resolved the way GitLab merges it) and checked against the rules that protect
against the mistakes this module exists to prevent. Each violation has a
stable code so tests can assert that a specific mistake is caught.

    python3 checks/pipeline_policy.py [--root DIR] [--ci FILE]

Exit status 1 when any violation is found.
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path

import yaml

RESERVED_KEYS = {"stages", "variables", "workflow", "default", "include", "image", "services"}
SELF_ENTRYPOINT_IMAGES = re.compile(r"(^|/)(hashicorp/terraform|aquasec/trivy)(:|@|$)")


def deep_merge(base: dict, override: dict) -> dict:
    """GitLab-style merge for `extends`: hashes merge recursively, everything else is replaced."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_jobs(ci_file: Path) -> tuple[dict, dict]:
    """Return (raw top-level document, {job name: raw job})."""
    doc = yaml.safe_load(ci_file.read_text(encoding="utf-8")) or {}
    jobs = {k: v for k, v in doc.items() if k not in RESERVED_KEYS and isinstance(v, dict)}
    return doc, jobs


def resolve(name: str, jobs: dict, seen: tuple[str, ...] = ()) -> dict:
    if name in seen:
        raise ValueError(f"extends cycle: {' -> '.join(seen + (name,))}")
    raw = jobs[name]
    parents = raw.get("extends", [])
    if isinstance(parents, str):
        parents = [parents]
    merged: dict = {}
    for parent in parents:
        merged = deep_merge(merged, resolve(parent, jobs, seen + (name,)))
    return deep_merge(merged, {k: v for k, v in raw.items() if k != "extends"})


def image_parts(job: dict) -> tuple[str | None, object]:
    image = job.get("image")
    if isinstance(image, str):
        return image, None
    if isinstance(image, dict):
        return image.get("name"), image.get("entrypoint")
    return None, None


def rule_ifs(job: dict) -> list[str]:
    return [str(r.get("if", "")) for r in job.get("rules", []) if r.get("when") != "never"]


def needs_names(job: dict) -> list[str]:
    names = []
    for need in job.get("needs", []):
        names.append(need if isinstance(need, str) else need.get("job", ""))
    return names


def script_text(job: dict) -> str:
    parts = []
    for key in ("before_script", "script", "after_script"):
        parts.extend(str(line) for line in job.get(key, []))
    return "\n".join(parts)


def dockerfile_instructions(text: str) -> list[tuple[str, str]]:
    """Split a Dockerfile into (INSTRUCTION, arguments), joining `\\` continuations.

    HEALTHCHECK ... CMD ... is one HEALTHCHECK instruction, not a CMD.
    """
    joined = re.sub(r"\\\s*\n", " ", text)
    result = []
    for line in joined.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, args = stripped.partition(" ")
        result.append((name.upper(), args.strip()))
    return result


def check(root: Path, ci_file: Path | None = None) -> list[tuple[str, str]]:
    ci_file = ci_file or root / ".gitlab-ci.yml"
    doc, raw_jobs = load_jobs(ci_file)
    jobs = {name: resolve(name, raw_jobs) for name in raw_jobs}
    visible = {n: j for n, j in jobs.items() if not n.startswith(".")}
    problems: list[tuple[str, str]] = []

    def add(code: str, message: str) -> None:
        problems.append((code, message))

    # 1. Images whose ENTRYPOINT is their own binary must reset it.
    for name, job in visible.items():
        image, entrypoint = image_parts(job)
        if image and SELF_ENTRYPOINT_IMAGES.search(image) and entrypoint != [""]:
            add("TF_ENTRYPOINT", f"{name}: image {image} needs `entrypoint: [\"\"]`")

    # 2. Plans run in merge requests and on the default branch.
    for name, job in visible.items():
        if name.startswith("plan:"):
            ifs = rule_ifs(job)
            if not any("merge_request_event" in c for c in ifs):
                add("PLAN_RULES", f"{name}: no rule for merge request pipelines")
            if not any("CI_DEFAULT_BRANCH" in c for c in ifs):
                add("PLAN_RULES", f"{name}: no rule for the default branch")

    # 3-6. Applies: default branch only, need the matching plan, serialized;
    # production is a manual, blocking gate.
    for name, job in visible.items():
        if not name.startswith("apply:"):
            continue
        env = name.split(":", 1)[1]
        ifs = rule_ifs(job)
        if not job.get("rules"):
            add("APPLY_MAIN_ONLY", f"{name}: no rules, so it would run wherever the workflow runs")
        if any("merge_request_event" in c for c in ifs) or (
            job.get("rules") and not all("CI_DEFAULT_BRANCH" in c for c in ifs)
        ):
            add("APPLY_MAIN_ONLY", f"{name}: rules allow apply outside the default branch")
        if f"plan:{env}" not in needs_names(job):
            add("APPLY_NEEDS_PLAN", f"{name}: must list plan:{env} in needs")
        if not job.get("resource_group"):
            add("RESOURCE_GROUP", f"{name}: missing resource_group (concurrent applies)")
        if env == "production":
            rules = job.get("rules", [])
            manual = any(r.get("when") == "manual" for r in rules) or (
                job.get("when") == "manual" and any("when" not in r for r in rules)
            )
            if not manual or job.get("allow_failure") is not False:
                add("PROD_GATE", f"{name}: must be `when: manual` with `allow_failure: false`")

    # 7. The image is pushed to the project registry.
    build = visible.get("build")
    build_script = script_text(build) if build else ""
    if "docker push" not in build_script or "CI_REGISTRY" not in build_script:
        add("REGISTRY_PUSH", "build: must docker login and docker push to $CI_REGISTRY")

    # 8. State is remote (GitLab-managed), not on the runner.
    backend = root / "terraform" / "backend.tf"
    if not backend.is_file() or not re.search(r'backend\s+"http"', backend.read_text(encoding="utf-8")):
        add("STATE_BACKEND", "terraform/backend.tf must declare backend \"http\"")
    plans = [j for n, j in visible.items() if n.startswith("plan:")]
    if not plans or not all("/terraform/state/" in str(j.get("variables", {}).get("TF_HTTP_ADDRESS", ""))
                            for j in plans):
        add("STATE_BACKEND", "plan jobs must set TF_HTTP_ADDRESS to the GitLab state API")

    # 9. Provider lock file is committed and used read-only.
    lock = root / "terraform" / ".terraform.lock.hcl"
    gitignore = root / ".gitignore"
    ignored = gitignore.is_file() and any(
        line.strip().endswith(".terraform.lock.hcl") and not line.lstrip().startswith("#")
        for line in gitignore.read_text(encoding="utf-8").splitlines()
    )
    if not lock.is_file() or ignored:
        add("LOCKFILE", "terraform/.terraform.lock.hcl must exist and must not be git-ignored")
    if not all("-lockfile=readonly" in script_text(j) for j in plans):
        add("LOCKFILE", "plan jobs must run `terraform init -lockfile=readonly`")

    # 10. The image runs a real process as a non-root user.
    dockerfile = root / "app" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8") if dockerfile.is_file() else ""
    instructions = dockerfile_instructions(text)
    users = [args.split()[0] for name, args in instructions if name == "USER" and args.split()]
    if not users or users[-1] in {"root", "0"}:
        add("DOCKERFILE", "app/Dockerfile must end with a non-root USER")
    if not any(name in {"CMD", "ENTRYPOINT"} for name, _ in instructions):
        add("DOCKERFILE", "app/Dockerfile has no CMD or ENTRYPOINT")

    # 11. No duplicate branch + MR pipelines.
    if not doc.get("workflow", {}).get("rules"):
        add("WORKFLOW_RULES", "workflow:rules is missing")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--ci", type=Path, default=None, help="pipeline file (default: ROOT/.gitlab-ci.yml)")
    args = parser.parse_args(argv)
    problems = check(args.root, args.ci)
    for code, message in problems:
        print(f"{code}: {message}")
    if problems:
        print(f"{len(problems)} violation(s)")
        return 1
    print("pipeline policy: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
