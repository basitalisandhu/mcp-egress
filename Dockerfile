# syntax=docker/dockerfile:1
#
# The mcp-egress CLI as an image. Build and run with:
#   docker build -t mcp-egress .
#   docker run --rm -v "$PWD:/work" mcp-egress run --out egress.json -- python server.py
#
# "run" spawns the MCP server inside the container, so the server command must exist in the image
# (Python with the mcp package is included) or in the mounted /work directory.
#
# The base image is pinned by digest (python:3.12-slim, multi-arch index).
ARG PYTHON_IMAGE=python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

# Build the wheel on the runner's own platform: the package is pure Python.
FROM --platform=$BUILDPLATFORM ${PYTHON_IMAGE} AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY src/ src/
RUN pip install --no-cache-dir --disable-pip-version-check build \
 && python -m build --wheel --outdir /dist

FROM ${PYTHON_IMAGE}
ARG VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="mcp-egress" \
      org.opencontainers.image.description="Record every host an MCP server contacts, per tool, and fail CI when a new one appears" \
      org.opencontainers.image.source="https://github.com/basitalisandhu/mcp-egress" \
      org.opencontainers.image.url="https://github.com/basitalisandhu/mcp-egress" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN --mount=type=bind,from=build,source=/dist,target=/dist \
    pip install /dist/*.whl \
 && useradd --uid 1000 --user-group --create-home --shell /usr/sbin/nologin app
WORKDIR /work
USER 1000:1000
ENTRYPOINT ["mcp-egress"]
CMD ["--help"]
