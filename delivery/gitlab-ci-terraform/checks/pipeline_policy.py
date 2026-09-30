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


class UnsupportedRule(ValueError):
    """A rules:if expression this checker cannot evaluate. The policy fails closed."""


_TOKEN = re.compile(r'\s*(?:(\$[A-Za-z_][A-Za-z0-9_]*)|"([^"]*)"|\'([^\']*)\'|(==|!=|&&|\|\||\(|\)))')


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    while pos < len(expr):
        if not expr[pos:].strip():
            break
        m = _TOKEN.match(expr, pos)
        if not m:
            raise UnsupportedRule(f"cannot evaluate `{expr}` (unsupported syntax near `{expr[pos:].strip()[:20]}`)")
        var, dq, sq, op = m.groups()
        if var:
            tokens.append(("var", var[1:]))
        elif dq is not None or sq is not None:
            tokens.append(("str", dq if dq is not None else sq))
        else:
            tokens.append(("op", op))
        pos = m.end()
    return tokens


def eval_if(expr: str, env: dict[str, str]) -> bool:
    """Evaluate a GitLab `rules:if` expression against variables `env`.

    Supports $VAR, "literal", ==, !=, &&, || and parentheses. A bare `$VAR` is
    true when the variable is set and not empty; an unset variable compares as
    an empty string. Anything else (regex matches, ...) raises UnsupportedRule.
    """
    tokens = _tokenize(expr)
    pos = 0

    def peek() -> tuple[str, str] | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> tuple[str, str]:
        nonlocal pos
        tok = peek()
        if tok is None:
            raise UnsupportedRule(f"cannot evaluate `{expr}` (unexpected end)")
        pos += 1
        return tok

    def value(tok: tuple[str, str]) -> str:
        return env.get(tok[1], "") if tok[0] == "var" else tok[1]

    def primary() -> bool:
        tok = take()
        if tok == ("op", "("):
            result = disjunction()
            if take() != ("op", ")"):
                raise UnsupportedRule(f"cannot evaluate `{expr}` (missing `)`)")
            return result
        if tok[0] == "op":
            raise UnsupportedRule(f"cannot evaluate `{expr}` (unexpected `{tok[1]}`)")
        nxt = peek()
        if nxt in {("op", "=="), ("op", "!=")}:
            take()
            rhs = take()
            if rhs[0] == "op":
                raise UnsupportedRule(f"cannot evaluate `{expr}`")
            same = value(tok) == value(rhs)
            return same if nxt[1] == "==" else not same
        return value(tok) != ""

    def conjunction() -> bool:
        result = primary()
        while peek() == ("op", "&&"):
            take()
            result = primary() and result
        return result

    def disjunction() -> bool:
        result = conjunction()
        while peek() == ("op", "||"):
            take()
            result = conjunction() or result
        return result

    result = disjunction()
    if pos != len(tokens):
        raise UnsupportedRule(f"cannot evaluate `{expr}` (trailing tokens)")
    return result


# The pipelines that matter, described by the predefined variables GitLab sets.
CONTEXTS: dict[str, dict[str, str]] = {
    "merge request": {
        "CI_PIPELINE_SOURCE": "merge_request_event",
        "CI_MERGE_REQUEST_IID": "7",
        "CI_DEFAULT_BRANCH": "main",
    },
    "default branch": {
        "CI_PIPELINE_SOURCE": "push",
        "CI_COMMIT_BRANCH": "main",
        "CI_DEFAULT_BRANCH": "main",
    },
    "feature branch with an open MR": {
        "CI_PIPELINE_SOURCE": "push",
        "CI_COMMIT_BRANCH": "feature",
        "CI_OPEN_MERGE_REQUESTS": "group/project!7",
        "CI_DEFAULT_BRANCH": "main",
    },
    "feature branch without an MR": {
        "CI_PIPELINE_SOURCE": "push",
        "CI_COMMIT_BRANCH": "feature",
        "CI_DEFAULT_BRANCH": "main",
    },
}


def first_match(rules: list[dict], env: dict[str, str]) -> dict | None:
    """The first rule whose `if` holds (a rule without `if` always matches), like GitLab."""
    for rule in rules:
        if "if" not in rule or eval_if(str(rule["if"]), env):
            return rule
    return None


def pipeline_runs(doc: dict, env: dict[str, str]) -> bool:
    rules = doc.get("workflow", {}).get("rules")
    if not rules:
        return True
    rule = first_match(rules, env)
    return rule is not None and rule.get("when") != "never"


def outcome(doc: dict, job: dict, env: dict[str, str]) -> tuple[str, bool] | None:
    """(when, allow_failure) of the job in this pipeline, or None when it is not created."""
    if not pipeline_runs(doc, env):
        return None
    rules = job.get("rules")
    if not rules:
        when = job.get("when", "on_success")
        # Job-level `when: manual` is optional (allow_failure defaults to true).
        return when, bool(job.get("allow_failure", when == "manual"))
    rule = first_match(rules, env)
    if rule is None:
        return None
    when = rule.get("when", job.get("when", "on_success"))
    if when == "never":
        return None
    # allow_failure: rule value, else job value, else the default: true for a job-level
    # `when: manual` (rule without its own `when`), false for `manual` set inside rules.
    default = when == "manual" and "when" not in rule
    return when, bool(rule.get("allow_failure", job.get("allow_failure", default)))


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

    # 2-6. Rules are evaluated per pipeline type with first-match semantics,
    # not searched for substrings.
    #   plan:*   run automatically in merge requests and on the default branch
    #   apply:*  exist only on the default branch, need the matching plan and a
    #            resource_group; production is a manual, blocking gate
    for name, job in visible.items():
        if not name.startswith(("plan:", "apply:")):
            continue
        kind, env_name = name.split(":", 1)
        try:
            results = {ctx: outcome(doc, job, variables) for ctx, variables in CONTEXTS.items()}
        except UnsupportedRule as exc:
            add("RULE_UNSUPPORTED", f"{name}: {exc}")
            continue
        if kind == "plan":
            for ctx in ("merge request", "default branch"):
                if results[ctx] is None or results[ctx][0] != "on_success":
                    add("PLAN_RULES", f"{name}: must run automatically in a {ctx} pipeline")
            continue
        for ctx, result in results.items():
            if ctx != "default branch" and result is not None:
                add("APPLY_MAIN_ONLY", f"{name}: would be created in a {ctx} pipeline")
        if results["default branch"] is None:
            add("APPLY_MAIN_ONLY", f"{name}: is never created on the default branch")
        if f"plan:{env_name}" not in needs_names(job):
            add("APPLY_NEEDS_PLAN", f"{name}: must list plan:{env_name} in needs")
        if not job.get("resource_group"):
            add("RESOURCE_GROUP", f"{name}: missing resource_group (concurrent applies)")
        if env_name == "production" and results["default branch"] is not None:
            when, allow_failure = results["default branch"]
            if when != "manual" or allow_failure:
                add(
                    "PROD_GATE",
                    f"{name}: on the default branch it resolves to when={when}, "
                    f"allow_failure={str(allow_failure).lower()}; needs manual and false",
                )

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
