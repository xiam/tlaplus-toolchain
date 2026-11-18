#!/bin/sh
# Smoke test of the toolchain image.
#
#   test/smoke/run.sh IMAGE
#
# 1. `docker inspect`: the default user is not root, and the pin labels match
#    pins.env.
# 2. TLC model-checks test/smoke/Smoke.tla inside the image, with the
#    hardened run flags: no network, read-only root filesystem, a sized tmpfs
#    scratch, no capabilities, an arbitrary UID and a read-only spec mount.
#    The test asserts the exact distinct-state count.
#
# The spec directory reaches the container through a Docker volume mounted
# read-only, not a bind mount, so the test also works when the Docker daemon
# runs elsewhere (for example a Docker-in-Docker CI service).
#
# Exit status: 0 pass, 1 fail, 2 usage error.
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 IMAGE" >&2
    exit 2
fi
image=$1
here=$(cd "$(dirname "$0")" && pwd -P)
root=$(cd "$here/../.." && pwd -P)
docker=${DOCKER:-docker}

# shellcheck source=../../pins.env
. "$root/pins.env"

expected_states=16
run_user=12345:12345

failures=0
fail() {
    echo "FAIL: $*" >&2
    failures=$((failures + 1))
}
pass() {
    echo "ok: $*"
}

# --- 1. Image metadata --------------------------------------------------------

user=$($docker image inspect --format '{{.Config.User}}' "$image")
uid=${user%%:*}
case "$uid" in
    "" | 0 | root) fail "default user is root (Config.User='$user')" ;;
    *) pass "default user is not root ($user)" ;;
esac

label() {
    $docker image inspect --format "{{index .Config.Labels \"$1\"}}" "$image"
}
check_label() {
    actual=$(label "$1")
    if [ "$actual" = "$2" ]; then
        pass "label $1=$actual"
    else
        fail "label $1: expected '$2', got '$actual'"
    fi
}
check_label io.github.xiam.tlaplus-toolchain.tlc.version "$TLC_VERSION"
check_label io.github.xiam.tlaplus-toolchain.tlc.sha256 "$TLC_SHA256"
check_label org.opencontainers.image.base.digest "$BASE_DIGEST"
check_label io.github.xiam.tlaplus-toolchain.jre.version "$JRE_VERSION"

# --- 2. Hardened TLC run ------------------------------------------------------

# Unique per run: the Docker daemon may be shared with concurrent runs.
volume=tlaplus-smoke-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
loader=
out=$(mktemp)
cleanup() {
    if [ -n "$loader" ]; then $docker rm -f "$loader" >/dev/null 2>&1 || true; fi
    $docker volume rm -f "$volume" >/dev/null 2>&1 || true
    rm -f "$out"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

$docker volume create "$volume" >/dev/null
loader=$($docker create --network none -v "$volume:/specs" "$image" true)
$docker cp "$here/Smoke.tla" "$loader:/specs/Smoke.tla" >/dev/null
$docker cp "$here/Smoke.cfg" "$loader:/specs/Smoke.cfg" >/dev/null
$docker rm "$loader" >/dev/null
loader=

# Exactly the documented guarantees: nothing may be written outside /tmp, and
# no network is available. The JVM gets an explicit small heap.
status=0
$docker run --rm \
    --network none --read-only --tmpfs /tmp:size=64m,mode=1777 \
    --cap-drop ALL --security-opt no-new-privileges \
    --user "$run_user" \
    --memory 1g --memory-swap 1g --pids-limit 256 \
    -v "$volume:/specs:ro" \
    "$image" \
    sh -c 'set -eu
        echo "jar-sha256: $(sha256sum "$TLA2TOOLS_JAR" | cut -d" " -f1)"
        java -XX:+UseSerialGC -Xmx256m -XX:+ExitOnOutOfMemoryError \
            -cp "$TLA2TOOLS_JAR" tlc2.TLC \
            -workers 1 -metadir /tmp/states \
            -config /specs/Smoke.cfg /specs/Smoke.tla' \
    >"$out" 2>&1 || status=$?

if [ "$status" -ne 0 ]; then
    cat "$out" >&2
    fail "TLC run exited with status $status"
else
    pass "TLC run exited 0 (user $run_user, --network none, --read-only, read-only spec mount)"
fi

if grep -qx "jar-sha256: $TLC_SHA256" "$out"; then
    pass "jar in the image matches TLC_SHA256"
else
    fail "jar in the image does not match TLC_SHA256"
fi

if grep -q '^Model checking completed\. No error has been found\.' "$out"; then
    pass "TLC found no error"
else
    fail "TLC did not report 'No error has been found'"
fi

# TLC prints: "<G> states generated, <D> distinct states found, <Q> states left on queue."
found=$(sed -n 's/^[0-9][0-9]* states generated, \([0-9][0-9]*\) distinct states found, 0 states left on queue\.$/\1/p' "$out" | tail -n 1)
if [ "$found" = "$expected_states" ]; then
    pass "TLC found exactly $expected_states distinct states"
else
    sed -n '/distinct states/p' "$out" >&2
    fail "expected $expected_states distinct states, found '${found:-none}'"
fi

if [ "$failures" -ne 0 ]; then
    echo "smoke: $failures check(s) failed" >&2
    exit 1
fi
echo "smoke: all checks passed"
