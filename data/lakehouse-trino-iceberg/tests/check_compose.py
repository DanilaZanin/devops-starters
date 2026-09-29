#!/usr/bin/env python3
"""Static checks on the rendered compose config and the Dockerfiles. No containers.

Rules: every image has an explicit, non-`latest` tag; every published port is bound to
127.0.0.1. The rules are first run against a deliberately bad config (the shape most
copy-pasted compose files have) which must be flagged, then against the real one,
which must be clean. Stdlib only.
"""
import json
import pathlib
import re
import subprocess
import sys

MODULE = pathlib.Path(__file__).resolve().parent.parent

BROKEN_SAMPLE = {
    "services": {
        "storage": {"image": "example/s3:latest", "ports": [{"target": 9000, "published": "9000", "protocol": "tcp"}]},
        "app": {"image": "example/app", "ports": [{"target": 8080, "published": "8080", "host_ip": "0.0.0.0"}]},
    }
}


def image_problem(image: str) -> str | None:
    name = image.rsplit("/", 1)[-1]
    if "@sha256:" in image:
        return None
    if ":" not in name:
        return "no tag (defaults to latest)"
    if name.endswith(":latest"):
        return "uses :latest"
    return None


def config_violations(config: dict) -> list[str]:
    found = []
    for name, service in config.get("services", {}).items():
        image = service.get("image")
        if image and "build" not in service and (problem := image_problem(image)):
            found.append(f"{name}: image {image} {problem}")
        for port in service.get("ports", []):
            if port.get("host_ip") not in ("127.0.0.1", "::1"):
                found.append(f"{name}: port {port.get('published')}->{port.get('target')} is not bound to 127.0.0.1")
    return found


def dockerfile_violations(path: pathlib.Path) -> list[str]:
    found = []
    stages = set()
    for line in path.read_text().splitlines():
        match = re.match(r"\s*FROM\s+(?:--\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", line, re.IGNORECASE)
        if not match:
            continue
        image, stage = match.groups()
        if image not in stages and image != "scratch" and (problem := image_problem(image)):
            found.append(f"{path.relative_to(MODULE)}: FROM {image} {problem}")
        if stage:
            stages.add(stage)
    return found


def main() -> int:
    if not config_violations(BROKEN_SAMPLE):
        print("self-test failed: the deliberately bad config was not flagged")
        return 1
    print("self-test ok: the bad sample config is flagged")

    rendered = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=MODULE, capture_output=True, text=True, check=False,
    )
    if rendered.returncode != 0:
        print(rendered.stderr)
        return 1
    problems = config_violations(json.loads(rendered.stdout))
    for dockerfile in sorted(MODULE.rglob("Dockerfile")):
        problems += dockerfile_violations(dockerfile)

    for problem in problems:
        print(f"violation: {problem}")
    print("compose and Dockerfile checks:", "FAILED" if problems else "ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
