#!/usr/bin/env python3
"""Release checks for the tlaplus-toolchain image.

The release workflow (.github/workflows/release.yml) calls these commands; they
also run against any OCI registry, for example a local `registry:2` for a dry
rehearsal. See docs/RELEASE.md.

    release.py version TAG
        Print the image tag X.Y.Z for the release tag vX.Y.Z. Any other form
        is a usage error.
    release.py assert-absent IMAGE VERSION [--allow-unreadable]
        Pass only when the registry proves that IMAGE:VERSION does not exist:
        the tag list is readable and lacks VERSION, and the manifest lookup
        returns 404. Fail (1) when it exists; a published tag is never moved.
        Any other registry answer is an error (2). With --allow-unreadable, a
        repository that the registry refuses to read (it does not exist yet,
        before the first release) passes; use it only for an early check, never
        for the check right before tagging.
    release.py assert-tags IMAGE VERSION
        Fail unless IMAGE has the tag VERSION and every tag of IMAGE has the
        form X.Y.Z: no `latest`, no `v`-prefixed tag, no other tag.
    release.py assert-platforms IMAGE VERSION PLATFORM...
        Fail unless IMAGE:VERSION is an index whose image manifests are
        exactly the given platforms (attestation manifests are ignored).
        Print the index digest.
    release.py notes IMAGE VERSION DIGEST PLATFORM...
        Print the release notes (Markdown) for the published image.

IMAGE is `host/name`, for example `ghcr.io/xiam/tlaplus-toolchain`. The
registry is reached over HTTPS, except `localhost` and `127.0.0.1`, which use
HTTP. Credentials, when needed, come from REGISTRY_USER and REGISTRY_TOKEN;
without them the registry is read anonymously.

Exit status: 0 the check passed, 1 the check failed, 2 usage or registry error.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

RELEASE_TAG_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
IMAGE_TAG_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
MANIFEST_TYPES = INDEX_TYPES + (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)


class UsageError(Exception):
    pass


class CheckFailed(Exception):
    pass


class NotReadable(UsageError):
    """The registry refused to read the repository (it may not exist yet)."""


def release_version(tag: str) -> str:
    m = RELEASE_TAG_RE.match(tag)
    if not m:
        raise UsageError(f"release tag {tag!r} is not of the form vX.Y.Z")
    return tag[1:]


class Registry:
    def __init__(self, image: str):
        host, sep, name = image.partition("/")
        if not sep or not name or ":" in name or "@" in name:
            raise UsageError(f"image {image!r} is not of the form host/name")
        self.host, self.name = host, name
        local = host.split(":")[0] in ("localhost", "127.0.0.1")
        self.base = f"{'http' if local else 'https'}://{host}/v2/{name}"
        self.auth_header: str | None = None

    def _basic(self) -> str | None:
        user, cred = os.environ.get("REGISTRY_USER"), os.environ.get("REGISTRY_TOKEN")
        if user and cred:
            return "Basic " + base64.b64encode(f"{user}:{cred}".encode()).decode()
        return None

    def _authenticate(self, challenge: str) -> None:
        scheme, _, params = challenge.partition(" ")
        if scheme.lower() != "bearer":
            basic = self._basic()
            if not basic:
                raise UsageError(f"{self.host}: registry asks for {scheme} auth and no credentials are set")
            self.auth_header = basic
            return
        fields = dict(re.findall(r'(\w+)="([^"]*)"', params))
        query = {"service": fields.get("service", ""), "scope": f"repository:{self.name}:pull"}
        req = urllib.request.Request(fields["realm"] + "?" + urllib.parse.urlencode(query))
        basic = self._basic()
        if basic:
            req.add_header("Authorization", basic)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as e:
            raise NotReadable(f"{self.host}/{self.name}: token request returned HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise UsageError(f"{self.host}: {e.reason}") from e
        self.auth_header = "Bearer " + (body.get("token") or body["access_token"])

    def get(self, path: str, accept: tuple[str, ...] = ()) -> tuple[int, bytes, dict]:
        for _ in range(2):
            req = urllib.request.Request(self.base + path)
            if accept:
                req.add_header("Accept", ", ".join(accept))
            if self.auth_header:
                req.add_header("Authorization", self.auth_header)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.status, resp.read(), dict(resp.headers)
            except urllib.error.HTTPError as e:
                if e.code == 401 and self.auth_header is None:
                    self._authenticate(e.headers.get("WWW-Authenticate", ""))
                    continue
                return e.code, e.read(), dict(e.headers)
            except urllib.error.URLError as e:
                raise UsageError(f"{self.host}: {e.reason}") from e
        raise UsageError(f"{self.host}: authentication failed")

    def tags(self) -> list[str]:
        status, body, _ = self.get("/tags/list")
        if status == 404:
            return []  # the repository does not exist yet
        if status in (401, 403):
            raise NotReadable(f"{self.host}/{self.name}: tags/list returned HTTP {status}")
        if status != 200:
            raise UsageError(f"{self.host}/{self.name}: tags/list returned HTTP {status}")
        return sorted(json.loads(body).get("tags") or [])

    def manifest(self, ref: str) -> tuple[int, dict, str]:
        status, body, headers = self.get(f"/manifests/{ref}", MANIFEST_TYPES)
        if status != 200:
            return status, {}, ""
        digest = {k.lower(): v for k, v in headers.items()}.get("docker-content-digest", "")
        return status, json.loads(body), digest


def assert_absent(image: str, version: str, allow_unreadable: bool = False) -> None:
    reg = Registry(image)
    try:
        tags = reg.tags()
    except NotReadable as e:
        if not allow_unreadable:
            raise UsageError(f"{e}; cannot prove that {image}:{version} is absent")
        # Early check only: a package that does not exist yet cannot be read.
        print(f"release: {e}; not provable yet (early check, --allow-unreadable)")
        return
    if version in tags:
        raise CheckFailed(f"{image}:{version} already exists; a published tag is never moved")
    status, _, _ = reg.manifest(version)
    if status == 200:
        raise CheckFailed(f"{image}:{version} already exists; a published tag is never moved")
    if status != 404:
        raise UsageError(f"{image}:{version}: manifest lookup returned HTTP {status}; "
                         "cannot prove that the tag is absent")
    print(f"release: {image}:{version} does not exist yet")


def assert_tags(image: str, version: str) -> None:
    tags = Registry(image).tags()
    if version not in tags:
        raise CheckFailed(f"{image}: tag {version} was not produced (tags: {tags})")
    bad = [t for t in tags if not IMAGE_TAG_RE.match(t)]
    if bad:
        raise CheckFailed(f"{image}: tags not of the form X.Y.Z: {bad}")
    print(f"release: {image} tags {tags}: {version} present, every tag is X.Y.Z")


def platform_of(entry: dict) -> str | None:
    p = entry.get("platform") or {}
    if (entry.get("annotations") or {}).get("vnd.docker.reference.type") == "attestation-manifest":
        return None
    if p.get("os") == "unknown":
        return None
    s = f"{p.get('os')}/{p.get('architecture')}"
    return s + (f"/{p['variant']}" if p.get("variant") else "")


def assert_platforms(image: str, version: str, platforms: list[str]) -> str:
    status, index, digest = Registry(image).manifest(version)
    if status != 200:
        raise CheckFailed(f"{image}:{version}: manifest returned HTTP {status}")
    if index.get("mediaType") not in INDEX_TYPES:
        raise CheckFailed(f"{image}:{version} is not a multi-platform index ({index.get('mediaType')})")
    found = sorted(p for p in (platform_of(m) for m in index.get("manifests", [])) if p)
    if found != sorted(platforms):
        raise CheckFailed(f"{image}:{version}: platforms {found}, expected {sorted(platforms)}")
    if not digest.startswith("sha256:"):
        raise UsageError(f"{image}:{version}: registry sent no content digest")
    print(digest)
    print(f"release: {image}:{version} lists {found}", file=sys.stderr)
    return digest


def notes(image: str, version: str, digest: str, platforms: list[str]) -> str:
    plist = ", ".join(f"`{p}`" for p in platforms)
    return f"""## Image

