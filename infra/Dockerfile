FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

COPY --from=uv /uv /uvx /usr/local/bin/
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV UV_PROJECT_ENVIRONMENT=/opt/farmared-venv \
    UV_LINK_MODE=copy \
    PATH="/opt/farmared-venv/bin:$PATH"
WORKDIR /workspaces/farmared
CMD ["sleep", "infinity"]
