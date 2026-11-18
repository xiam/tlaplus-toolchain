# syntax=docker/dockerfile:1
# check=skip=InvalidDefaultArgInFrom
#
# (The check is skipped because the base-image arguments have no default on
# purpose: a build without the pins must fail.)
#
# The tlaplus-toolchain image. Contract: docs/SPECS.md#the-image.
#
# Every pin comes from pins.env through build arguments; this file holds no
# pin of its own. Build with `make build`, which passes them. A build without
# them fails in the first step.

ARG BASE_IMAGE
ARG BASE_DIGEST

# ---------------------------------------------------------------------------
# Stage 1: download tla2tools.jar and verify its SHA256.
# Runs on the build platform: the jar is platform-independent, so a
# cross-platform build needs no emulation for this stage.
# ---------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM ${BASE_IMAGE}@${BASE_DIGEST} AS tla2tools

ARG TLC_VERSION
ARG TLC_SHA256

RUN set -eu; \
    : "${TLC_VERSION:?build argument TLC_VERSION is not set (use make build)}"; \
    : "${TLC_SHA256:?build argument TLC_SHA256 is not set (use make build)}"; \
    url="https://github.com/tlaplus/tlaplus/releases/download/v${TLC_VERSION}/tla2tools.jar"; \
    mkdir -p /out; \
    # curl retries timeouts, 408, 429, 5xx and refused connections.
    # --max-time is per attempt; --retry-max-time bounds the whole window.
    curl -fsSL --proto '=https' --tlsv1.2 --max-time 120 \
        --retry 3 --retry-delay 2 --retry-connrefused --retry-max-time 300 \
        -o /out/tla2tools.jar "$url"; \
    actual="$(sha256sum /out/tla2tools.jar | cut -d' ' -f1)"; \
    if [ "$actual" != "$TLC_SHA256" ]; then \
        echo "SHA256 mismatch for tla2tools.jar v${TLC_VERSION}" >&2; \
        echo "  expected: ${TLC_SHA256}" >&2; \
        echo "  actual:   ${actual}" >&2; \
        exit 1; \
    fi; \
    echo "tla2tools.jar v${TLC_VERSION}: SHA256 verified (${actual})"

# ---------------------------------------------------------------------------
# Stage 2: the toolchain image.
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE}@${BASE_DIGEST}

ARG BASE_IMAGE
ARG BASE_DIGEST
ARG BASE_TAG
ARG JRE_VERSION
ARG TLC_VERSION
ARG TLC_SHA256

# make, git and python3 for project scripts that run inside the container.
RUN set -eu; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        git make python3; \
    rm -rf /var/lib/apt/lists/*

# The default user. The image also runs as any other UID (`--user`), so
# nothing below depends on this account: HOME points at the scratch directory
# and every installed file is world-readable.
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /tmp \
        --shell /usr/sbin/nologin tlc; \
    # Created here: COPY --chmod would also apply its mode to the directory.
    mkdir -m 0755 /opt/tlaplus

COPY --from=tla2tools --chmod=0444 /out/tla2tools.jar /opt/tlaplus/tla2tools.jar

# --- Commands ---------------------------------------------------------------
# The tlc-check command is installed in this section (into /usr/local/bin).
COPY --chmod=0755 bin/tlc-check /usr/local/bin/tlc-check
# The base image's entrypoint script is dropped: the container runs exactly
# the command it is given.
ENTRYPOINT []
CMD ["tlc-check", "--help"]
# ----------------------------------------------------------------------------

ENV TLA2TOOLS_JAR=/opt/tlaplus/tla2tools.jar \
    TLC_VERSION=${TLC_VERSION} \
    TLC_SHA256=${TLC_SHA256} \
    HOME=/tmp

LABEL org.opencontainers.image.title="tlaplus-toolchain" \
      org.opencontainers.image.description="Pinned TLA+ toolchain: Eclipse Temurin JRE 21 and tla2tools.jar (TLC)" \
      org.opencontainers.image.source="https://github.com/xiam/tlaplus-toolchain" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="${BASE_IMAGE}:${BASE_TAG}" \
      org.opencontainers.image.base.digest="${BASE_DIGEST}" \
      io.github.xiam.tlaplus-toolchain.tlc.version="${TLC_VERSION}" \
      io.github.xiam.tlaplus-toolchain.tlc.sha256="${TLC_SHA256}" \
      io.github.xiam.tlaplus-toolchain.jre.version="${JRE_VERSION}"

USER 10001:10001
WORKDIR /tmp
