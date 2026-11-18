#!/usr/bin/env python3
"""Acceptance tests for tlc-check, run inside the toolchain image.

Usage: TLC_CHECK_IMAGE=<image> python3 test/tlc-check/test_tlc_check.py [-v]

Every test starts from the hardened invocation of docs/SPECS.md and changes
only what the test is about. The tests run one container at a time and remove
every container and volume they create. They need `docker` and nothing else.

Spec directories and output directories reach the containers through Docker
volumes, not bind mounts, so the suite also works when the Docker daemon runs
elsewhere (for example a CI job that talks to the runner host's daemon).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
IMAGE = os.environ.get("TLC_CHECK_IMAGE", "")
UID = "12345:12345"
LABEL = "tlc-check-test"


def hardened(memory: str = "512m", tmpfs: str | None = "size=256m,mode=1777") -> list[str]:
    args = [
        "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", UID,
        "--memory", memory, "--memory-swap", memory,
        "--cpus", "2", "--pids-limit", "512",
    ]
    if tmpfs is not None:
        args += ["--tmpfs", f"/tmp:{tmpfs}" if tmpfs else "/tmp"]
    return args


def docker(*args: str, check: bool = True) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          check=check).stdout


class Volume:
    """A uniquely named Docker volume, removed by remove()."""

    def __init__(self, source: Path | None = None, writable: bool = False):
        self.name = f"{LABEL}-{uuid.uuid4().hex[:12]}"
        docker("volume", "create", "--label", LABEL, self.name)
        if source is not None:
            loader = docker("create", "--network", "none", "--label", LABEL,
                            "-v", f"{self.name}:/v", IMAGE, "true").strip()
            try:
                docker("cp", f"{source}/.", f"{loader}:/v")
            finally:
                docker("rm", "-f", loader, check=False)
        if writable:
            self.root("chmod -R a+rwX /v")

    def load(self, source: Path, subdir: str) -> None:
        """Copy a directory's files into <volume>/<subdir>, writable by anyone."""
        self.root(f'mkdir -p "/v/{subdir}"')
        loader = docker("create", "--network", "none", "--label", LABEL,
                        "-v", f"{self.name}:/v", IMAGE, "true").strip()
        try:
            docker("cp", f"{source}/.", f"{loader}:/v/{subdir}")
        finally:
            docker("rm", "-f", loader, check=False)
        self.root("chmod -R a+rwX /v")

    def root(self, script: str) -> str:
        """Run a shell script as root with the volume at /v; return stdout."""
        return docker("run", "--rm", "--network", "none", "--user", "0:0", "--label", LABEL,
                      "-v", f"{self.name}:/v", IMAGE, "sh", "-c", script)

    def read(self, path: str) -> str:
        return self.root(f'cat "/v/{path}"')

    def digest(self) -> str:
        """Names, modes, sizes, times and contents of every entry."""
        return self.root("cd /v && find . -exec stat -c '%n %F %a %s %Y' {} + | sort && "
                         "find . -type f -exec sha256sum {} + | sort")

    def remove(self) -> None:
        docker("volume", "rm", "-f", self.name, check=False)


_fixtures: dict[str, Volume] = {}


def fixture(name: str) -> Volume:
    """The read-only volume of a fixture directory, loaded once per run."""
    if name not in _fixtures:
        _fixtures[name] = Volume(FIXTURES / name)
    return _fixtures[name]


def tearDownModule() -> None:
    for v in _fixtures.values():
        v.remove()


class Result:
    def __init__(self, rc: int, output: str, oom_killed: bool):
        self.rc, self.output, self.oom_killed = rc, output, oom_killed

    def summary(self) -> dict[str, int]:
        """Model -> status, from the summary block."""
        block = self.output.split("tlc-check: summary:", 1)[-1]
        return {m.group(1): int(m.group(2))
                for m in re.finditer(r"^  (\S+): status (\d+):", block, re.M)}

    def __str__(self) -> str:
        return f"rc={self.rc} oom_killed={self.oom_killed}\n{self.output}"


