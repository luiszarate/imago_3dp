# imago-3dp-bridge: read-only printer bridge (SPEC 16.9). Standard library only.
# Base image pinned by digest (multi-arch index of python:3.11-slim, 21-Oct-2026: amd64 + arm64).
# To update: docker buildx imagetools inspect python:3.11-slim  -> copy the index "Digest".
FROM python:3.11-slim@sha256:cce12316475d7d56d605f76e1d811d0dc4e7227f2d4afd29951521264f504ff8

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 bridge \
    && useradd --system --uid 10001 --gid bridge --no-create-home --shell /usr/sbin/nologin bridge

WORKDIR /app
COPY --chown=root:root imago_bridge/ /app/imago_bridge/

USER bridge
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "-m", "imago_bridge"]
