# Design decisions

Each entry records a decision, its date and its reason. A change to a decision
adds a new entry that supersedes the old one; entries are not rewritten.

The [contract](../SPECS.md) states the resulting behavior.

| # | Decision | Date | Status |
|---|---|---|---|
| [D1](#d1-standalone-project-dependencies-run-one-way) | Standalone project; dependencies run one way | 2026-11-17 | Accepted |
| [D2](#d2-tlc-pin-v174-only) | TLC pin: v1.7.4 only | 2026-11-17 | Accepted |
| [D3](#d3-distribution-public-github-repository-and-ghcrio) | Distribution: public GitHub repository and `ghcr.io` | 2026-11-17 | Accepted |
| [D4](#d4-v1-scope-the-image-and-one-tlc-runner-command) | v1 scope: the image and one TLC runner command | 2026-11-17 | Accepted |
| [D5](#d5-license-mit) | License: MIT | 2026-11-17 | Accepted |
| [D6](#d6-public-name) | Public name | 2026-11-17 | Accepted |
| [D7](#d7-the-run-contract-is-a-requirement) | The run contract is a requirement | 2026-11-17 | Accepted |
| [D8](#d8-tlc-check-memory-split-headroom-and-default-deadline) | `tlc-check` memory split, headroom and default deadline | 2026-11-17 | Accepted |
| [D9](#d9-release-build-test-and-push-the-same-bytes-per-platform) | Release: build, test and push the same bytes per platform | 2026-11-17 | Accepted |

D1 to D7 were decided by the project owner (xiam) on 2026-11-17. D8 is the
measured implementation of D7's memory policy.

## D1. Standalone project; dependencies run one way

**Decision.** This repository defines the image and the standard way to use
it. It depends on no consumer's repository, CI template or CI runner.
Consumers depend on the published image, never the reverse.

**Reason.** Projects that model-check TLA+ specs each carried their own
toolchain: different JRE bases, different TLC versions, and a re-implemented
jar pin, checksum and run loop in each. One standalone image removes the
copies. When two designs are both reasonable, the project chooses the one
that a stranger can use unchanged.

## D2. TLC pin: v1.7.4 only

**Decision.** The image ships `tla2tools.jar` v1.7.4, the last stable
release, verified by SHA256
(`936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`).

**Reason.** v1.8.0 is a rolling pre-release: upstream re-publishes it, so its
bytes change and it cannot be pinned by checksum. A dated v1.8.0 snapshot
track is added only when a consumer shows that it needs a v1.8.0 feature.

## D3. Distribution: public GitHub repository and `ghcr.io`

**Decision.** The source is public on GitHub and the image is published to
`ghcr.io`.

**Reason.** Anyone can pull the image anonymously from any CI system or
workstation, with no registry credentials.

## D4. v1 scope: the image and one TLC runner command

**Decision.** Version 1 is the image and `tlc-check`. Checks of drift between
specs and prose, back-references and model coverage are deferred.

**Reason.** Those checks exist in one project today. They join this project
only when they are shown to generalize to a second consumer.

## D5. License: MIT

**Decision.** The project is licensed under the [MIT License](../../LICENSE).

**Reason.** A permissive license lets any project, open or closed, use the
image and copy the invocation.

## D6. Public name

**Decision.** The repository is `xiam/tlaplus-toolchain` on GitHub and the
image is `ghcr.io/xiam/tlaplus-toolchain`.

**Reason.** "toolchain" rather than "tlc" leaves room for other TLA+ tools
(for example Apalache or TLAPS) without a rename; there is no work on them
now.

## D7. The run contract is a requirement

**Decision.** The run contract in [SPECS.md](../SPECS.md#the-run-contract)
(read-only mounts, the memory policy, the hardened invocation and the threat
model) is a requirement, not a recommendation.

**Reason.** A spec directory is code. A model that is too large must fail
with a clear exit status and must not crash the host, and checking a spec
must not expose credentials or the host filesystem.

## D8. `tlc-check` memory split, headroom and default deadline

**Decision.** `tlc-check` splits the JVM budget `B` into 70 % heap, 25 %
off-heap fingerprint memory (TLC's `OffHeapDiskFPSet`) and a 5 % reserve for
garbage-collector structures. It keeps a fixed headroom of 128 MiB outside
`B`. The default deadline is 30 minutes per model. The exit status for mixed
results is the first of 124, 4, 3, 1.

**Reason.** TLC v1.7.4 keeps fingerprints on the heap by default, so a heap
limit alone does not separate them from other heap use; the off-heap set gets
a fixed share and was 15 times faster on a 16-million-state model. The 25 %
share is TLC's own default fingerprint fraction. The headroom and the reserve
cover the measured worst case (72 to 98 MiB of native, process and kernel
memory, with the whole heap resident) with a margin of at least 74 MiB. The
measurements and the deadline evidence are in
[SPECS.md](../SPECS.md#measurements).

## D9. Release: build, test and push the same bytes per platform

**Decision.** The release workflow builds each platform natively, on a
`linux/amd64` and a `linux/arm64` runner. One build per platform produces two
outputs: the image loaded locally, which `make test` checks, and the same
image pushed by digest only, with no tag. Only after both platforms pass does
one step create the single tag `X.Y.Z` over the two tested digests. The
workflow asserts the tag set (every tag `X.Y.Z`) and the platform list, and
uses only the built-in `GITHUB_TOKEN`. The only third-party action is
`actions/checkout`, pinned by commit SHA; the build uses the Docker CLI and the
pinned BuildKit image of the `Makefile`.

**Reason.** A rebuild after the tests could produce different bytes than the
ones tested. Native runners test each platform at full speed, including the
memory-limit tests, which emulation would distort. Tagging last means that a
failed release leaves no tag that consumers can pull, so a failure is either
re-run or superseded by a patch release, and a published tag is never moved.

