# Pins

The image is built from pinned inputs only. [`pins.env`](../pins.env) is the
only file that holds the pins; `make build` passes them to the
[`Dockerfile`](../Dockerfile) as build arguments, and the image labels report
them (see [The image](SPECS.md#the-image)).

| Key | Meaning |
|---|---|
| `BASE_IMAGE` | The base image repository: Eclipse Temurin. |
| `BASE_TAG` | The tag that `BASE_DIGEST` was resolved from. Informational. |
| `BASE_DIGEST` | The digest of the base image's multi-platform index. The build uses it. |
| `JRE_VERSION` | The Temurin JRE version inside that digest. Informational. |
| `TLC_VERSION` | The upstream TLA+ tools release, without the `v`. |
| `TLC_SHA256` | The SHA256 of that release's `tla2tools.jar`. The build fails on a mismatch. |

A pin changes only through the procedures below, in a change of its own that
also passes `make build test`.

## Update the TLC pin

1. **Choose a stable release.** Use a tag from
   <https://github.com/tlaplus/tlaplus/releases> that is **not** marked as a
   pre-release. Never use `v1.8.0`: it is a rolling pre-release, upstream
   re-publishes it, and its bytes change, so no checksum can pin it.
2. **Download the jar twice, independently.** Use two different machines or
   networks, at different times:

   ```sh
   curl -fsSLo tla2tools.jar \
     https://github.com/tlaplus/tlaplus/releases/download/vX.Y.Z/tla2tools.jar
   sha256sum tla2tools.jar
   ```

   The two digests must be identical. If they differ, stop: the asset is not
   stable.
3. **Verify the jar.** Its manifest names the TLC entry point and the release
   tag, and it contains the TLC, PlusCal and SANY classes:

   ```sh
   unzip -p tla2tools.jar META-INF/MANIFEST.MF   # must contain: Main-class: tlc2.TLC
                                                 # and X-Git-Tag: vX.Y.Z
   unzip -l tla2tools.jar | grep -cE ' (tlc2|pcal|tla2sany)/'   # must not be 0
   ```

4. **Update `pins.env`.** Set `TLC_VERSION` (without the `v`) and
   `TLC_SHA256`.
5. **Build and test.** Run `make build test`. A wrong checksum fails the
   build with `SHA256 mismatch for tla2tools.jar`.
6. **Record the change.** A new TLC version changes the
   [contract](SPECS.md#the-image) and needs a new
   [design decision](design/README.md), because the current decision pins
   v1.7.4.

## Update the base image

1. **Resolve the digest of the multi-platform index** of the Temurin JRE 21
   tag, not the digest of one platform's manifest:

   ```sh
   docker buildx imagetools inspect docker.io/library/eclipse-temurin:21-jre-noble
   ```

   Take the top-level `Digest:` line. Check that the index lists
   `linux/amd64` and `linux/arm64`.
2. **Read the JRE version** from that digest:

   ```sh
   docker run --rm docker.io/library/eclipse-temurin@sha256:<digest> java -version
   ```

3. **Update `pins.env`.** Set `BASE_DIGEST`, `JRE_VERSION` (for example
   `21.0.13+9`) and, when the tag changed, `BASE_TAG`.
4. **Build and test** for every platform:

   ```sh
   make build test
   make build-platforms
   ```

A change of the JRE major version (21) changes the contract and needs a new
design decision.
