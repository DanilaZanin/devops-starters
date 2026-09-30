# Terraform replicas fail with "port is already allocated": local module starter on the Docker provider

Level: **lab** (native `terraform test` and validation in CI; `make up` applies for real on a local Docker).

Three small Terraform modules (`network`, `security-group`, `compute`) in the classic
"VPC + security group + instances" shape, implemented on the Docker provider so
they run on a laptop with no cloud account. **This is a teaching model of module
interfaces, not production infrastructure**: the value is the module structure,
input validation and tests, not the Docker resources behind them.

## Problem

A module that creates N copies of a container publishes the same host port for every
copy. The first container starts; the second fails at `terraform apply` with the Docker
daemon's `Bind for 0.0.0.0:8080 failed: port is already allocated`, halfway through an
apply that has already created other resources. Nothing at plan time warns you.

The `compute` module computes the published ports in one `locals` block and offsets the
host port by the replica index (8080, 8081, ...). Its tests assert the planned ports, so
the mistake shows up in `terraform test` in seconds, without a Docker daemon.

The offset only separates replicas of the same rule. With two replicas and rules on 8080
and 8081, replica 0 publishes 8080 and 8081 and replica 1 publishes 8081 and 8082, so 8081
is claimed twice. The module therefore checks the whole computed set and refuses to plan
when any (ip, protocol, host port) appears more than once, or a port exceeds 65535.
Space rules at least `replicas` apart.

## Quick start

```bash
make check-prereqs   # terraform >= 1.7
make test            # fmt, tflint (if installed), validate, terraform test, trap
```

`make test` runs `terraform fmt -check`, `tflint` when installed, `terraform init` and
`validate` in every module and the example, and `terraform test` in each (native tests
against a mocked docker provider: no daemon needed, the provider is still downloaded
by `init`). The last step builds a broken copy of `modules/compute` without the port
offset and requires its tests to fail on the distinct-ports assertion:

```
OK: without the offset, terraform test fails on 'replicas must publish distinct host ports'.
```

`make up` applies `examples/docker-sandbox` on your local Docker (two nginx containers on
127.0.0.1:8080 and :8081) and requires each URL to answer HTTP 200 (15 tries, 2 s apart, then
non-zero exit); `make down` destroys them; `make reset` also
removes `.terraform` directories and local state.

| | Status |
|---|---|
| macOS arm64 + colima (4 CPU / 8 GB) | verified 2026-09-29: `make test` green (also from a copied directory); `make up` and `make down` applied and destroyed 5 resources on colima. Terraform 1.16.4, kreuzwerker/docker 4.6.0, tflint 0.64.0 (via its docker image, clean) |
| ubuntu-24.04 GitHub runner | CI only, not measured here; see `.github/workflows/terraform-docker-modules.yml` |
| First-run time | `make test` about 18 s with a cold provider cache (about 11 s from a copied directory); `make up` about 8 s with the image already local |
| RAM | `make test` starts no containers; `make up` runs two nginx containers (a few MB each, not measured separately) |

## Traps this avoids

1. **Replicas collide on the host port** (reproduced in tests). One `locals` block feeds
   both the containers and the `published_ports` output, with the replica index added
   to the external port, and a precondition rejects rules whose offset ranges overlap
   (8080 and 8081 with two replicas) or leave the port range.
2. **Silently ignored inputs.** Docker cannot filter published ports by source
   address, so the security-group module rejects any `cidr` other than `0.0.0.0/0`
   instead of accepting a value that does nothing.
3. **Ports exposed on every interface.** Published ports bind to `127.0.0.1` unless you
   pass `bind_ip`.
4. **Port opened is not the port the process binds.** The example uses
   `nginxinc/nginx-unprivileged`, which listens on 8080, matching the rule. The image
   also runs as non-root and has a health check in the example.
5. **Typos found at apply time.** Ports outside 1..65535, unknown protocols, invalid
   subnets and `replicas < 1` fail at plan time (each has a test).

## What the test proves / does NOT prove

Proves:

