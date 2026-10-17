#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
deploy_dir="$repo_root/var/kubernetes/production"
secrets_file="$deploy_dir/app-secrets.env"
kustomization_file="$deploy_dir/kustomization.yaml"
registry_repository="gnumoksha/eventhub-core"
registry_image="ghcr.io/$registry_repository"
registry_token_url="https://ghcr.io/token?scope=repository%3A${registry_repository//\//%2F}%3Apull"
registry_manifest_url="https://ghcr.io/v2/$registry_repository/manifests/latest"
rollout_timeout="${ROLLOUT_TIMEOUT:-5m}"

for command in kubectl curl jq python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Error: %s is required but was not found in PATH.\n' "$command" >&2
    exit 1
  fi
done

if [[ ! -f "$secrets_file" ]]; then
  printf 'Error: secrets file not found: %s\n' "$secrets_file" >&2
  printf 'Copy app-secrets.env.example to app-secrets.env and fill in its values.\n' >&2
  exit 1
fi

if grep -Eqi 'replace-with|change-me|todo' "$secrets_file"; then
  printf 'Error: app-secrets.env still contains example values.\n' >&2
  exit 1
fi

# Get the latest image digest for the main branch
registry_token="$(curl --fail --silent --show-error --location "$registry_token_url" \
  | jq -er 'if type == "object" and (.token | type == "string" and length > 0) then .token else error("GHCR token response does not contain a token") end')"
image_digest="$(curl --fail --silent --show-error --location \
  --output /dev/null \
  --dump-header - \
  --header "Authorization: Bearer $registry_token" \
  --header 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json' \
  "$registry_manifest_url" \
  | awk '
      tolower($1) == "docker-content-digest:" { gsub("\\r", "", $2); digest = $2 }
      END { if (digest != "") print digest }
    ')"
if [[ ! "$image_digest" =~ ^sha256:[[:xdigit:]]{64}$ ]]; then
  printf 'Error: could not resolve a valid image digest from the public GHCR latest tag (received: %q).\n' "$image_digest" >&2
  exit 1
fi

# update the kustomization.yaml with the image digest
python3 - "$kustomization_file" "$image_digest" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
digest = sys.argv[2]
contents = path.read_text()
updated, count = re.subn(
    r"(?m)^([ \t]*)(?:newTag|digest):[ \t]*.+$",
    rf"\g<1>digest: {digest}",
    contents,
)
if count != 1:
    raise SystemExit(f"Error: expected one newTag or digest entry in {path}, found {count}.")
path.write_text(updated)
PY

context="$(kubectl config current-context)"
printf 'Deploying image %s@%s to Kubernetes context: %s\n' "$registry_image" "$image_digest" "$context"

kubectl apply -k "$deploy_dir"

printf 'Waiting for PostgreSQL, RabbitMQ, and Redis...\n'
kubectl -n production rollout status statefulset/postgresql --timeout="$rollout_timeout"
kubectl -n production rollout status statefulset/rabbitmq --timeout="$rollout_timeout"
kubectl -n production rollout status deployment/redis --timeout="$rollout_timeout"

printf 'Waiting for the API before running database migrations...\n'
kubectl -n production rollout status deployment/eventhub-web --timeout="$rollout_timeout"
kubectl -n production exec deployment/eventhub-web -- alembic upgrade head

printf 'Waiting for the outbox relay...\n'
kubectl -n production rollout status deployment/outbox-relay --timeout="$rollout_timeout"

printf 'Deployment completed.\n'
