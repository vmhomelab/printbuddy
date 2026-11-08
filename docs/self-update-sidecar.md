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
      # Also update the slicer sidecars of this compose project (default true).
      - PRINTBUDDY_UPDATE_SLICER_SIDECARS=true
      - PRINTBUDDY_UPDATER_PORT=8787
    restart: unless-stopped
```

Start or recreate the stack:

```bash
docker compose up -d
```

## What the button does

When an administrator clicks **Update now**, Printbuddy calls the updater sidecar. For normal channel updates where no exact release image is supplied, the sidecar runs exactly:

```bash
docker compose -p "$PRINTBUDDY_COMPOSE_PROJECT" -f "$PRINTBUDDY_COMPOSE_FILE" pull "$PRINTBUDDY_SERVICE_NAME"
docker compose -p "$PRINTBUDDY_COMPOSE_PROJECT" -f "$PRINTBUDDY_COMPOSE_FILE" up -d "$PRINTBUDDY_SERVICE_NAME"
```

Only the configured service is recreated, plus the slicer sidecars described below. The updater does not run `docker compose up -d` for the full stack so it does not restart itself mid-job.

When the in-app update checker selected a specific release tag, including a beta tag such as `v0.2.5.1b13`, Printbuddy passes that target image to the sidecar. The sidecar then:

```bash
docker compose -p "$PRINTBUDDY_COMPOSE_PROJECT" -f "$PRINTBUDDY_COMPOSE_FILE" config --format json
docker pull "docker.io/vmhomelabde/printbuddy:<selected-release-tag>"
docker tag "docker.io/vmhomelabde/printbuddy:<selected-release-tag>" "<image declared by the compose service>"
docker compose -p "$PRINTBUDDY_COMPOSE_PROJECT" -f "$PRINTBUDDY_COMPOSE_FILE" up -d --force-recreate "$PRINTBUDDY_SERVICE_NAME"
```

That extra retag step is intentional: it lets a compose file that tracks `docker.io/vmhomelabde/printbuddy:latest` install an explicitly selected beta release without rewriting the mounted compose file.

### Slicer sidecars

After Printbuddy itself, the updater also updates the slicer sidecars
(`bambu-studio-api`, `orca-slicer-api`) of the same Compose project, so they
match the sidecar revision the new Printbuddy expects:

```bash
docker compose -p "$PRINTBUDDY_COMPOSE_PROJECT" -f "$PRINTBUDDY_COMPOSE_FILE" config --format json
docker compose -p "$PRINTBUDDY_COMPOSE_PROJECT" -f "$PRINTBUDDY_COMPOSE_FILE" pull <sidecar service>
docker compose -p "$PRINTBUDDY_COMPOSE_PROJECT" -f "$PRINTBUDDY_COMPOSE_FILE" up -d <sidecar service>
```

Only services whose image is listed in `PRINTBUDDY_ALLOWED_SIDECAR_IMAGES`
(default: `docker.io/vmhomelabde/printbuddy-orca-slicer-api` and
`docker.io/vmhomelabde/printbuddy-bambu-studio-api`) are touched. A failed
sidecar step does not fail the update: Printbuddy is already running the new
version, and **Settings → Slicer → Test slicer connection** reports a sidecar
that is still outdated. Set `PRINTBUDDY_UPDATE_SLICER_SIDECARS=false` to
update only Printbuddy. Sidecars in a separate Compose project (the
`slicer-api/` stack) are not reached; update those by hand.

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
