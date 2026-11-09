"""Guards for the soak harness's pass/fail logic."""

from __future__ import annotations

import unittest

from tools.soak import Sample, analyse


def _sample(
    cycle: int,
    *,
    rss_mb: float = 40.0,
    fds: int = 12,
    threads: int = 1,
    traced_kb: int = 100,
) -> Sample:
    return Sample(
        cycle=cycle,
        rss_kb=int(rss_mb * 1024),
        fds=fds,
        threads=threads,
        traced_kb=traced_kb,
        elapsed_ms=1.0,
    )


class SoakAnalysisTests(unittest.TestCase):
    def test_stable_noise_passes(self) -> None:
        samples = [
            _sample(
                i,
                rss_mb=40.0 + (0.4 if i % 2 else -0.4),
                fds=12 + (i % 2),
                threads=1,
                traced_kb=100 + (i % 3),
            )
            for i in range(60)
        ]

        findings = analyse(samples)

        self.assertTrue(all(finding.ok for finding in findings), findings)

    def test_descriptor_growth_fails(self) -> None:
        samples = [_sample(i, fds=12 + i // 5) for i in range(60)]

        findings = analyse(samples)

        fds = next(finding for finding in findings if finding.metric == "file descriptors")
        self.assertFalse(fds.ok)
        self.assertGreaterEqual(fds.delta, 10)

    def test_thread_growth_fails(self) -> None:
        samples = [_sample(i, threads=1 + i // 10) for i in range(60)]

        findings = analyse(samples)

        threads = next(finding for finding in findings if finding.metric == "threads")
        self.assertFalse(threads.ok)

    def test_rss_growth_fails(self) -> None:
        samples = [_sample(i, rss_mb=40.0 + i * 0.15) for i in range(60)]

        findings = analyse(samples)

        rss = next(finding for finding in findings if finding.metric == "resident memory")
        self.assertFalse(rss.ok)
        self.assertGreater(rss.delta, 5.0)

    def test_tracemalloc_growth_fails(self) -> None:
        samples = [_sample(i, traced_kb=100 + i * 20) for i in range(60)]

        findings = analyse(samples)

        traced = next(finding for finding in findings if finding.metric == "tracemalloc")
        self.assertFalse(traced.ok)
        self.assertGreater(traced.delta, 512)

    def test_too_few_samples_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            analyse([_sample(i) for i in range(4)])


if __name__ == "__main__":
    unittest.main()