- With a mocked provider, the compute module plans distinct host ports and indexed
  names for N replicas, keeps the plain name and port for one, and defaults to
  loopback. A copy without the offset fails those assertions.
- Rules on adjacent ports (8080 and 8081, two replicas) are rejected at plan time, rules
  spaced by the replica count are accepted, tcp and udp on one number do not collide, and
  ports above 65535 are rejected.
- `make check-urls` (used by `make up`) fails on a closed port and passes on an answering
  server (`make urls-guard`, part of `make test`).
- The validations in all three modules reject bad input (`expect_failures`).
- The example wires the modules into two replicas on `127.0.0.1:8080` and `:8081`.
- Code is formatted and validates against the real provider schema.

Does NOT prove:

- That `apply` works in CI. `terraform test` runs `plan` against a mocked provider; nothing
  talks to a Docker daemon there. `make up` is the manual check (run once by hand on colima).
- The exact Docker error message from the Problem section is not reproduced; the test
  checks the planned ports that would cause it.
- That the modules map cleanly onto a real cloud. The interfaces are shaped like AWS
  security-group rules and ASG capacity, but nothing here is tested against AWS.
- Behavior of provider versions other than the one in the example's lock file (4.6.0).

## Local demo vs production

- The Docker provider has no real VPC, security group or load balancer. `network` is a
  bridge network, `security-group` only normalizes and validates rules
  (a `terraform_data` resource), and `compute` publishes ports on the host.
- Real modules need remote state, provider version and lock file management for every
  root module, tagging, IAM, and a review of every default.
- Pin `image` to an exact tag or digest; the example uses the exact tag `1.30.2-alpine`.
- Publishing on `0.0.0.0` (`bind_ip`) exposes the container to your network.

## Copy it into your project

Copy the directories under `modules/` you need (each has its own `versions.tf`, tests,
and descriptions in `variables.tf` and `outputs.tf`), and keep
`traps/port-offset.sh` with `compute` if you want the regression test. The example
shows how the modules connect. The module has no references outside its directory.

## Module reference

### `modules/network`

| Input | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Network is called `<name>-net` |
| `subnet` | string | `10.20.0.0/24` | IPv4 CIDR, validated |
| `labels` | map(string) | `{}` | Docker labels |

Outputs: `network_id`, `network_name`

### `modules/security-group`

| Input | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Name of the group |
| `ingress_rules` | list(object) | `[]` | `{ description, port, protocol = "tcp", cidr = "0.0.0.0/0" }` |

Validated: port in 1..65535, protocol `tcp` or `udp`, `cidr` only `0.0.0.0/0`.
Outputs: `name`, `rules` (normalized `{ description, internal, external, protocol }`).

### `modules/compute`

| Input | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Base name, `-<index>` appended when `replicas > 1` |
| `image` | string | required | Docker image; use one that runs as non-root |
| `replicas` | number | `1` | Number of containers, at least 1 |
| `network_name` | string | required | From the network module |
| `security_group_rules` | list(object) | `[]` | From the security-group module |
| `bind_ip` | string | `127.0.0.1` | Host address for published ports |
| `env` | map(string) | `{}` | Environment variables |
| `command` | list(string) | `null` | Override the image command |
| `healthcheck` | object | `null` | `{ test, interval, timeout, retries }` |

Outputs: `container_names`, `container_ips`, `published_ports`

## Porting to a real cloud

The module inputs and outputs mirror a cloud shape, so porting means rewriting the
resources inside each module:

- `modules/network` to `aws_vpc` plus `aws_subnet`
- `modules/security-group` to `aws_security_group` plus rules (`cidr` becomes meaningful)
- `modules/compute` to `aws_instance` or an autoscaling group (the port offset goes
  away; a load balancer replaces host ports)

`examples/docker-sandbox` would change only where it depends on host ports.

## Layout

```
modules/network/          docker_network, validation, tests/
modules/security-group/   rule validation and normalization, tests/
modules/compute/          docker_container replicas, port offset, tests/
examples/docker-sandbox/  the three wired together, tests/, committed lock file
traps/port-offset.sh      broken (no offset) copy of compute must fail its tests
```
