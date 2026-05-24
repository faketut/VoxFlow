# Shipping on GHCR: Reproducible, Non-Root Images for a WS App

*A small Dockerfile and a small workflow, with the choices that matter.*

## Why ship images at all

For a long time VoxFlow was deployed via "git pull and restart". Fine for a side project. Three problems show up the moment a second person joins:

- "Works on my machine" — different Python versions, different `audioop` outcomes.
- Rollback is `git reset --hard <sha>` plus a redeploy — and you have to remember to rebuild the venv.
- There's no immutable artifact to point an incident report at ("which build was running when this broke?").

A container image solves all three. GitHub Container Registry (GHCR) is the path of least resistance when your code already lives on GitHub.

## The Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install dependencies first to leverage Docker layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source.
COPY app ./app

# Run as non-root for safety.
RUN useradd --create-home --shell /bin/bash voxflow \
    && chown -R voxflow:voxflow /app
USER voxflow

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
```

That's the whole thing. A few specific choices are worth defending.

**`python:3.11-slim`, not `alpine`.**
Alpine images use musl libc. Half the Python wheels you'll install — `pydantic-core`, `httpx`'s optional extras, anything that ships a compiled `.so` — don't have musl wheels, so pip silently switches to building from source. Build time triples; image size becomes larger than slim because gcc + headers got installed too. Stick with `-slim` unless you have a measured reason.

**`PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1`.**
The first stops `__pycache__` clutter (which would also defeat the read-only filesystem you might add later). The second forces line-buffered stdout, so `kubectl logs` shows your logs in real time instead of in 4KB chunks.

**Requirements *before* source.**
`COPY requirements.txt` then `RUN pip install`, then `COPY app`. This way, edits to source don't invalidate the pip-install layer — rebuilds drop from 90 seconds to 5. The single most cost-effective Dockerfile change.

**Non-root user.**
The default `USER` in `python:3.11-slim` is root. If the app gets RCE'd (think: a hostile prompt that smuggles a tool-injection payload into a shell), the attacker is root inside the container. Add a non-root user. Three lines. Zero downsides for this kind of app.

**No `HEALTHCHECK`.**
On purpose. In Kubernetes, the orchestrator owns health checks (via `/health` and `/ready`). A Docker-level `HEALTHCHECK` would duplicate logic and confuse the picture. If you deploy with bare `docker compose`, add one; if you deploy on k8s/Fly/Cloud Run, leave it out.

## The GitHub Actions workflow

```yaml
name: Build and Push Docker Image

on:
  push:
    branches: [main]
    tags: ['v*']

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write          # required to push to GHCR
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=sha,format=long
            type=ref,event=branch
            type=semver,pattern={{version}}
      - uses: docker/build-push-action@v6
        with:
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

Things to highlight:

**`packages: write` and `GITHUB_TOKEN`.**
No long-lived PAT, no rotating secrets. The auto-issued `GITHUB_TOKEN` already has permission to push to GHCR if you grant `packages: write` in the job. One less thing to leak.

**Three tag formats from `docker/metadata-action`:**
- `type=sha,format=long` → `ghcr.io/owner/voxflow:abc123...` (the immutable one — pin production to this)
- `type=ref,event=branch` → `ghcr.io/owner/voxflow:main` (latest-on-branch — fine for staging)
- `type=semver,pattern={{version}}` → `ghcr.io/owner/voxflow:1.2.3` (when you push a tag)

Production should pin the SHA tag. Without it, rolling back means rebuilding old code and racing to push it. With it, rolling back is editing one digest in a Helm chart.

**`cache-from: type=gha` / `cache-to: type=gha,mode=max`.**
GitHub-hosted layer cache. Cuts a clean build from ~90s to ~25s when only source changes. Free, no setup, no S3 bucket to manage.

## What this *isn't* (and why that's fine)

This isn't a hermetic build. It pins `requirements.txt`, not the transitive dependency graph. For full reproducibility you'd add `pip-tools` + `pip install --require-hashes`. Worth doing when supply-chain trust matters (financial, healthcare, regulated). Not worth the maintenance burden for everything else.

This isn't a signed image. Cosign + Sigstore is the next step when you need to prove provenance to a downstream consumer. Until you have that consumer, holding off keeps the workflow simple.

This isn't a multi-arch build. `linux/amd64` only. Add `linux/arm64` (e.g. for an M-series laptop dev loop) with a one-line `platforms:` field on the build-push action — but only when someone actually tries to `docker run` it on arm and fails.

## The payoff

Three things change the day you start shipping immutable images to GHCR:

1. **Deploy = pin a digest.** Whatever orchestrator you use (k8s, Compose, Fly, ECS), the deployment manifest references one SHA-pinned tag. No more "redeploy from main."
2. **Rollback = pin the previous digest.** Seconds, not minutes.
3. **Incidents have a name.** "We were running `voxflow:a1b2c3d4` at 14:22 UTC." That string is portable: someone six months later can `docker pull` and reproduce the exact behavior.

Plus, the CI job runs ~25 seconds. The cost is negligible.

## Takeaway

A useful Dockerfile is `python:3.11-slim`, requirements layer before source, non-root user, no `HEALTHCHECK` if k8s owns probes. A useful GHCR workflow is `GITHUB_TOKEN` (no PAT), SHA-tagged immutable images, GHA layer cache. Both fit on a screen. Both pay back the first time you need to roll back.
