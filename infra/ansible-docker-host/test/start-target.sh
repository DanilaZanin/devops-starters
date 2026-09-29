#!/usr/bin/env bash
# Spins up a throwaway systemd-enabled Ubuntu container to run the role
# against, so we're not testing "did the YAML parse" but "does this actually
# install and start services on a real host". Uses geerlingguy's
# docker-ubuntu2204-ansible image, which is what the Ansible community itself
# uses for Molecule tests since it ships /sbin/init and works with systemd
# under docker --privileged.
set -euo pipefail

CONTAINER_NAME="ansible-test-target"
SSH_PUBKEY_FILE="${1:-$HOME/.ssh/id_ed25519.pub}"

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

docker run -d --privileged \
  --name "$CONTAINER_NAME" \
  --cgroupns=host \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
  geerlingguy/docker-ubuntu2204-ansible:latest

echo "waiting for systemd inside the container..."
sleep 5

docker exec "$CONTAINER_NAME" bash -c "
  apt-get update -qq && apt-get install -y -qq openssh-server sudo >/dev/null
  useradd -m -s /bin/bash deploy || true
  usermod -aG sudo deploy
  echo 'deploy ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deploy
  mkdir -p /home/deploy/.ssh
  chmod 700 /home/deploy/.ssh
"

docker cp "$SSH_PUBKEY_FILE" "$CONTAINER_NAME:/home/deploy/.ssh/authorized_keys"
docker exec "$CONTAINER_NAME" bash -c "
  chmod 600 /home/deploy/.ssh/authorized_keys
  chown -R deploy:deploy /home/deploy/.ssh
  systemctl enable ssh
  systemctl start ssh
"

IP=$(docker inspect -f '{{ .NetworkSettings.Networks.bridge.IPAddress }}' "$CONTAINER_NAME")
echo "target ready: deploy@$IP"
echo "$IP" > /tmp/ansible-test-target-ip
