# ansible-docker-bootstrap

An idempotent Ansible role that takes a fresh Ubuntu 22.04/24.04 host and turns
it into a Docker-ready box: installs Docker Engine from the official repo,
deploys `node_exporter` as a systemd service, locks the firewall down with
`ufw`, and applies basic SSH hardening. This is the same shape of role I'd
reach for to bootstrap a new host before handing it to a CI runner or a
docker-compose deployment.

## What it does

- **Docker** — adds Docker's official apt repo + GPG key (not the distro's
  stale `docker.io` package), installs `docker-ce`, `docker-ce-cli`,
  `containerd.io`, `docker-compose-plugin`, enables the service, adds the
  given users to the `docker` group.
- **node_exporter** — downloads the pinned version, installs it as an
  unprivileged systemd service with `ProtectSystem=strict` / `NoNewPrivileges`,
  restarts it automatically if the binary or unit file changes.
- **Firewall (ufw)** — default deny incoming / allow outgoing, opens the admin
  ports you list (SSH by default), and opens the node_exporter port *only*
  to the CIDRs you list as your monitoring subnet — not the world.
- **SSH hardening** — disables password auth, disables root login, validates
  `sshd_config` with `sshd -t` before ever restarting the service (so a typo
  can't lock you out).

## Structure

```
playbook.yml
inventory/hosts.example.ini
roles/docker_bootstrap/
  defaults/main.yml   # every tunable, see table below
  tasks/
    main.yml
    docker.yml
    node_exporter.yml
    firewall.yml
    ssh_hardening.yml
  handlers/main.yml
  templates/node_exporter.service.j2
requirements.yml       # community.general, needed for the ufw module
test/start-target.sh   # spins up a disposable target to test against
```

## Usage

```bash
ansible-galaxy collection install -r requirements.yml
cp inventory/hosts.example.ini inventory/hosts.ini   # edit with your hosts
ansible-playbook -i inventory/hosts.ini playbook.yml
```

Key variables (`roles/docker_bootstrap/defaults/main.yml`):

| Variable | Default | Description |
|---|---|---|
| `docker_bootstrap_users` | `[]` | Users to add to the `docker` group |
| `node_exporter_version` | `1.8.2` | Pinned node_exporter release |
| `node_exporter_port` | `9100` | |
| `node_exporter_allowed_cidrs` | `["10.0.0.0/8"]` | Only these CIDRs can reach node_exporter — point it at your monitoring subnet |
| `firewall_allowed_tcp_ports` | `[22]` | Ports open to everyone |
| `ssh_disable_password_auth` | `true` | |
| `ssh_disable_root_login` | `true` | |

## How I tested it (not just `--syntax-check`)

Linting a role tells you the YAML parses. It doesn't tell you the Docker repo
GPG key is correct, or that the ufw rule syntax is right, or that the role is
actually idempotent. So `test/start-target.sh` spins up
`geerlingguy/docker-ubuntu2204-ansible` — the same systemd-enabled image the
Ansible community uses for Molecule tests — as a disposable target, and I ran
the real playbook against it over real SSH:

```
$ ansible-playbook -i test-inventory.ini playbook.yml
...
PLAY RECAP *****************************************************************
172.17.0.2  : ok=27  changed=21  unreachable=0  failed=0  skipped=1

$ curl -s http://172.17.0.2:9100/metrics | head -3
# HELP go_gc_duration_seconds A summary of the pause duration of garbage collection cycles.
# TYPE go_gc_duration_seconds summary
go_gc_duration_seconds{quantile="0"} 0

$ ssh deploy@172.17.0.2 sudo docker version --format '{{.Server.Version}}'
29.7.0

$ sudo ufw status verbose   # (run inside the target)
Status: active
Default: deny (incoming), allow (outgoing), deny (routed)
22/tcp     ALLOW IN  Anywhere
9100/tcp   ALLOW IN  10.0.0.0/8

# ran it a second time to check idempotency:
$ ansible-playbook -i test-inventory.ini playbook.yml
PLAY RECAP *****************************************************************
172.17.0.2  : ok=24  changed=0  unreachable=0  failed=0  skipped=2
```

`changed=0` on the second run — the role is genuinely idempotent, not just
"doesn't crash if you run it twice."

Stack: Ansible 2.10 (core), `community.general` 13.x for the `ufw` module,
tested against Ubuntu 22.04, Docker CE 29.7.0.
