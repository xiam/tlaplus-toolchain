#!/bin/sh
# Negative test: the image build fails when the jar SHA256 pin is wrong.
#
#   test/smoke/bad-checksum.sh
#
# Builds only the download stage of the Dockerfile with a wrong TLC_SHA256
# (every other pin from pins.env) and asserts that the build fails with the
# checksum-mismatch message. Nothing is tagged or loaded.
#
# Exit status: 0 the build failed as expected, 1 otherwise.
set -eu

here=$(cd "$(dirname "$0")" && pwd -P)
root=$(cd "$here/../.." && pwd -P)
docker=${DOCKER:-docker}

# shellcheck source=../../pins.env
. "$root/pins.env"

wrong=0000000000000000000000000000000000000000000000000000000000000000
out=$(mktemp)
trap 'rm -f "$out"' EXIT

status=0
$docker buildx build \
    --progress=plain \
    --target tla2tools \
    --output type=cacheonly \
    --build-arg BASE_IMAGE="$BASE_IMAGE" \
    --build-arg BASE_DIGEST="$BASE_DIGEST" \
    --build-arg TLC_VERSION="$TLC_VERSION" \
    --build-arg TLC_SHA256="$wrong" \
    "$root" >"$out" 2>&1 || status=$?

if [ "$status" -eq 0 ]; then
    cat "$out" >&2
    echo "FAIL: the build succeeded with a wrong TLC_SHA256" >&2
    exit 1
fi
# Match only what the RUN step printed, not the command text that BuildKit
# echoes (it contains the same message). Plain progress output prefixes a
# process line with "#<step> <seconds> ". The build must have downloaded the
# real jar (its actual digest equals the correct pin) and failed only on the
# comparison: a download error must not pass this test.
step_output='^#[0-9][0-9]* [0-9][0-9]*\.[0-9][0-9]* '
if ! grep -Eq "${step_output}SHA256 mismatch for tla2tools\.jar v${TLC_VERSION}\$" "$out" ||
   ! grep -Eq "${step_output}  actual:   ${TLC_SHA256}\$" "$out"; then
    cat "$out" >&2
    echo "FAIL: the build failed (status $status), but not on the checksum of the downloaded jar" >&2
    exit 1
fi
grep -E "${step_output}(SHA256 mismatch|  expected:|  actual:)" "$out" | sed 's/^/    /'
echo "ok: the build fails when TLC_SHA256 is wrong (status $status)"