def docker_run(docker_args: list[str], command: list[str], timeout: int = 600) -> Result:
    name = f"{LABEL}-{uuid.uuid4().hex[:12]}"
    try:
        p = subprocess.run(
            ["docker", "run", "--name", name, "--label", LABEL, *docker_args, IMAGE, *command],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        state = docker("inspect", "-f", "{{.State.OOMKilled}}", name).strip()
        return Result(p.returncode, p.stdout, state == "true")
    finally:
        docker("rm", "-f", name, check=False)


def check(name: str, *args: str, memory: str = "512m",
          tmpfs: str | None = "size=256m,mode=1777", extra: list[str] | None = None,
          specs: Volume | None = None, spec_mode: str = "ro") -> Result:
    vol = specs or fixture(name)
    docker_args = hardened(memory, tmpfs) + (extra or []) + ["-v", f"{vol.name}:/specs:{spec_mode}"]
    return docker_run(docker_args, ["tlc-check", *args, "/specs"])


class TempVolume:
    """A writable volume for one test: `with TempVolume() as v: ...`."""

    def __init__(self, source: Path | None = None):
        self.source = source

    def __enter__(self) -> Volume:
        self.vol = Volume(self.source, writable=True)
        return self.vol

    def __exit__(self, *exc) -> None:
        self.vol.remove()


class TlcCheck(unittest.TestCase):
    def assertStatus(self, r: Result, rc: int) -> None:
        self.assertEqual(r.rc, rc, str(r))
        self.assertFalse(r.oom_killed, f"container was OOM-killed\n{r}")

    # A passing model returns 0 and prints its state count.
    def test_pass_prints_state_count(self):
        r = check("pass")
        self.assertStatus(r, 0)
        self.assertEqual(r.summary(), {"Counter.cfg": 0})
        self.assertRegex(r.output, r"Counter\.cfg: status 0: 10 distinct states")

    # An invariant violation returns 1 and the counterexample is in --out.
    def test_violation_counterexample_in_out(self):
        with TempVolume() as out:
            r = check("violation", "--out", "/out", extra=["-v", f"{out.name}:/out"])
            self.assertStatus(r, 1)
            self.assertEqual(r.summary(), {"Viol.cfg": 1})
            log = out.read("Viol.log")
            self.assertIn("Invariant Small is violated", log)
            self.assertIn("State 6:", log)
            self.assertRegex(log, r"x = 5")

    # A model above 10 x expected-states returns 1; at exactly 10 x it passes.
    def test_guard_at_limit_passes(self):
        r = check("pass")
        self.assertStatus(r, 0)
        self.assertIn("10 distinct states <= 10 (10 x expected-states 1)", r.output)

    def test_guard_above_limit_fails(self):
        r = check("guard-over")
        self.assertStatus(r, 1)
        self.assertIn("11 distinct states > 10 (10 x expected-states 1)", r.output)

    # An unreadable expected-states marker returns 1.
    def test_unreadable_marker_fails(self):
        r = check("guard-unreadable")
        self.assertStatus(r, 1)
        self.assertIn("unreadable expected-states marker", r.output)

    # --deep checks only *.deep.cfg; the default mode checks only the others.
    def test_default_mode_skips_deep_models(self):
        r = check("pass")
        self.assertStatus(r, 0)
        self.assertEqual(r.summary(), {"Counter.cfg": 0})
        self.assertNotIn("Counter.deep.cfg", r.output)

    def test_deep_mode_checks_only_deep_models(self):
        r = check("pass", "--deep")
        self.assertStatus(r, 0)
        self.assertEqual(r.summary(), {"Counter.deep.cfg": 0})
        self.assertIn("20 distinct states", r.output)
        self.assertNotIn("=== tlc-check: Counter.cfg ", r.output)

    # Read-only spec mount, read-only root, sized tmpfs, arbitrary UID: the run
    # passes and the spec directory is unchanged.
    def test_read_only_mount_passes_and_is_unchanged(self):
        before = fixture("pass").digest()
        r = check("pass", tmpfs="size=256m,mode=1777")
        self.assertStatus(r, 0)
        self.assertEqual(fixture("pass").digest(), before)

    def test_writable_spec_dir_is_not_written(self):
        # Even a writable spec directory receives no file: states, logs and
        # traces go to the scratch directory.
        with TempVolume(FIXTURES / "violation") as d:
            before = d.digest()
            r = check("violation", specs=d, spec_mode="rw")
            self.assertStatus(r, 1)
            self.assertEqual(d.digest(), before)

    # A scratch layout whose generated paths are, or contain, the spec
    # directory is refused before anything is removed or opened.
    def test_out_overlapping_spec_dir_is_rejected(self):
        for subdir in ("Counter.states", "Counter.states/sub", "Counter.log"):
            with self.subTest(subdir=subdir), TempVolume() as vol:
                vol.load(FIXTURES / "pass", subdir)
                before = vol.digest()
                r = docker_run(hardened() + ["-v", f"{vol.name}:/out"],
                               ["tlc-check", "--out", "/out", f"/out/{subdir}"])
                self.assertStatus(r, 2)
                self.assertIn("choose an --out that does not contain it", r.output)
                self.assertNotIn("TLC2 Version", r.output)
                self.assertEqual(vol.digest(), before)

    def test_out_beside_spec_dir_in_same_volume_passes(self):
        # An ordinary ancestor --out that does not collide stays allowed.
        with TempVolume() as vol:
            vol.load(FIXTURES / "pass", "specs")
            before = vol.root("cd /v/specs && find . -type f -exec sha256sum {} + | sort")
            r = docker_run(hardened() + ["-v", f"{vol.name}:/out"],
                           ["tlc-check", "--out", "/out", "/out/specs"])
            self.assertStatus(r, 0)
            self.assertEqual(vol.root("cd /v/specs && find . -type f -exec sha256sum {} + | sort"),
                             before)
            self.assertIn("Model checking completed", vol.read("Counter.log"))

    # Heap exhaustion under a 512 MiB container returns 3, names the model,
    # and the kernel does not OOM-kill the container.
    def test_heap_exhaustion_returns_3_without_kernel_oom(self):
        r = check("hog")
        self.assertStatus(r, 3)
        self.assertEqual(r.summary(), {"Hog.cfg": 3})
        self.assertIn("Hog.cfg: status 3: out of memory", r.output)

    # States outgrow a 32 MiB tmpfs scratch: 4, model named, no kernel OOM.
    def test_scratch_full_returns_4_without_kernel_oom(self):
        r = check("spill", tmpfs="size=32m,mode=1777")
        self.assertStatus(r, 4)
        self.assertEqual(r.summary(), {"Spill.cfg": 4})
        self.assertIn("Spill.cfg: status 4: scratch directory", r.output)

    # --memory 1g in a 512 MiB container returns 2 before any model starts.
    def test_memory_above_limit_is_rejected(self):
        r = check("pass", "--memory", "1g")
        self.assertStatus(r, 2)
        self.assertIn("--memory 1 GiB does not fit", r.output)
        self.assertNotIn("=== tlc-check:", r.output)
        self.assertNotIn("TLC2 Version", r.output)

    # An unsized tmpfs in a memory-limited container returns 2 and names the fix.
    def test_unsized_tmpfs_is_rejected_with_fix(self):
        r = check("pass", tmpfs="")
        self.assertStatus(r, 2)
        self.assertIn("tmpfs without a size limit", r.output)
        self.assertIn("--tmpfs /tmp:size=", r.output)
        self.assertIn("--out", r.output)
        self.assertNotIn("TLC2 Version", r.output)

    # Disk-backed --out: S is 0, B = L - headroom, and the state-heavy model
    # that fills a 32 MiB tmpfs is not stopped by the scratch size.
    def test_disk_backed_out_has_no_scratch_charge(self):
        with TempVolume() as out:
            r = check("spill", "--out", "/out", tmpfs="size=32m,mode=1777",
                      extra=["-v", f"{out.name}:/out"])
            self.assertStatus(r, 0)
            self.assertIn("counted 0)", r.output)
            self.assertIn("budget 384 MiB", r.output)          # 512 MiB - 128 MiB
            self.assertEqual(r.summary(), {"Spill.cfg": 0})

    # JVM option variables in the environment do not change the heap.
    def test_java_option_variables_are_ignored(self):
        heap = re.compile(r"with (\d+)MB heap and (\d+)MB offheap")
        plain = check("pass")
        self.assertStatus(plain, 0)
        env = []
        for var in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
            env += ["-e", f"{var}=-Xmx64g -XX:MaxDirectMemorySize=64g"]
        r = check("pass", extra=env)
        self.assertStatus(r, 0)
        self.assertNotIn("Picked up", r.output)
        self.assertEqual(heap.search(r.output).groups(), heap.search(plain.output).groups())

    # A model that outlives --deadline returns 124 and leaves no JVM.
    def test_deadline_returns_124_and_leaves_no_jvm(self):
        script = (
            'tlc-check --deadline 5s /specs; rc=$?; '
            'for p in /proc/[0-9]*; do '
            '  c=$(cat "$p/comm" 2>/dev/null); '
            '  [ "$c" = java ] && echo "LEFTOVER JVM: pid ${p#/proc/}"; '
            'done; exit $rc')
        r = docker_run(hardened() + ["-v", f"{fixture('slow').name}:/specs:ro"],
                       ["sh", "-c", script])
        self.assertStatus(r, 124)
        self.assertEqual(r.summary(), {"Slow.cfg": 124})
        self.assertNotIn("LEFTOVER JVM", r.output)

    # One failing model does not stop the others; the summary lists every model.
    def test_failing_model_does_not_stop_the_others(self):
        r = check("mixed")
        self.assertStatus(r, 1)
        self.assertEqual(r.summary(), {"Alpha.cfg": 0, "Middle.cfg": 1, "Omega.cfg": 0})
        self.assertIn("=== tlc-check: Omega.cfg", r.output)

    # Exit-status precedence: 124, then 4, then 3, then 1.
    def test_precedence_scratch_over_oom_over_fail(self):
        r = check("precedence", tmpfs="size=32m,mode=1777")
        self.assertStatus(r, 4)
        self.assertEqual(r.summary(), {"Hog.cfg": 3, "Middle.cfg": 1, "Spill.cfg": 4})

    def test_precedence_deadline_first(self):
        r = check("precedence-deadline", "--deadline", "5s")
        self.assertStatus(r, 124)
        self.assertEqual(r.summary(), {"Hog.cfg": 3, "Slow.cfg": 124})

    # Contract details beyond the acceptance list.
    def test_missing_spec_is_a_usage_error(self):
        r = check("missing-tla")
        self.assertStatus(r, 2)
        self.assertIn("Orphan.cfg (no Orphan.tla)", r.output)
        self.assertNotIn("TLC2 Version", r.output)

    def test_empty_directory_is_a_usage_error(self):
        r = check("violation", "--deep")
        self.assertStatus(r, 2)
        self.assertIn("no models", r.output)

    def test_invalid_option_values_are_usage_errors(self):
        for args in (["--memory", "1x"], ["--deadline", "0s"], ["--workers", "0"], ["--bogus"]):
            with self.subTest(args=args):
                self.assertStatus(check("pass", *args), 2)

    def test_no_memory_limit_warns_and_uses_2_gib(self):
        args = [a for a in hardened() if a not in ("--memory", "512m", "--memory-swap")]
        r = docker_run(args + ["-v", f"{fixture('pass').name}:/specs:ro"],
                       ["tlc-check", "/specs"])
        self.assertStatus(r, 0)
        self.assertIn("no memory limit", r.output)
        self.assertIn("budget 2 GiB", r.output)

    def test_no_memory_limit_still_enforces_the_minimum_budget(self):
        args = [a for a in hardened() if a not in ("--memory", "512m", "--memory-swap")]
        r = docker_run(args + ["-v", f"{fixture('pass').name}:/specs:ro"],
                       ["tlc-check", "--memory", "1m", "/specs"])
        self.assertStatus(r, 2)
        self.assertIn("below the minimum budget", r.output)
        self.assertNotIn("=== tlc-check:", r.output)
        self.assertNotIn("TLC2 Version", r.output)

    def test_version_reports_pins(self):
        r = docker_run(hardened(), ["tlc-check", "--version"])
        self.assertStatus(r, 0)
        self.assertRegex(r.output, r"(?m)^tlc-check \S+$")
        self.assertIn("TLC v1.7.4", r.output)
        self.assertIn("936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88", r.output)
        self.assertRegex(r.output, r"(?m)^JRE 21\.")


if __name__ == "__main__":
    if not IMAGE:
        sys.exit("set TLC_CHECK_IMAGE to the image under test")
    unittest.main()
