# terraform-modules-starter

A small set of reusable Terraform modules — `network`, `security-group`, `compute` —
built around the classic "VPC + SG + instances" shape you'd use on any cloud, but
wired up against the Docker provider so the whole thing is runnable on a laptop
with just `docker` installed, no cloud account required.

## Why Docker as the backend

I wanted modules I could actually `terraform apply` and poke at, not just lint.
Docker gives real resources (networks, containers, published ports) with the
same lifecycle semantics as a cloud provider, so the modules exercise real
`create/update/destroy` behavior instead of being a `local_file` demo.

The module *interfaces* are written to look like their cloud equivalents
(`ingress_rules` shaped like an AWS security group rule, `count_` like an ASG
desired count) specifically so swapping the provider block later is a matter
of rewriting `main.tf` inside each module, not touching any code that calls them.

## Structure

```
modules/
  network/         # docker_network  ~ VPC/subnet
  security-group/  # validates + normalizes firewall rules ~ AWS security_group
  compute/         # docker_container ~ EC2 instance / ASG
examples/
  docker-sandbox/  # wires the three modules into a 2-replica nginx deployment
```

## Usage

```bash
cd examples/docker-sandbox
terraform init
terraform plan
terraform apply
```

This creates:
- a dedicated Docker network (`sandbox-net`, 10.30.0.0/24)
- a validated security-group object allowing inbound TCP/8080
- two `nginx-unprivileged` containers (listens on 8080, not the usual 80 —
  needed so the internal/external port in the security-group rule actually
  matches what the process binds to) on that network, published as 8080 and
  8081 on the host (the compute module offsets the external port per replica
  so multiple instances never collide on the same host port)

Verify it worked:

```bash
curl -sI http://localhost:8080
curl -sI http://localhost:8081
```

Tear down:

```bash
terraform destroy
```

## Module reference

### `modules/network`
| Input | Type | Default | Description |
|---|---|---|---|
| `name` | string | — | Base name, gets `-net` suffix |
| `subnet` | string | `10.20.0.0/24` | CIDR for the network |
| `labels` | map(string) | `{}` | Docker labels |

Outputs: `network_id`, `network_name`

### `modules/security-group`
| Input | Type | Default | Description |
|---|---|---|---|
| `name` | string | — | Name, used for the object identity |
| `ingress_rules` | list(object) | `[]` | `{ description, port, protocol = "tcp", cidr = "0.0.0.0/0" }` |

Validates that ports are in `1..65535` and protocol is `tcp`/`udp` before
anything gets applied — `terraform plan` fails fast on a typo'd port instead
of failing at apply time.

Outputs: `name`, `rules` (normalized `{ internal, external, protocol }` list,
ready to feed straight into the compute module).

### `modules/compute`
| Input | Type | Default | Description |
|---|---|---|---|
| `name` | string | — | Base name |
| `image` | string | — | Docker image |
| `count_` | number | `1` | Number of replicas |
| `network_id` / `network_name` | string | — | From the network module |
| `security_group_rules` | list(object) | `[]` | From the security-group module |
| `env` | map(string) | `{}` | Env vars |
| `command` | list(string) | `null` | Override entrypoint |

Outputs: `container_names`, `container_ips`

## Porting to a real cloud

Because the module *inputs/outputs* mirror a cloud shape, porting to AWS is
mostly a matter of rewriting the three `main.tf` files:

- `modules/network` → `aws_vpc` + `aws_subnet`
- `modules/security-group` → `aws_security_group` + `aws_security_group_rule`
  (the `rules` output already matches the shape `aws_instance` wants)
- `modules/compute` → `aws_instance` or `aws_autoscaling_group`

The `examples/docker-sandbox/main.tf` file wouldn't need to change at all.

## Verified

Ran end to end on a clean Ubuntu 22.04 box (Terraform 1.10.5, Docker Engine 27,
kreuzwerker/docker 3.9.0):

```
terraform init     -> OK
terraform validate -> Success! The configuration is valid.
terraform plan     -> Plan: 5 to add, 0 to change, 0 to destroy
terraform apply    -> Apply complete! Resources: 5 added
curl -sI http://localhost:8080 -> HTTP/1.1 200 OK (nginx/1.27.5)
curl -sI http://localhost:8081 -> HTTP/1.1 200 OK (nginx/1.27.5)
terraform destroy  -> Destroy complete! Resources: 5 destroyed
```

One real bug caught along the way: the first pass used the plain `nginx`
image, which listens on port 80 by default — but the security-group rule
(and therefore the published port) was 8080, so requests got a connection
reset. Fixed by switching to `nginxinc/nginx-unprivileged`, which listens on
8080 out of the box. Left it in this README because it's the kind of mismatch
between "port I opened" and "port the process actually binds to" that's easy
to hit with real cloud security groups too.
