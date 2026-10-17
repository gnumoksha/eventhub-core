#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
deploy_dir="$repo_root/var/kubernetes/production"
secrets_file="$deploy_dir/app-secrets.env"
kustomization_file="$deploy_dir/kustomization.yaml"
package_versions_endpoint="/users/gnumoksha/packages/container/eventhub-core/versions?per_page=100"
rollout_timeout="${ROLLOUT_TIMEOUT:-5m}"

for command in kubectl gh jq python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Error: %s is required but was not found in PATH.\n' "$command" >&2
    exit 1
  fi
done

if ! gh auth status >/dev/null 2>&1; then
  printf 'Error: authenticate with GitHub CLI first (gh auth login).\n' >&2
  exit 1
fi

if [[ ! -f "$secrets_file" ]]; then
  printf 'Error: secrets file not found: %s\n' "$secrets_file" >&2
  printf 'Copy app-secrets.env.example to app-secrets.env and fill in its values.\n' >&2
  exit 1
fi

if grep -Eqi 'replace-with|change-me|todo' "$secrets_file"; then
  printf 'Error: app-secrets.env still contains example values.\n' >&2
  exit 1
fi

image_tag="$(gh api --paginate "$package_versions_endpoint" | jq -rs '[add[] | select((.metadata.container.tags // []) | any(startswith("sha-")))] | sort_by(.created_at) | last | (.metadata.container.tags[]? | select(startswith("sha-")))')"
if [[ ! "$image_tag" =~ ^sha-[[:xdigit:]]{7,40}$ ]]; then
  printf 'Error: could not find a valid sha-* image tag in GitHub Container Registry.\n' >&2
  exit 1
fi

python3 - "$kustomization_file" "$image_tag" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
tag = sys.argv[2]
contents = path.read_text()
updated, count = re.subn(r"(?m)^([ \t]*newTag:[ \t]*).+$", rf"\g<1>{tag}", contents)
if count != 1:
    raise SystemExit(f"Error: expected one newTag entry in {path}, found {count}.")
path.write_text(updated)
PY

context="$(kubectl config current-context)"
printf 'Deploying image tag %s to Kubernetes context: %s\n' "$image_tag" "$context"

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
