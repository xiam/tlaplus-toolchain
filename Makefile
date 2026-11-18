PYTHON ?= python3
LINT_ARGS ?=
DOCKER ?= docker

# The pins (base digest, TLC version, jar SHA256). pins.env is the only place
# that holds them.
include pins.env

# The local image that `make build` produces and `make test` checks.
IMAGE ?= tlaplus-toolchain:dev
# The platforms that `make build-platforms` builds (build only, no image).
PLATFORMS ?= linux/amd64,linux/arm64
# The BuildKit image of the temporary builder that `make build-platforms`
# uses. A build tool, not an input of the image, so it is not in pins.env.
BUILDKIT_IMAGE ?= docker.io/moby/buildkit:v0.26.2@sha256:de10faf919fc71ba4eb1dd7bd6449566d012b0c9436b1c61bfee21d621b009aa
# Extra flags for `docker buildx build`, for example `--no-cache`.
BUILD_FLAGS ?=

BUILD_ARGS = \
	--build-arg BASE_IMAGE=$(BASE_IMAGE) \
	--build-arg BASE_TAG=$(BASE_TAG) \
	--build-arg BASE_DIGEST=$(BASE_DIGEST) \
	--build-arg JRE_VERSION=$(JRE_VERSION) \
	--build-arg TLC_VERSION=$(TLC_VERSION) \
	--build-arg TLC_SHA256=$(TLC_SHA256)

# The checks that `make test` runs. Add a target here to extend it.
TESTS = test-release test-checksum test-smoke test-tlc-check

.PHONY: help lint build build-platforms release-build test $(TESTS)

help: ## List the targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

lint: ## Check that Markdown links resolve (and public-tree rules, when present)
	$(PYTHON) scripts/lint.py $(LINT_ARGS)

build: ## Build the image for the local platform as $(IMAGE)
	$(DOCKER) buildx build $(BUILD_ARGS) $(BUILD_FLAGS) --load -t $(IMAGE) .

# A multi-platform build needs a BuildKit container builder: the default
# `docker` driver builds one platform only. The builder is temporary and
# uniquely named, and is removed afterwards. BuildKit runs the RUN steps of a
# foreign platform with its bundled QEMU emulators, so the host needs no
# binfmt setup.
build-platforms: ## Build the image for $(PLATFORMS), without loading or pushing it
	@set -e; \
	builder=tlaplus-toolchain-$$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n'); \
	$(DOCKER) buildx create --name $$builder --driver docker-container \
		--driver-opt image=$(BUILDKIT_IMAGE) >/dev/null; \
	trap '$(DOCKER) buildx rm $$builder >/dev/null' EXIT; \
	echo "== build-platforms: $(PLATFORMS) (builder $$builder)"; \
	$(DOCKER) buildx build --builder $$builder $(BUILD_ARGS) $(BUILD_FLAGS) \
		--platform $(PLATFORMS) --output type=cacheonly .

# Release build of one platform (used by .github/workflows/release.yml and by
# the local rehearsal in docs/RELEASE.md). One build, two outputs, so the image
# that `make test` checks is byte for byte the image that is pushed:
#   - loaded into the local Docker image store as $(IMAGE), and
#   - pushed to $(RELEASE_REPO) by digest only: no tag is pushed here.
# The digest is written to $(DIGEST_FILE). The tag is added later, once, by
# `docker buildx imagetools create` (see docs/RELEASE.md).
RELEASE_REPO ?=
RELEASE_PLATFORM ?= linux/amd64
RELEASE_VERSION ?=
RELEASE_REVISION ?=
DIGEST_FILE ?= release-digest.txt
# Extra flags for `docker buildx create`, for example `--driver-opt
# network=host` when RELEASE_REPO is a registry on localhost (rehearsal).
RELEASE_BUILDER_FLAGS ?=

release-build: ## Build $(RELEASE_PLATFORM), load it as $(IMAGE) and push it by digest to $(RELEASE_REPO)
	@set -e; \
	test -n "$(RELEASE_REPO)" || { echo "release-build: RELEASE_REPO is not set" >&2; exit 2; }; \
	test -n "$(RELEASE_VERSION)" || { echo "release-build: RELEASE_VERSION is not set" >&2; exit 2; }; \
	builder=tlaplus-toolchain-$$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n'); \
	$(DOCKER) buildx create --name $$builder --driver docker-container \
		--driver-opt image=$(BUILDKIT_IMAGE) $(RELEASE_BUILDER_FLAGS) >/dev/null; \
	trap '$(DOCKER) buildx rm $$builder >/dev/null' EXIT; \
	meta=$$(mktemp); \
	echo "== release-build: $(RELEASE_PLATFORM) -> $(RELEASE_REPO) (builder $$builder)"; \
	$(DOCKER) buildx build --builder $$builder $(BUILD_ARGS) $(BUILD_FLAGS) \
		--platform $(RELEASE_PLATFORM) \
		--label org.opencontainers.image.version=$(RELEASE_VERSION) \
		--label org.opencontainers.image.revision=$(RELEASE_REVISION) \
		--provenance=false --sbom=false \
		--metadata-file $$meta \
		--output type=docker,name=$(IMAGE) \
		--output type=image,name=$(RELEASE_REPO),push-by-digest=true,name-canonical=true,push=true \
		.; \
	digest=$$($(PYTHON) -c 'import json,sys; print(json.load(open(sys.argv[1]))["containerimage.digest"])' $$meta); \
	rm -f $$meta; \
	case "$$digest" in sha256:*) ;; *) echo "release-build: no image digest" >&2; exit 1;; esac; \
	echo "$$digest" > $(DIGEST_FILE); \
	echo "== release-build: $(RELEASE_PLATFORM) pushed as $(RELEASE_REPO)@$$digest"

test: $(TESTS) ## Run every check against $(IMAGE) (run `make build` first)

test-release: ## Run the offline tests of the release checks (scripts/release.py)
	$(PYTHON) test/release/test_release.py -v

test-checksum: ## Check that the build fails on a wrong jar SHA256
	DOCKER="$(DOCKER)" sh test/smoke/bad-checksum.sh

test-smoke: ## Check the image metadata and run TLC on the smoke spec, hardened
	DOCKER="$(DOCKER)" sh test/smoke/run.sh $(IMAGE)

test-tlc-check: ## Run the tlc-check acceptance tests in $(IMAGE), hardened
	TLC_CHECK_IMAGE=$(IMAGE) $(PYTHON) test/tlc-check/test_tlc_check.py -v
