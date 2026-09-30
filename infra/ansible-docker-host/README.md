# SSH hardening that survives Ubuntu cloud-init: Ansible role for a Docker host

Level: **verified** (trap test runs in CI on every PR).

An Ansible role that turns a fresh Ubuntu 22.04/24.04 host into a Docker host:
Docker Engine from the official apt repo, `node_exporter` as a systemd service,
`ufw`, and sshd hardening that is checked against what sshd actually uses.

## Problem

You set `PasswordAuthentication no` in `/etc/ssh/sshd_config`, the play reports
`changed`, `sshd -t` passes, and the server still accepts password logins. On
Ubuntu, `sshd_config` starts with `Include /etc/ssh/sshd_config.d/*.conf`, cloud
images ship `/etc/ssh/sshd_config.d/50-cloud-init.conf` with
`PasswordAuthentication yes`, and sshd keeps the first value it reads for most
keywords (see `sshd_config(5)`, <https://man.openbsd.org/sshd_config>). The
drop-in is read first, so your edit is dead text.

This role writes `/etc/ssh/sshd_config.d/00-hardening.conf` (lexically before
`50-cloud-init.conf`) and then asserts on the output of `sshd -T`, so the play
fails if any other file still wins.

## Quick start

```bash
make check-prereqs   # docker, ansible-lint, molecule (with the docker driver)
make test            # lint, trap (broken must fail), access, keytrust, then the fixed role twice
```

`make test` prints `OK: broken hardening failed the sshd -T check as expected`
after the trap step. The `access` step proves an unreachable new ssh port cannot lock you
out and that `ssh_port=2222` really moves the listener on 22.04 and 24.04; the `keytrust` step
proves apt trusts only Docker's key. Then it runs the full molecule sequence
(`create, prepare, converge, idempotence, verify, destroy`) for the fixed role on
Ubuntu 22.04 and 24.04 containers. It exits non-zero if the broken variant
passes, if it fails for any reason other than the sshd assertion, if either extra
step fails, or if the fixed role is not idempotent. Container names carry a suffix
derived from the directory (`MOLECULE_RUN`), so two copies of the module can run
against one Docker daemon.

Other targets: `make up` (converge and keep the containers), `make down`,
`make reset` (also deletes downloaded collections and logs).

| | Status |
|---|---|
| macOS arm64 + colima (4 CPU / 8 GB) | verified 2026-09-30: `make test` green (lockout, customport, keytrust, broken, default), also from a copied directory |
| ubuntu-24.04 GitHub runner | CI only, not measured here; see the workflow `.github/workflows/ansible-docker-host.yml` |
| First-run time | `make test` (trap, access, keytrust, fixed) measured 2026-09-30: 4 min 38 s in place and 5 min 17 s from a copied directory, both with the Ubuntu images already local; a cold machine adds the image pulls (not measured). The Docker apt install in the `default` scenario dominates |
| RAM | peak about 2.2 GB used in the colima VM while two systemd containers ran (other containers were running too, so this is an upper bound) |

Do not treat a green badge as more
than the boundaries below.

Using it on a real host:

```bash
ansible-galaxy collection install -r requirements.yml
cp inventory/hosts.example.ini inventory/hosts.ini   # edit
ansible-playbook -i inventory/hosts.ini playbook.yml
```

Confirm key-based login works for the Ansible user before the first run.
The role disables password login and does not check that a key is installed.

## Traps this avoids

1. **sshd first-match plus the cloud-init drop-in** (reproduced in tests). Fix: a
   `00-hardening.conf` drop-in and an `sshd -T` assertion.
2. **Firewall and sshd disagree about the port, or ufw closes the old one too early**
   (reproduced in tests). The role hardens and restarts sshd first, then waits until
   something listens on `docker_bootstrap_ssh_port`, and only then touches ufw. If the port
   never comes up the play stops with `SSH_PORT_NOT_LISTENING` while ufw is untouched and the
   old port still works. On Ubuntu 24.04 sshd is started by `ssh.socket`; its
   `sshd-socket-generator` copies `Port` from the sshd config into
   `/run/systemd/generator/ssh.socket.d/addresses.conf`, but only when systemd re-runs its
   generators, so the handler does `daemon-reload`, restarts `ssh.socket` and then `ssh`. A
   plain `systemctl restart ssh` does not re-run generators, so the old socket may stay. The `access` step covers
   both the working case (22.04 and 24.04, port 2222) and the failing one (a socket drop-in
   pinned to port 22 that the generator cannot override).
3. **Untrusted Docker apt key** (reproduced in tests). The key bundle is downloaded and its
   fingerprint compared with `docker_bootstrap_gpg_fingerprint`. apt's `signed-by` trusts
   every key in the file it points at, so a check that the expected fingerprint is present
   is not enough. The role exports only the verified key into `/etc/apt/keyrings/docker.gpg`,
   points `signed-by` there, and removes the key files when verification fails. The `keytrust`
   step feeds a bundle with Docker's real key plus a foreign key and requires a one-key
   keyring, and requires a wrong fingerprint to be refused.
4. **node_exporter on the wrong architecture or a bad download.** The tarball
   name is derived from `ansible_facts['architecture']` (amd64 or arm64) and the
   sha256 is taken from the release's `sha256sums.txt`. Not covered by the tests
   beyond whichever architecture your machine runs.
5. **Roles that are not idempotent.** The molecule `idempotence` step fails the
   run if the second converge reports any change.

## What the test proves / does NOT prove

Proves:

- With a cloud-init style drop-in present, the `sshd_config` edit leaves
  `sshd -T` reporting `passwordauthentication yes` (broken fails), and the role
  leaves it at `no` (fixed passes), on Ubuntu 22.04 and 24.04.
- The role converges twice with `changed=0` on the second run.
- With `ssh_port=2222` the effective config, the actual listener (`ss`) and ufw all say
  2222 and nothing listens on 22, on 22.04 (plain sshd) and 24.04 (`ssh.socket`).
- When the new port never listens, the play stops before ufw is enabled and port 22 keeps
  listening.
- A key bundle with an extra key produces a keyring holding only Docker's key; a wrong
  fingerprint is refused and leaves no key files.
- After converge: root login off, `ufw` active with default deny incoming and
  the ssh port open, `docker` client installed, `node_exporter` answers on
  `127.0.0.1:9100`.

Does NOT prove:

- Behaviour on a real VM. The targets are containers; `50-cloud-init.conf` is
  written by the test, not by cloud-init. Different cloud images may put other
  files in `sshd_config.d`.
- A real password login is refused. The test reads sshd's effective
  configuration with `sshd -T`; it never opens a connection.
- That a real remote login works on the new port through a real network path; the
  listener and ufw rules are checked from inside the container.
- Docker's real apt repository being usable with the exported keyring end to end is only
  exercised by the default scenario's Docker install, not by `keytrust`.
- `ufw` rules for ports published by Docker (see below). ufw inside a container
  also depends on the host kernel.
- Docker daemon behaviour beyond installation. The daemon runs nested inside a
  privileged container.
- Package and release versions are current. Pins are listed in the tables below.

## Docker publish bypasses ufw

`ufw` does not filter ports published with `docker run -p` or `ports:` in
compose. Docker inserts its own iptables rules ahead of ufw's, so
`ufw default deny incoming` does not protect a published container port. Bind
published ports to `127.0.0.1` (`127.0.0.1:8080:80`) or put filtering rules in
the `DOCKER-USER` iptables chain, which Docker evaluates before its own rules.
This role does not manage `DOCKER-USER`.

## Local demo vs production

The demo runs against throwaway containers. For real hosts you still need:

- SSH keys managed outside the role, and a second admin path (console or
  provider rescue) in case the firewall or sshd config locks you out.
- `DOCKER-USER` rules or loopback-only port publishing (see above).
- Automatic security updates (`unattended-upgrades`), log shipping, and
  brute-force protection such as `fail2ban`. None are included.
- A pinned Docker Engine version if you need reproducible hosts; the role
  installs whatever the Docker repo currently serves.
- Prometheus scraping node_exporter from the CIDRs in
  `docker_bootstrap_node_exporter_allowed_cidrs`. The default `10.0.0.0/8` is a
  placeholder.
- Inventory and secrets handled with your usual tooling (Ansible Vault, SOPS).

## Variables

`roles/docker_bootstrap/defaults/main.yml`:

| Variable | Default | Description |
|---|---|---|
| `docker_bootstrap_users` | `[]` | Users added to the `docker` group |
| `docker_bootstrap_gpg_fingerprint` | Docker's release key | Expected fingerprint of the apt key |
| `docker_bootstrap_node_exporter_version` | `1.12.1` | node_exporter release |
| `docker_bootstrap_node_exporter_port` | `9100` | |
| `docker_bootstrap_node_exporter_allowed_cidrs` | `["10.0.0.0/8"]` | Sources allowed to reach the exporter |
| `docker_bootstrap_ssh_port` | `22` | Used for both sshd and ufw |
| `docker_bootstrap_ssh_disable_password_auth` | `true` | |
| `docker_bootstrap_ssh_disable_root_login` | `true` | |
| `docker_bootstrap_firewall_enabled` | `true` | |
| `docker_bootstrap_firewall_extra_tcp_ports` | `[]` | Extra ports open to everyone |

Version pins: Ubuntu base images `ubuntu:22.04` and `ubuntu:24.04`, node_exporter
`1.12.1`. Ubuntu images are pinned by digest (build arg `BASE` in
`molecule/*/molecule.yml`). Test tooling is pinned exactly in `requirements-dev.txt`
(ansible-core 2.21.4, ansible-lint 26.9.0, molecule 26.9.0, molecule-plugins 26.9.28)
and the collections: `requirements.yml` holds the role's runtime dependency (community.general 13.4.0),
`molecule/requirements.yml` adds the test-only community.docker 5.3.0 for the molecule docker driver.

## Copy it into your project

Minimum: `roles/docker_bootstrap/`, `requirements.yml`, and a play that applies
the role (`playbook.yml`). To keep the tests, also copy `molecule/` (including
`molecule/requirements.yml`, which the Makefile installs), `traps/`,
`Makefile`, `requirements-dev.txt`, `.ansible-lint` and `ansible.cfg`. The
module has no references outside its own directory.

## Layout

```
Makefile                        test, up, down, reset, check-prereqs
playbook.yml                    example play
roles/docker_bootstrap/         the role
traps/broken_ssh_hardening.yml  the trap: the sshd_config edit that does not work
molecule/default/               fixed role, with idempotence check
molecule/broken/                trap: same fixture, broken hardening, verify must fail
molecule/customport/            ssh_port=2222 on 22.04 and 24.04 (ssh.socket generator)
molecule/lockout/               new port never listens: role must stop before ufw, 22 stays open
molecule/keytrust/              key bundle with an extra key: apt keyring holds only Docker's key
molecule/shared/                Dockerfile, cloud-init fixture, sshd -T check
```
