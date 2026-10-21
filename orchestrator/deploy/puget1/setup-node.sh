#!/usr/bin/env bash
# Retires the CoreWeave GPU node dependency for the single Puget1 worker.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo 'Run this setup with sudo.' >&2; exit 1; }
TS_IP=100.102.65.120
test "$(tailscale ip -4)" = "$TS_IP" || {
  echo 'This setup is for Puget1 (100.102.65.120); refusing a different host.' >&2
  exit 1
}
test ! -e /etc/rancher/k3s/config.yaml || {
  echo 'An existing K3s configuration needs review; refusing to overwrite it.' >&2
  exit 1
}
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl gnupg2 rsync
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |
  gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update -qq
apt-get install -y --no-install-recommends \
  nvidia-container-toolkit=1.20.1-1 nvidia-container-toolkit-base=1.20.1-1 \
  libnvidia-container-tools=1.20.1-1 libnvidia-container1=1.20.1-1
install -d -m 0755 /etc/rancher/k3s
cat > /etc/rancher/k3s/config.yaml <<'YAML'
node-name: puget1
node-ip: 100.102.65.120
bind-address: 100.102.65.120
advertise-address: 100.102.65.120
tls-san:
  - 100.102.65.120
  - puget1.tailb5dd08.ts.net
flannel-iface: tailscale0
secrets-encryption: true
write-kubeconfig-mode: '0600'
disable:
  - traefik
  - servicelb
kubelet-arg:
  - address=100.102.65.120
YAML
curl -fsSL https://get.k3s.io -o /tmp/hexapod-install-k3s.sh
INSTALL_K3S_VERSION=v1.36.5+k3s1 sh /tmp/hexapod-install-k3s.sh
install -d -o user -g user -m 0700 /home/user/.kube
sed 's#https://127.0.0.1:6443#https://100.102.65.120:6443#' \
  /etc/rancher/k3s/k3s.yaml > /home/user/.kube/puget1.yaml
chown user:user /home/user/.kube/puget1.yaml
chmod 0600 /home/user/.kube/puget1.yaml
install -d -o user -g user -m 0750 /srv/hexapod /srv/hexapod/worker /srv/hexapod/backups
export KUBECONFIG=/home/user/.kube/puget1.yaml
kubectl wait --for=create node/puget1 --timeout=180s
kubectl wait --for=condition=Ready node/puget1 --timeout=180s
kubectl apply -f /home/user/hexapod-migration/nvidia-device-plugin.yaml
kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset --timeout=180s
kubectl get node puget1 -o wide
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