```text
{image}:{version}
{image}@{digest}
```

- Digest: `{digest}`
- Platforms: {plist}
- Tag: `{version}` only. There is no `latest` tag; pin the digest.

```sh
docker pull {image}@{digest}
```

The image contents and pins are listed in `docs/SPECS.md` and reported by
`tlc-check --version`. How to run it: `docs/INTEGRATION.md` at this tag.
"""


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 2 and argv[0] == "version":
            print(release_version(argv[1]))
        elif argv[:1] == ["assert-absent"] and len(argv) in (3, 4) and argv[3:] in ([], ["--allow-unreadable"]):
            assert_absent(argv[1], argv[2], allow_unreadable=argv[3:] == ["--allow-unreadable"])
        elif len(argv) == 3 and argv[0] == "assert-tags":
            assert_tags(argv[1], argv[2])
        elif len(argv) >= 4 and argv[0] == "assert-platforms":
            assert_platforms(argv[1], argv[2], argv[3:])
        elif len(argv) >= 5 and argv[0] == "notes":
            print(notes(argv[1], argv[2], argv[3], argv[4:]), end="")
        else:
            raise UsageError("usage: see the module docstring (release.py --help)")
    except UsageError as e:
        if argv[:1] in (["--help"], ["-h"]):
            print(__doc__)
            return 0
        print(f"release: {e}", file=sys.stderr)
        return 2
    except CheckFailed as e:
        print(f"release: FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
