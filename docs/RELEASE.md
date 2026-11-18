# Releases

A release is a Git tag `vX.Y.Z`. It publishes exactly one image tag,
`ghcr.io/xiam/tlaplus-toolchain:X.Y.Z` (the release tag without its `v`), for
`linux/amd64` and `linux/arm64`. The rules are in the
[contract](SPECS.md#versioning): there is no `latest` tag, and a published tag
is never moved.

This repository is published as history-free snapshots. A maintainer cuts the
release tag; the snapshot and its public tag follow, and the public tag starts
the release workflow.

## What a release does

1. **A maintainer runs the release-candidate gate** (below) on the exact commit
   to be tagged. The tag is cut only after the gate passes.
2. **The release tag is created** as an annotated tag `vX.Y.Z` on that commit.
   Its message is the release headline, a short summary and the release notes.
3. **The snapshot is published** to this repository with the same tag.
4. **The release workflow runs** on the tag
   ([`.github/workflows/release.yml`](../.github/workflows/release.yml)):
   - `prepare` maps `vX.Y.Z` to `X.Y.Z` and rejects any other tag form. It
     fails early when `X.Y.Z` already exists in the registry.
   - `build-amd64` and `build-arm64` build the image natively on each
     platform. One build both loads the image locally and pushes it **by digest
     only** (no tag), so `make test` checks exactly the bytes that are pushed.
   - `publish` first requires the registry to prove that `X.Y.Z` does not
     exist (a readable tag list without it and a 404 for the tag); any other
     answer stops the release. It then tags the two tested digests once, as
     `X.Y.Z`, and asserts
     that the tag exists, that every tag of the image has the form `X.Y.Z`
     (so no `latest` and no `v`-prefixed tag), and that the index lists exactly
     `linux/amd64` and `linux/arm64`. It writes the index digest into the
     release notes.
   - The only credential is the workflow's built-in `GITHUB_TOKEN` with
     `packages: write`. No long-lived token exists for the push.
5. **The release is verified** as a consumer sees it
   ([`.github/workflows/verify.yml`](../.github/workflows/verify.yml), run by
   hand with the release tag): an anonymous pull, the platform list, the digest
   against the release notes, the hardened invocation of
   [SPECS.md](SPECS.md#the-run-contract) on `examples/specs`, and the GitHub
   Actions example of the [consumer guide](INTEGRATION.md#github-actions),
   unchanged.

On the first release, the package is private until a maintainer sets its
visibility to public. The verification runs after that.

## The release-candidate gate

Mandatory before every release tag. Run it on the exact commit to be tagged,
on a machine with Docker and buildx:

1. Build and test:

   ```sh
   make lint
   make build
   make build-platforms
   make test
   python3 test/examples/check.py
   ```

2. Run the `linux/arm64` image at least once (natively, or under emulation)
   on `test/smoke` and check the expected state count. If the host cannot run
   it, record why.
3. Run the candidate image with the hardened invocation, read-only and one
   container at a time, against real consumer spec directories. Record for each
   directory the models, the result, the exit status and the state counts.
4. Tag the candidate locally as `ghcr.io/xiam/tlaplus-toolchain:X.Y.Z` (never
   push it) and run every command block of the
   [consumer guide](INTEGRATION.md) as written.
5. Keep the evidence with the release.

A failure stops the release. Fix it in a new commit and run the gate again on
that commit.

## When something goes wrong

- **The release workflow fails before `publish` tags the image.** Nothing
  consumers can pull exists yet (the pushed digests carry no tag). Fix a
  transient cause and re-run the failed jobs; the workflow re-checks that
  `X.Y.Z` is still absent. A defect in the code or the image ships in a new
  patch release.
- **A published release is defective.** It is superseded by a new patch
  release `vX.Y.(Z+1)` through the same procedure. The defective tag and image
  stay as they are: a published tag is never moved, deleted or re-pointed.

## Tag message

The annotated tag message has three parts. The headline line is
`vX.Y.Z: <what changed>`, at most 72 bytes. The summary is one paragraph of
2–4 sentences, at most 600 bytes. Then come the release notes, as a
`## vX.Y.Z - YYYY-MM-DD` section. Create it with `--cleanup=verbatim` so the
Markdown headings stay in the message.
