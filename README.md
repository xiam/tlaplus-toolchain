# tlaplus-toolchain

A pinned container image and one command, `tlc-check`, to model-check TLA+
specifications the same way on any CI system or workstation.

- **One pinned toolchain.** Eclipse Temurin JRE 21 (pinned by digest) and
  `tla2tools.jar` v1.7.4 (verified by SHA256). No project builds its own image
  or re-implements the jar pin.
- **One command.** `tlc-check [DIR]` checks every `<Name>.cfg` in a directory
  against `<Name>.tla` and returns one exit status.
- **Safe by default.** The spec directory is mounted read-only, the JVM always
  gets an explicit memory budget, and a model that is too large fails with a
  clear exit status instead of crashing the host (see the
  [scope of this guarantee](docs/SPECS.md#scope-of-the-guarantee)).

> **Status.** Pre-release. The image is not published yet; the first release
> is `v0.1.0`, published as `ghcr.io/xiam/tlaplus-toolchain:0.1.0`. There is no
> `latest` tag.

## Quick start

From a project whose specs live in `specs/`:

```sh
docker run --rm \
  --network none --read-only --tmpfs /tmp:size=256m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --memory 2g --memory-swap 2g --cpus 2 --pids-limit 512 \
  -v "$PWD/specs:/specs:ro" \
  ghcr.io/xiam/tlaplus-toolchain:<tag> tlc-check /specs
```

Change only the mount path and the limits. Exit status 0 means every model
passed; the other statuses are listed in the
[contract](docs/SPECS.md#exit-status). The [consumer guide](docs/INTEGRATION.md)
explains each flag, the memory limits and the CI setup.

A spec directory is code, not data: TLC can load Java classes from it. Read
the [threat model](docs/SPECS.md#security-threat-model) before you check specs
from an untrusted source.

## Documentation

- [docs/INTEGRATION.md](docs/INTEGRATION.md): the consumer guide. The
  hardened invocation flag by flag, mounts, memory limits and exit statuses,
  security, CI examples, and how to migrate from a project-specific TLA+
  toolchain. Start here to adopt the image.
- [docs/SPECS.md](docs/SPECS.md): the contract. Image contents and pins,
  `tlc-check` interface and exit statuses, mounts, memory policy, threat model
  and versioning.
- [docs/RELEASE.md](docs/RELEASE.md): how a release is built, tested,
  published and verified, and what happens when one goes wrong.
- [docs/design/](docs/design/README.md): the design decisions and their
  reasons.
- [docs/](docs/README.md): the documentation index.

## Development

`make lint` checks that the Markdown links in the repository resolve. It needs
`python3` and `git`.

`make build` builds the image locally as `tlaplus-toolchain:dev` from the pins
in `pins.env` ([docs/PINS.md](docs/PINS.md)). `make test` then checks it: the
build fails on a wrong jar checksum, and TLC model-checks a smoke spec inside
the image with the hardened run flags. `make build-platforms` builds for
`linux/amd64` and `linux/arm64` without loading the result. It uses a
temporary BuildKit container builder, whose bundled QEMU emulates the foreign
platform. They need Docker with buildx.

`make test` also runs the `tlc-check` acceptance tests (`test/tlc-check/`).
They start one hardened container per case, including 512 MiB containers that
exhaust the heap and the scratch directory on purpose. They need `docker` and
`python3`.

`python3 test/examples/check.py` checks that the
[consumer guide](docs/INTEGRATION.md) shows the CI examples in `examples/`
verbatim and that they parse as YAML. It needs PyYAML.

`scripts/release.py` holds the checks of the release workflow (tag form,
image tags, platforms, release notes); see [docs/RELEASE.md](docs/RELEASE.md).

## License

[MIT](LICENSE).
