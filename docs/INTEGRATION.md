# Consumer guide

This guide shows a project how to model-check its TLA+ specifications with
the tlaplus-toolchain image: on a workstation, in CI, and when it replaces a
toolchain of its own. It needs only Docker.

The [contract](SPECS.md) is the authoritative description of the behavior.
This guide shows how to use it. When the two disagree, the contract is right
and the guide has a bug.

> **Release.** This guide describes release `v0.1.0`, published as the image
> `ghcr.io/xiam/tlaplus-toolchain:0.1.0`. There is no `latest` tag.

## Contents

- [Quick start](#quick-start)
- [The hardened invocation](#the-hardened-invocation)
- [Mounts](#mounts)
- [Memory](#memory)
- [What to do for each exit status](#what-to-do-for-each-exit-status)
- [Security](#security)
- [The layout convention](#the-layout-convention)
- [CI examples](#ci-examples)
- [Migrate from a project-specific toolchain](#migrate-from-a-project-specific-toolchain)

## Quick start

Put each specification in `specs/` as `<Name>.tla` with a model `<Name>.cfg`.
The repository holds a small example in [examples/specs/](../examples/specs).
Copy it to try the commands of this guide:

```text
specs/
├── Counter.tla
├── Counter.cfg         checked by default
└── Counter.deep.cfg    checked only with --deep
```

From the directory that contains `specs/`, run:

```sh
docker run --rm \
  --network none --read-only --tmpfs /tmp:size=256m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --memory 2g --memory-swap 2g --cpus 2 --pids-limit 512 \
  -v "$PWD/specs:/specs:ro" \
  ghcr.io/xiam/tlaplus-toolchain:0.1.0 tlc-check /specs
```

The output, with some TLC progress lines left out (`[...]`):

```text
tlc-check: 1 model(s) in /specs
tlc-check: memory: container limit 2 GiB, scratch /tmp/tlc-check-tougduhg (tmpfs, counted 256 MiB), headroom 128 MiB, budget 1664 MiB = heap 1165 MiB + off-heap 416 MiB + GC reserve
tlc-check: workers 2, deadline 30m per model
=== tlc-check: Counter.cfg (Counter.tla) ===
TLC2 Version 2.19 of 08 August 2024 (rev: 5a47802)
[...]
Model checking completed. No error has been found.
[...]
11 states generated, 10 distinct states found, 0 states left on queue.
[...]
tlc-check: PASS Counter.cfg in 1s: 10 distinct states <= 100 (10 x expected-states 10)
tlc-check: summary:
  Counter.cfg: status 0: 10 distinct states <= 100 (10 x expected-states 10)
```

Exit status 0 means that every model passed. To check the deep models
instead, add `--deep` after `tlc-check`.

To see which tools the image holds:

```sh
docker run --rm ghcr.io/xiam/tlaplus-toolchain:0.1.0 tlc-check --version
```

```text
tlc-check 0.1.0
TLC v1.7.4 (revision 5a47802), tla2tools.jar sha256 936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88
JRE 21.0.13+9-LTS (Eclipse Adoptium)
```

`tlc-check --help` prints the options. The full list is in the
[contract](SPECS.md#options).

## The hardened invocation

The invocation of the quick start is the one supported way to run the image,
on a workstation and in CI. Change only the mount path and the limits.

| Flag | Why |
|---|---|
| `--rm` | Removes the container when it ends. |
| `--network none` | The spec gets no network; the image needs none at run time. |
| `--read-only` | The root filesystem of the container is read-only. |
| `--tmpfs /tmp:size=256m,mode=1777` | The only writable place: the scratch directory, in memory, with a size limit and writable by any UID. |
| `--cap-drop ALL` | The container gets no Linux capabilities. |
| `--security-opt no-new-privileges` | No process in the container can gain privileges, for example through a setuid binary. |
| `--user "$(id -u):$(id -g)"` | Runs as your own UID, so files written to a mounted `--out` directory belong to you. The image runs as any UID; never use UID 0 (root). |
| `--memory 2g --memory-swap 2g` | Limits the memory of the container to 2 GiB with no swap. `tlc-check` derives the JVM budget from this limit. |
| `--cpus 2` | Limits the container to 2 CPUs. `tlc-check` starts one TLC worker per CPU. |
| `--pids-limit 512` | Limits the number of processes and threads, so a spec cannot exhaust the process table. |
| `-v "$PWD/specs:/specs:ro"` | Mounts only the spec directory, read-only. |
| `ghcr.io/xiam/tlaplus-toolchain:0.1.0` | The image, pinned to a release. [Pin it by digest](#pin-the-image-by-digest) in CI. |
| `tlc-check /specs` | Checks every model in the mounted directory. |

## Mounts

### Mount only the spec directory, read-only, at any path

Mount the directory that holds the `.tla` and `.cfg` files, and pass the
same path to `tlc-check`. The path in the container is free. For a project
that keeps its specs in `test/`:

```sh
docker run --rm \
  --network none --read-only --tmpfs /tmp:size=256m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --memory 2g --memory-swap 2g --cpus 2 --pids-limit 512 \
  -v "$PWD/specs:/test:ro" \
  ghcr.io/xiam/tlaplus-toolchain:0.1.0 tlc-check /test
```

- Keep the mount read-only (`:ro`). `tlc-check` never writes into the spec
  directory.
- One invocation checks one directory. Subdirectories are not searched; a
  project with specs in several directories runs one invocation for each.
- Mount nothing else: never the repository root, a home directory or the
  Docker socket.

### Keep the logs and traces with `--out`

By default, `tlc-check` writes the TLC state files and one log per model to a
new directory under `/tmp`, which disappears with the container. The log of a
model holds its counterexample trace. To keep the logs, mount a writable
directory and pass it with `--out`:

```sh
mkdir -p tlc-out
docker run --rm \
  --network none --read-only --tmpfs /tmp:size=256m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --memory 2g --memory-swap 2g --cpus 2 --pids-limit 512 \
  -v "$PWD/specs:/specs:ro" \
  -v "$PWD/tlc-out:/out" \
  ghcr.io/xiam/tlaplus-toolchain:0.1.0 tlc-check --out /out /specs
ls tlc-out
```

```text
tlc-check: 1 model(s) in /specs
tlc-check: memory: container limit 2 GiB, scratch /out (ext4, counted 0), headroom 128 MiB, budget 1920 MiB = heap 1344 MiB + off-heap 480 MiB + GC reserve
[...]
tlc-check: summary:
  Counter.cfg: status 0: 10 distinct states <= 100 (10 x expected-states 10)
Counter.log
```

- Create the directory before the run, as your own user, so that the
  container UID can write to it.
- `--out` must not be the spec directory or lie inside it (exit status 2).
- A disk-backed `--out` also changes the memory budget: it does not count
  against the container limit. See [Memory](#memory).

When a model fails, its result line names the log. This is the output of a
model whose invariant is violated (exit status 1):

```text
Error: Invariant Small is violated.
Error: The behavior up to this point is:
State 1: <Initial predicate>
x = 0
[...]
State 6: <Next line 5, col 9 to line 5, col 25 of module Viol>
x = 5

6 states generated, 6 distinct states found, 0 states left on queue.
tlc-check: FAIL Viol.cfg in 1s: TLC exited 12; log: /out/Viol.log
```

## Memory

A model that is too large fails with a named model and exit status 3 or 4.
It does not crash the host. The rules are in the
[memory policy](SPECS.md#memory-policy); this section shows how to set the
limits.

### How `tlc-check` chooses the budget

`tlc-check` always gives the JVM an explicit budget `B`. It never lets the
JVM size itself from the host RAM. Docker counts the data in a `tmpfs`
against the memory limit of the container, so the budget leaves room for the
scratch directory:

```text
B = L − S − 128 MiB
```

- `L` is the container limit (`--memory`).
- `S` is the size of the scratch directory when it is a `tmpfs` (the
  `size=` of `--tmpfs /tmp`), and 0 when `--out` names a disk-backed
  directory.
- 128 MiB is the fixed headroom for JVM native memory and the `tlc-check`
  process.

`tlc-check` gives 70 % of `B` to the Java heap and 25 % to TLC's off-heap
fingerprint set, and keeps 5 % for the garbage collector. It prints the
result on its second line:

| Invocation | `L` | `S` | `B` |
|---|---|---|---|
| quick start | 2 GiB | 256 MiB | 1664 MiB |
| with a disk-backed `--out` | 2 GiB | 0 | 1920 MiB |

To give the models more memory, raise `--memory` and `--memory-swap`
together. Keep them equal, so that the container cannot swap.

### Why `/tmp` needs a size

A `tmpfs` without a size can grow until it takes the whole container limit,
and the JVM then has no memory left. In a memory-limited container,
`tlc-check` refuses to start with such a scratch directory. With
`--tmpfs /tmp:mode=1777` (no `size=`), the run ends at once with exit status
2:

```text
tlc-check: error: the scratch directory /tmp/tlc-check-133rqa4w is on a tmpfs without a size limit (/tmp), inside a container limited to 2 GiB; give the tmpfs a size, for example --tmpfs /tmp:size=256m,mode=1777, or pass --out with a disk-backed directory
```

### Set the budget explicitly with `--memory`

A project with a strict resource policy sets every resource option
explicitly:

```sh
docker run --rm \
  --network none --read-only --tmpfs /tmp:size=256m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --memory 2g --memory-swap 2g --cpus 2 --pids-limit 512 \
  -v "$PWD/specs:/specs:ro" \
  ghcr.io/xiam/tlaplus-toolchain:0.1.0 tlc-check --workers 1 --memory 1g --deadline 60m /specs
```

```text
tlc-check: 1 model(s) in /specs
tlc-check: memory: container limit 2 GiB, scratch /tmp/tlc-check-v3cc1zgd (tmpfs, counted 256 MiB), headroom 128 MiB, budget 1 GiB = heap 717 MiB + off-heap 256 MiB + GC reserve
tlc-check: workers 1, deadline 1h per model
[...]
```

`--memory` is the JVM budget `B`, not the container limit. A value that does
not fit, with the scratch size and the headroom, inside the container limit
is rejected before any model starts (exit status 2). `tlc-check` never
lowers it silently. With `--memory 2g` in a 2 GiB container:

```text
tlc-check: error: --memory 2 GiB does not fit: B + scratch + headroom = 2 GiB + 256 MiB + 128 MiB > container limit 2 GiB; the largest budget here is 1664 MiB
```

### Without a container limit

Without `--memory`, nothing protects the host. `tlc-check` then uses a
budget of 2 GiB and prints a warning:

```text
tlc-check: warning: the container has no memory limit, so nothing protects the host; run it with --memory and an equal --memory-swap
```

Always set `--memory` and an equal `--memory-swap`.

### Models that need a disk-backed scratch directory

TLC keeps its queue of unexplored states, and the fingerprints that do not
fit in memory, in the scratch directory. Some real models fill a 256 MiB
`tmpfs` scratch directory. This is a model of 9 million states in a 512 MiB
container with a 32 MiB `tmpfs`:

```text
Error: TLC threw an unexpected exception.
[...]
: java.io.IOException: No space left on device
5158937 states generated, 2581741 distinct states found, 2271 states left on queue.
tlc-check: FAIL Spill.cfg in 2s: scratch directory /tmp/tlc-check-onelt9l4 is full (tmpfs); use a larger scratch directory or a disk-backed --out
tlc-check: summary:
  Spill.cfg: status 4: scratch directory /tmp/tlc-check-onelt9l4 is full (tmpfs); use a larger scratch directory or a disk-backed --out
```

The remedy is a disk-backed scratch directory: mount a host directory and
pass it with `--out`, exactly as in
[Keep the logs and traces](#keep-the-logs-and-traces-with---out). It is
limited by the free disk space, not by memory, and it does not count against
the container limit (`S` = 0), so the JVM also gets a larger budget. The same
model, the same container, with `-v "$PWD/tlc-out:/out"` and `--out /out`:

```text
tlc-check: memory: container limit 512 MiB, scratch /out (ext4, counted 0), headroom 128 MiB, budget 384 MiB = heap 269 MiB + off-heap 96 MiB + GC reserve
[...]
Model checking completed. No error has been found.
[...]
18006001 states generated, 9006001 distinct states found, 0 states left on queue.
tlc-check: PASS Spill.cfg in 4s: 9006001 distinct states (no expected-states guard)
```

Keep the `--tmpfs /tmp:size=...` flag in this case too: the container still
needs a small writable `/tmp`.

### Scope of the no-OOM-kill guarantee

"Exit status 3 or 4, and no kernel OOM kill" holds when all of these are
true:

- the specs use TLC and its standard modules;
- the container follows the hardened invocation;
- the budget is the default, or a `--memory` that `tlc-check` accepts.

The guarantee rests on measurements with container limits from 512 MiB to
4 GiB and up to 12 workers. A run with many more workers, or a spec that
recurses very deeply, uses more of the headroom than was measured.

A spec that brings its own Java module overrides can allocate memory outside
this accounting. For such a spec the container limit is the only protection,
and the kernel can kill the container. The details and measurements are in
the [contract](SPECS.md#scope-of-the-guarantee).

## What to do for each exit status

`tlc-check` checks every model and then returns one status for the
directory. The summary lists the status of each model. When models end
differently, the first of 124, 4, 3, 1 wins.

| Status | Meaning | What to do |
|---|---|---|
| 0 | Every model passed. | Nothing. |
| 1 | A model failed: TLC found a violation or an error, the state-count guard tripped, or the guard marker is unreadable. | Read the model's log (see [`--out`](#keep-the-logs-and-traces-with---out)). For a guard trip, check why the model grew, then update the marker. |
| 2 | Usage error, before any model starts. | Read the `error:` line: a wrong option, a memory budget that does not fit, an unsized `tmpfs`, or a [layout problem](#the-layout-convention). |
| 3 | A model ran out of memory. | Use smaller constants in the `.cfg`; move the large model to a `.deep.cfg`; or raise `--memory` and `--memory-swap`. |
| 4 | The scratch directory is full. | Pass a [disk-backed `--out`](#models-that-need-a-disk-backed-scratch-directory), or give the `tmpfs` a larger size (it then counts against the limit). |
| 124 | A model reached its deadline. | Use smaller constants, move the model to a `.deep.cfg`, or raise `--deadline` (default `30m`). |

This is the output of a model that ran out of heap:

```text
Terminating due to java.lang.OutOfMemoryError: Java heap space
tlc-check: FAIL Hog.cfg in 1s: out of memory: Java heap exhausted (heap 90 MiB, off-heap 32 MiB); raise --memory and the container limit, or shrink the model
```

And of a model that reached its deadline (here `--deadline 1s`):

```text
tlc-check: FAIL Spill.cfg in 1s: deadline 1s reached; the JVM was stopped
```

## Security

### A spec directory is code

TLC loads Java module overrides (`.class` and `.jar` files) from the spec
directory, and a spec can drive long or unbounded computation. Checking a
spec from an untrusted source is running untrusted code. The
[threat model](SPECS.md#security-threat-model) has the details.

- **The container is the boundary.** Keep every flag of the hardened
  invocation. Together they give the spec no network, no writable filesystem
  except the scratch directory, no capabilities, no privilege escalation, a
  non-root user, and bounded memory, CPU and processes.
- **Pass no secrets.** Give the container no credential environment
  variables (`-e`, `--env-file`) and mount no tokens, SSH keys or cloud
  configuration.
- **Isolate untrusted contributions.** The image adds no protection beyond
  the container controls. A CI system that checks specs from untrusted
  contributors, for example pull requests from forks, runs the job on an
  isolated runner that holds no credentials. A job that can reach a Docker
  daemon can control that daemon's host: do not give such a job the Docker
  daemon of a runner that also runs trusted jobs.

### Pin the image by digest

A tag names a release, and a published tag is never moved. A digest also
proves that the bytes are the ones that were released. The digest of each
release is in its release notes. Pin it in CI:

```text
ghcr.io/xiam/tlaplus-toolchain:0.1.0@sha256:<digest from the release notes>
```

With a tag and a digest, Docker uses the digest and the tag documents the
version. To check the version of an image you have, read its labels:

```sh
docker image inspect --format '{{index .Config.Labels "io.github.xiam.tlaplus-toolchain.tlc.version"}} {{index .Config.Labels "io.github.xiam.tlaplus-toolchain.jre.version"}}' ghcr.io/xiam/tlaplus-toolchain:0.1.0
```

```text
1.7.4 21.0.13+9
```

## The layout convention

- Specs live in `specs/`. Any other directory works too; pass its path.
- A model is a file `<Name>.cfg`, checked against `<Name>.tla` in the same
  directory. Other modules (for example a module that only holds operators
  and that a spec `EXTENDS`) sit next to them without a `.cfg`.
- A deep model is a file `<Name>.deep.cfg`. `tlc-check --deep` checks the
  deep models, and only those. Use it for long runs with larger constants,
  for example in a nightly job.
- Every `.cfg` must have its `<Name>.tla`. A model without its spec, or a
  directory without a model, is a usage error (exit status 2).

### The `expected-states` marker

A model can declare how many distinct states it expects, in a comment line
of its `.cfg` file:

```text
\* expected-states: 10
```

The model fails (exit status 1) when TLC finds more than 10 times that
number, even if TLC finds no error. The guard catches a model that has grown
far beyond its intended size, before it becomes a slow CI job. Set `N` to
the count that TLC reports today ("... distinct states found"), and update
it when the model changes on purpose. A marker that is malformed, not a
positive integer, or given twice with different values fails the model.
A model without a marker has no guard; the result line says so.

## CI examples

The two jobs below are **examples**, not maintained templates: copy one and
adapt it. Both run the hardened invocation; the text before each job names
what it changes. Both pin a tag; add the digest
([Pin the image by digest](#pin-the-image-by-digest)).

### GitHub Actions

[examples/github-actions.yml](../examples/github-actions.yml). The runner
mounts the checkout directly. On failure, the job keeps the logs as an
artifact; the change from the hardened invocation is the writable `--out`
mount.

```yaml
# Example only: a GitHub Actions workflow that model-checks the specs in
# specs/ with the hardened invocation. Copy it to .github/workflows/tla.yml
# and adapt it; it is an illustration, not a maintained template.
# Guide: docs/INTEGRATION.md in the tlaplus-toolchain repository.
name: tla

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  tlc-check:
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    env:
      # Pin by digest: append @sha256:<digest> from the release notes.
      TLAPLUS_IMAGE: ghcr.io/xiam/tlaplus-toolchain:0.1.0
      SPEC_DIR: specs
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - name: Model-check the specs
        run: |
          mkdir -p "$RUNNER_TEMP/tlc-out"
          docker run --rm \
            --network none --read-only --tmpfs /tmp:size=256m,mode=1777 \
            --cap-drop ALL --security-opt no-new-privileges \
            --user "$(id -u):$(id -g)" \
            --memory 2g --memory-swap 2g --cpus 2 --pids-limit 512 \
            -v "$PWD/$SPEC_DIR:/specs:ro" \
            -v "$RUNNER_TEMP/tlc-out:/out" \
            "$TLAPLUS_IMAGE" tlc-check --out /out /specs
      - name: Keep the TLC logs and traces
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: tlc-logs
          path: ${{ runner.temp }}/tlc-out/*.log
```

### GitLab CI

[examples/gitlab-ci.yml](../examples/gitlab-ci.yml). The job talks to a
Docker daemon that may not see the job's files, for example a `docker:dind`
service, so a bind mount of the checkout would be empty. The job copies the
specs into a Docker volume and mounts that volume read-only instead. The job
container runs as root, so the job passes the image's non-root user
(`--user 10001:10001`) instead of `$(id -u)`.

```yaml
# Example only: a GitLab CI job that model-checks the specs in specs/ with
# the hardened invocation. Copy it into .gitlab-ci.yml and adapt it; it is an
# illustration, not a maintained template.
# Guide: docs/INTEGRATION.md in the tlaplus-toolchain repository.
#
# The job needs a Docker daemon: a runner with a `docker:dind` service, or a
# runner that gives jobs a Docker socket. The daemon may not see the job's
# files, so the specs reach the container through a Docker volume instead of
# a bind mount. The volume is mounted read-only, as the spec directory must be.

tlc-check:
  image: docker:29.1.3-cli
  variables:
    # Pin by digest: append @sha256:<digest> from the release notes.
    TLAPLUS_IMAGE: ghcr.io/xiam/tlaplus-toolchain:0.1.0
    SPEC_DIR: specs
    SPEC_VOLUME: tlc-specs-$CI_JOB_ID
    SPEC_LOADER: tlc-loader-$CI_JOB_ID
  script:
    - docker volume create "$SPEC_VOLUME"
    - docker create --name "$SPEC_LOADER" --network none -v "$SPEC_VOLUME:/specs" "$TLAPLUS_IMAGE" true
    - docker cp "$SPEC_DIR/." "$SPEC_LOADER:/specs"
    - docker rm "$SPEC_LOADER"
    - >-
      docker run --rm
      --network none --read-only --tmpfs /tmp:size=256m,mode=1777
      --cap-drop ALL --security-opt no-new-privileges
      --user 10001:10001
      --memory 2g --memory-swap 2g --cpus 2 --pids-limit 512
      -v "$SPEC_VOLUME:/specs:ro"
      "$TLAPLUS_IMAGE" tlc-check /specs
  after_script:
    - docker rm -f "tlc-loader-$CI_JOB_ID" || true
    - docker volume rm -f "tlc-specs-$CI_JOB_ID"
```

A job that runs directly in the image (`image:` set to the toolchain image,
`script: tlc-check specs`) also works, but then the runner, not the job,
decides the network, the filesystem, the user and the limits. Use it only
when the runner applies the same controls as the hardened invocation.

## Migrate from a project-specific toolchain

This recipe replaces a per-project install script (for example
`tools/tla/install.sh` that downloads `tla2tools.jar`) or a project-specific
TLA+ `Dockerfile` with this image.

1. **Record the old results.** Run the old toolchain once and note, for each
   model, the TLC version, the "distinct states found" count and the run
   time. Note the JVM options (`-Xmx`, `-Xss`, ...), the TLC options
   (`-workers`, `-deadlock`, ...) and the timeout.
2. **Arrange the layout.** Every model needs a `<Name>.cfg` next to a
   `<Name>.tla` (see [The layout convention](#the-layout-convention)).
   - *Several configs for one spec* (for example `Counter.tla` with
     `CounterSmall.cfg` and `CounterLarge.cfg`) are rejected with exit
     status 2:

     ```text
     tlc-check: error: model without its spec: CounterLarge.cfg (no CounterLarge.tla), CounterSmall.cfg (no CounterSmall.tla)
     ```

     Give each variant a wrapper module, `CounterSmall.tla`, that extends
     the spec. The config then refers to the spec's definitions as before:

     ```text
     ---- MODULE CounterSmall ----
     EXTENDS Counter
     ====
     ```

     Or, when there are exactly two configs and one is the long run, rename
     them to `Counter.cfg` and `Counter.deep.cfg`.
   - *Specs in several directories*: run one invocation per directory.
3. **Move options into the model.** `tlc-check` passes no TLC option other
   than the workers. Move a model option into its `.cfg` file, for example
   `-deadlock` becomes the line `CHECK_DEADLOCK FALSE`. Map the resource
   options to `tlc-check` options: `-workers N` to `--workers N`, the
   timeout to `--deadline`, and `-Xmx` to a container limit (`--memory`
   with an equal `--memory-swap`). `-Xmx` is about 70 % of the budget, so a
   limit of `-Xmx / 0.7` plus the scratch size plus 128 MiB gives the old heap.
4. **Add the guards.** Add `\* expected-states: N` to each `.cfg`, with the
   count from step 1.
5. **Run the hardened invocation** locally, as in the
   [quick start](#quick-start). Compare each "distinct states found" count
   with step 1. On the same TLC version the counts are the same. A model
   that ends with status 4 needs a
   [disk-backed `--out`](#models-that-need-a-disk-backed-scratch-directory).
6. **Check for newer-TLC features.** The image ships TLC v1.7.4, the last
   stable release. A spec written for a newer TLC (for example the v1.8.0
   pre-release) can fail on v1.7.4. It then fails before any state is
   explored, with status 1 and a parse or semantic error, typically
   `Unknown operator` for an operator that v1.7.4 does not have:

   ```text
   Semantic errors:

   *** Errors: 1

   line 6, col 7 to line 6, col 20 of module Newer

   Unknown operator: `FutureOperator'.

   Error: Parsing or semantic analysis failed.
   tlc-check: FAIL Newer.cfg in 0s: TLC exited 150; log: /tmp/tlc-check-ub3fqd7p/Newer.log
   ```

   If the same spec passes on the newer TLC, rewrite the construct for
   v1.7.4. If you cannot, open an issue in this project and name the
   feature: a newer TLC is added only when a project needs it.
7. **Replace the CI job** with one of the [CI examples](#ci-examples), and
   pin the image by digest.
8. **Delete the old toolchain:** the install script, the TLA+ `Dockerfile`,
   the jar checksum, any cached `tla2tools.jar` and the run loop that called
   TLC.
