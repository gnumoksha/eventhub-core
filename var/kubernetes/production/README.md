# Production deployment

The manifests mirror the services in `compose.yaml` and use the `production`
target of the image published by the GitHub Actions workflow. The web server uses
the Dockerfile's production CMD; the outbox relay and consumers run as separate
processes.

## Prepare and deploy

1. Copy `app-secrets.env.example` to `app-secrets.env`.
2. Replace the example values. Generate `APP_SECRET` with `openssl rand -hex 32`
   and passwords with `openssl rand -hex 24`. Match `POSTGRES_PASSWORD` to the
   password in `DATABASE_URL`, and `RABBITMQ_DEFAULT_PASS` to the password in
   `RABBITMQ_DSN`. Hexadecimal values avoid having to
   escape special characters in the URLs. Also configure `RESEND_API_KEY` and
   `NOTIFICATIONS_FROM_EMAIL` so the notifications worker can deliver verification
   and password-change emails. Set `RUSTFS_ACCESS_KEY` and `RUSTFS_SECRET_KEY` to
   distinct random credentials. The deploy script extracts only these two keys
   into the `rustfs-auth` Secret used by RustFS; they are not stored in the Helm
   release values.
3. Review `PUBLIC_FRONTEND_URL`, `PUBLIC_API_URL`, and `CORS_ALLOWED_ORIGINS` in
   `app-config.yaml` and update them to match the domains used by the application.
4. Adjust `storageclass.dataStorageSize` and `storageclass.logStorageSize` in
   `rustfs.yaml` to fit the available space in the `local-path` StorageClass.
5. Point the DNS record for `files.eventhub.tobias.ws` to the cluster's Traefik
   ingress. To create a self-signed certificate for this hostname, run these
   commands from the repository root on your workstation:

   ```sh
   umask 077
   mkdir -p "$HOME/.local/share/eventhub/tls"
   openssl req -x509 -newkey rsa:3072 -nodes -days 365 -sha256 \
     -keyout "$HOME/.local/share/eventhub/tls/tls.key" \
     -out "$HOME/.local/share/eventhub/tls/tls.crt" \
     -subj "/CN=files.eventhub.tobias.ws" \
     -addext "subjectAltName=DNS:files.eventhub.tobias.ws"

   kubectl apply -f var/kubernetes/production/namespace.yaml
   kubectl -n production create secret tls rustfs-tls \
     --cert="$HOME/.local/share/eventhub/tls/tls.crt" \
     --key="$HOME/.local/share/eventhub/tls/tls.key" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

   This certificate expires after 365 days. Self-signed certificates are not
   trusted by browsers or API clients by default, so embedded files may not load
   until the certificate is trusted. Use a CA-signed certificate for public
   access, or install this certificate on each client that needs to trust it. Keep
   `tls.key` outside the repository.

6. Run the deploy script. It applies the manifests, installs or upgrades the
   `rustfs` Helm release (using the official chart version pinned in the script),
   waits for PostgreSQL, RabbitMQ, Redis, and the API, runs database migrations,
   then waits for the outbox relay and notifications consumer:

   ```sh
   ./bin/deploy.sh production
   ```

   To increase the rollout timeout, set `ROLLOUT_TIMEOUT` (for example,
   `ROLLOUT_TIMEOUT=10m`).

7. The S3 endpoint is available at `https://files.eventhub.tobias.ws`; the console
   remains internal at `http://rustfs:9001`. To access the application and console
   locally, forward their ports:

   ```sh
   kubectl -n production port-forward svc/eventhub-web 8000:8000
   kubectl -n production port-forward svc/rustfs 9001:9001
   ```

The application's Service remains internal to the cluster. The RustFS Ingress
exposes only the S3 endpoint; objects still need presigned URLs or a bucket policy
that allows public reads. The script accesses public GHCR without logging in,
resolves the digest for the `latest` alias, and pins that digest in the `digest`
field of `kustomization.yaml` before applying the manifests. The required tools are
`kubectl`, `helm`, `curl`, `jq`, `python3`, and `openssl` for the self-signed
certificate procedure above.

PostgreSQL and RabbitMQ use PVCs on the cluster's default StorageClass. On k3s
with its default configuration, this typically uses node-local storage. RustFS
uses Helm in standalone mode with `local-path` PVCs; adjust their sizes in
`rustfs.yaml` before deploying. Redis remains non-persistent, as in Compose.
