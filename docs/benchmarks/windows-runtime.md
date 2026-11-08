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

## Worker-count controls

The manual **Matched Windows performance** workflow also accepts
`candidate-workers`. It defaults to four, matching ordinary CI. Both arms now
use native Git and the runner work disk for temporary repositories; worker-count
experiments must not accidentally compare different Git executables. Each arm
loads its own checkout through `PYTHONPATH` and explicitly disables selective
execution, preserving the full suite, coverage and JUnit evidence.

For a worker-count comparison, set `baseline` to the exact SHA of the selected
workflow ref. The workflow runs four-worker baseline, candidate, candidate,
four-worker baseline on each Python version. It runs only on manual dispatch,
so editing the benchmark does not automatically consume four complete suites
per Python version.

[Run 42505855403, attempt 1](https://github.com/gigaverse-app/pytest-selective/actions/runs/42505855403)
compared four and eight workers on the same revision,
`1535d35b17e242219550f4534e1c059bc4abbc59`:

| Python | Four-worker samples | Eight-worker samples | Mean before | Mean after | Reduction (higher is better) |
| --- | --- | --- | --- | --- | --- |
| 3.11 | 100.88s, 90.08s | 98.72s, 93.56s | 95.48s | 96.14s | -0.7% |
| 3.14 | 127.28s, 128.69s | 123.15s, 124.00s | 127.98s | 123.58s | 3.4% |

All samples retained the same 830 test identities and outcomes per interpreter:
819 passed/11 skipped on Python 3.11 and 828 passed/2 skipped on Python 3.14.
Covered line and branch totals were identical within each interpreter. The
`matched-windows-3.11` and `matched-windows-3.14` artifacts hold the raw evidence.
These two samples per arm do not establish a consistent benefit from eight
workers, so ordinary CI retains four.

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

## Git compatibility

The fetch optimization uses `--no-auto-gc`, the equivalent spelling available
since the documented Git 2.24 minimum. The newer `--no-auto-maintenance` spelling
caused dependency comparison to fall back to all tests on that version. The
existing real-repository pin-move regression reproduced this with a built Git
2.24.0 binary before the correction. Afterward the complete first-party dependency
suite passes on Git 2.24.0 and on the current installed Git. The timing results
above describe the measured revision; the alias correction does not change its
behavior on the measured modern Git versions.
