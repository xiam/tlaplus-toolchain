#!/usr/bin/env python3
"""Offline tests of scripts/release.py (no registry, no Docker)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import release  # noqa: E402


class FakeRegistry:
    def __init__(self, tags, index=None, digest="sha256:" + "a" * 64, unreadable=False):
        self._tags, self._index, self._digest, self._unreadable = tags, index, digest, unreadable

    def tags(self):
        if self._unreadable:
            raise release.NotReadable("denied")
        return self._tags

    def manifest(self, ref):
        if self._index is None or ref not in self._tags:
            return 404, {}, ""
        return 200, self._index, self._digest


def index(*platforms, attestation=True):
    manifests = [{"platform": {"os": p.split("/")[0], "architecture": p.split("/")[1]}} for p in platforms]
    if attestation:
        manifests.append({"platform": {"os": "unknown", "architecture": "unknown"},
                          "annotations": {"vnd.docker.reference.type": "attestation-manifest"}})
    return {"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": manifests}


class VersionTest(unittest.TestCase):
    def test_release_tag_maps_to_image_tag(self):
        self.assertEqual(release.release_version("v0.1.0"), "0.1.0")
        self.assertEqual(release.release_version("v10.20.30"), "10.20.30")

    def test_other_forms_are_rejected(self):
        for tag in ["0.1.0", "v0.1", "v0.1.0-rc1", "v01.0.0", "latest", "v0.1.0 ", "V0.1.0"]:
            with self.subTest(tag=tag), self.assertRaises(release.UsageError):
                release.release_version(tag)


class RegistryChecksTest(unittest.TestCase):
    def setUp(self):
        self._orig = release.Registry
        self.addCleanup(setattr, release, "Registry", self._orig)

    def use(self, fake):
        release.Registry = lambda image: fake

    def test_absent_passes_only_when_proven(self):
        self.use(FakeRegistry(["0.1.0"]))
        release.assert_absent("r/x", "0.2.0")

    def test_absent_unreadable_is_an_error_unless_allowed(self):
        self.use(FakeRegistry([], unreadable=True))
        with self.assertRaises(release.UsageError):
            release.assert_absent("r/x", "0.1.0")
        release.assert_absent("r/x", "0.1.0", allow_unreadable=True)

    def test_absent_requires_a_clean_404(self):
        fake = FakeRegistry([])
        fake.manifest = lambda ref: (401, {}, "")
        self.use(fake)
        with self.assertRaises(release.UsageError):
            release.assert_absent("r/x", "0.1.0")

    def test_absent_fails_for_existing(self):
        self.use(FakeRegistry(["0.1.0"], index=index("linux/amd64")))
        with self.assertRaises(release.CheckFailed):
            release.assert_absent("r/x", "0.1.0")

    def test_tags_reject_latest_and_v_prefix(self):
        self.use(FakeRegistry(["0.1.0"]))
        release.assert_tags("r/x", "0.1.0")
        for tags in (["0.1.0", "latest"], ["0.1.0", "v0.1.0"], []):
            with self.subTest(tags=tags), self.assertRaises(release.CheckFailed):
                self.use(FakeRegistry(tags))
                release.assert_tags("r/x", "0.1.0")

    def test_platforms_exact(self):
        self.use(FakeRegistry(["0.1.0"], index=index("linux/amd64", "linux/arm64")))
        self.assertTrue(release.assert_platforms("r/x", "0.1.0", ["linux/arm64", "linux/amd64"]).startswith("sha256:"))
        for wanted in (["linux/amd64"], ["linux/amd64", "linux/arm64", "linux/s390x"]):
            with self.subTest(wanted=wanted), self.assertRaises(release.CheckFailed):
                release.assert_platforms("r/x", "0.1.0", wanted)

    def test_platforms_require_an_index(self):
        single = {"mediaType": "application/vnd.oci.image.manifest.v1+json"}
        self.use(FakeRegistry(["0.1.0"], index=single))
        with self.assertRaises(release.CheckFailed):
            release.assert_platforms("r/x", "0.1.0", ["linux/amd64"])

    def test_notes_carry_the_digest(self):
        d = "sha256:" + "b" * 64
        text = release.notes("ghcr.io/o/r", "0.1.0", d, ["linux/amd64", "linux/arm64"])
        self.assertIn(f"ghcr.io/o/r@{d}", text)
        self.assertIn("ghcr.io/o/r:0.1.0", text)
        self.assertNotIn("latest`", text.replace("no `latest` tag", ""))


if __name__ == "__main__":
    unittest.main()
