# Self-update sidecar

Printbuddy can optionally show an **Update now** button for Docker Compose installs. The safe mode is a small updater sidecar: the main Printbuddy container does **not** receive Docker socket access. Only the sidecar can talk to the host Docker daemon.

## Security model

The updater sidecar mounts `/var/run/docker.sock`. That is effectively host-level Docker administration access. Enable it only when Printbuddy administrators are trusted to restart/update containers on that host.

Guardrails implemented by the sidecar:

- bearer-token authentication is required
- only one configured Compose file is used
- only one configured service is updated
- no arbitrary shell command is accepted from the UI
- subprocesses are run with argv lists, not `shell=True`
- concurrent update jobs are rejected
- returned logs are truncated and token-redacted

## Compose configuration

Generate a token first:

```bash
openssl rand -hex 32
```

Add it to `.env` next to your Compose file:

```env
PRINTBUDDY_UPDATER_TOKEN=replace-with-generated-token
```

Then enable the commented self-update block in `docker-compose.yml`:

```yaml
services:
  printbuddy:
    environment:
      - SELF_UPDATE_ENABLED=true
      - UPDATER_URL=http://127.0.0.1:8787
      - UPDATER_TOKEN=${PRINTBUDDY_UPDATER_TOKEN}

  printbuddy-updater:
    image: docker.io/vmhomelabde/printbuddy-updater:latest
    container_name: printbuddy-updater
    network_mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./docker-compose.yml:/host/docker-compose.yml:ro
    environment:
      - PRINTBUDDY_UPDATER_TOKEN=${PRINTBUDDY_UPDATER_TOKEN}
      - PRINTBUDDY_COMPOSE_FILE=/host/docker-compose.yml
      - PRINTBUDDY_COMPOSE_PROJECT=${COMPOSE_PROJECT_NAME:-printbuddy}
      - PRINTBUDDY_SERVICE_NAME=printbuddy
      - PRINTBUDDY_ALLOWED_IMAGE=docker.io/vmhomelabde/printbuddy
      - PRINTBUDDY_UPDATER_PORT=8787
    restart: unless-stopped
```

Start or recreate the stack:

```bash
docker compose up -d
```

## What the button does

When an administrator clicks **Update now**, Printbuddy calls the updater sidecar. The sidecar runs exactly:

```bash
docker compose -p "$PRINTBUDDY_COMPOSE_PROJECT" -f "$PRINTBUDDY_COMPOSE_FILE" pull "$PRINTBUDDY_SERVICE_NAME"
docker compose -p "$PRINTBUDDY_COMPOSE_PROJECT" -f "$PRINTBUDDY_COMPOSE_FILE" up -d "$PRINTBUDDY_SERVICE_NAME"
```

Only the configured service is recreated. The updater does not run `docker compose up -d` for the full stack so it does not restart itself mid-job.

## Troubleshooting

Check sidecar health from the host:

```bash
curl -H "Authorization: Bearer ${PRINTBUDDY_UPDATER_TOKEN}" http://127.0.0.1:8787/health
```

Expected healthy response:

```json
{
  "ok": true,
  "service": "printbuddy-updater",
  "docker_available": true,
  "compose_file_available": true
}
```

Common failures:

- `docker_available: false`: `/var/run/docker.sock` is not mounted into the updater.
- `compose_file_available: false`: the Compose file is not mounted at `PRINTBUDDY_COMPOSE_FILE`.
- Printbuddy shows manual commands: `SELF_UPDATE_ENABLED`, `UPDATER_URL`, or `UPDATER_TOKEN` is missing on the main container.
- Update job fails with service not found: `PRINTBUDDY_SERVICE_NAME` or `PRINTBUDDY_COMPOSE_PROJECT` does not match your Compose project.

## Manual fallback

If the sidecar is disabled, use the normal Docker Compose update path:

```bash
docker compose pull
docker compose up -d
```
