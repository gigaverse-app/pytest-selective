# Measuring Windows runtime without dropping tests

The Git-heavy suite exercises real commits, dependency fetches and CLI invocations.
[The runtime change](https://github.com/gigaverse-app/pytest-selective/pull/15)
batches old/new commit existence checks, verifies only newly fetched objects a
second time, and avoids automatic maintenance in the already bounded shallow
cache and tiny temporary test histories. The nested audit fixture now owns its
pytest temporary directory, avoiding cleanup of earlier Git fixture trees.

No tests, platforms, Python versions, selection safety checks or coverage
collection were removed. Missing and non-commit objects still prevent narrowing.

## Complete hosted suites

The [final matched run](https://github.com/gigaverse-app/pytest-selective/actions/runs/39854060026)
compares baseline `a7be2f78cef2cb30e3f1c11074e718628140ab09` with candidate
`b73343a144621a027f06057c1fb53a1b8f8540f4`. Each Python version uses one Windows
worker and runs baseline, candidate, candidate, baseline, with four pytest
workers, coverage and JUnit enabled throughout. Dependencies are installed before
timing. Each sample gets a fresh explicit temporary base, so one arm does not
time cleanup of another arm's Git fixture trees. Times include the uv/pytest
command, coverage and JUnit output, and exclude checkout and dependency setup.

| Python | Baseline samples | Candidate samples | Mean before | Mean after | Reduction |
| --- | --- | --- | --- | --- | --- |
| 3.11 | 90.39s, 90.58s | 85.74s, 83.03s | 90.48s | 84.38s | 6.7% |
| 3.14 | 124.71s, 122.14s | 137.49s, 118.53s | 123.43s | 128.01s | -3.7% |

Python 3.11 improved in both samples. Python 3.14 did not establish a full-suite
improvement: its first candidate was slower and its second was faster. The
reported mean is 3.7% slower; the focused improvements below do not justify a
universal Windows-suite speedup claim. No sample is excluded from these means.

The `matched-windows-{python}` artifacts contain every log, JUnit inventory,
coverage XML and a timing manifest recording exact commits and exit codes.
These are two samples per arm on one worker per Python version, not a confidence
interval or a guarantee for different machines. Use the **Matched Windows
performance** workflow with an immutable baseline and the desired candidate ref
to repeat the measurement.

## Coverage preservation

On Python 3.11, both candidates retain all 540 original outcomes: 529 passed and
11 skipped, plus one new passing regression for commit/object-type checks.
On Python 3.14, both candidates retain all 540 original outcomes: 538 passed and
2 skipped, plus the same new passing regression. All eight complete suites pass.
JUnit identities and outcomes are compared directly. Coverage XML is compared
using source-line mappings between the two commits: no previously covered
unchanged source line, branch count or mapped branch destination lost coverage.
The [complete normal CI matrix](https://github.com/gigaverse-app/pytest-selective/actions/runs/39854060034)
also passed.

## Measured sources of overhead

| Native Windows measurement | Before | After | Method |
| --- | --- | --- | --- |
| Warm dependency-cache validation | 95.57 ms | 23.40 ms | Median of nine alternating calls; both commit objects checked after each call |
| Nested audit fixture setup | 15.02s | 1.20s | Complete 33-test audit suite before and after temporary-directory isolation |
| Complete audit suite | 20.01s | 5.20s | Same 33 tests, all passing |

The warm path starts one commit-probe process instead of four. A cold fetch uses
two probes instead of four and still verifies fetched objects. Production caches
retain the existing shallow-history bound and rebuild behavior; this does not
disable maintenance for users' repositories.

## Earlier observations and limits

The [first hosted ABBA experiment](https://github.com/gigaverse-app/pytest-selective/actions/runs/39851403849)
**did not establish a speedup**. Before the audit cleanup fix, Python 3.11
baseline samples were 198.72/215.02s and candidate samples 241.04/246.98s. Python
3.14 baseline samples were 187.35/201.26s and candidate samples 189.62/266.09s.
Logs exposed 30-second audit setup pauses and wider I/O variation. Those results
motivated the fixture fix and separate temporary bases for the final experiment;
they are retained here instead of selecting only favorable measurements.

Earlier local Windows Python 3.11 pairs at the baseline and initial candidate
`5f5ef23` measured 115.48 to 90.07s, then 87.98 to 83.49s. The first baseline
included a 14-second fixture setup outlier. A later unpaired final-candidate run
took 119.37s. All original outcomes and covered unchanged lines/branches were
preserved. Separate normal CI workers also varied substantially: baseline pytest
steps were 126/135s for Python 3.11/3.14, versus 172/140s for the final candidate.
These unpaired observations are not the basis for the hosted speedup claim.
