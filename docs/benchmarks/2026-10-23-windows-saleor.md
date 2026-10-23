# Fix the measured critical path, not just the CI plumbing

Selective #32 moved an existing native Git optimization into CI-esta. It did not
speed up test execution. Its observed regression was Windows pytest 160 → 186s,
checkout 5 → 16s, and environment setup 10 → 18s. Those measurements cannot
attribute every second of runner variation to the action move.

This follow-up keeps temporary repositories on the runner work disk and uses
`git init --template=` for fixtures, avoiding hundreds of copies of unused Git
sample hooks. All platform/Python lanes, real commits, coverage, minimum-pytest
compatibility and the executable tutorial remain required.

## Fresh hosted control and after

| Measurement | Unchanged control | Optimized | Difference |
| --- | ---: | ---: | ---: |
| Windows Python 3.11 pytest step | 187s | 73s | −61.0% |
| Windows Python 3.14 pytest step | 185s | 115s | −37.8% |
| Validation gate elapsed | 249s | 185s | −25.7% |
| Dependency critical-path execution | 242s | 177s | −26.9% |
| Sum of all job execution | 740 runner-seconds | 597 runner-seconds | −19.3% |

The critical path remains `select-tests → Windows tests → Validation gate`.
The longest Windows variant changes from Python 3.11 to 3.14. Runner-seconds
are a sum of job durations, not elapsed time or billed minutes.

Sources, both attempt 1:

- [Fresh unchanged control, run 39919567540](https://github.com/gigaverse-app/pytest-selective/actions/runs/39919567540),
  head `4301c88e440b60f514c94f1bf32a025322ba2ad2`.
- [Optimized run 39919114589](https://github.com/gigaverse-app/pytest-selective/actions/runs/39919114589),
  head `d142f5af4d836f308140e923d4e66cc895f518b0`.

The control was dispatched after the optimized run, rather than choosing only
the earlier slow run. The [earlier unchanged run](https://github.com/gigaverse-app/pytest-selective/actions/runs/39915035279)
took 391s to the gate, with 258s/330s Windows test steps. That variation is why
the smaller fresh-control comparison is the headline. These are observed runs,
not a guaranteed percentage or a statistically isolated attribution between
the two filesystem changes. A local Windows template-only experiment measured
63.52s before and 64.41s after, so it showed no local speedup by itself.

## Conformance evidence

Both Windows versions retain all 626 original JUnit cases and their outcomes.
Each adds one passing test proving that minimal templates still produce real,
independent commit histories. Python 3.11 retains its platform-specific skips;
Python 3.14 retains its own baseline skip set. Coverage remains enabled.

[Raw CI-esta reports and JUnit files](2026-10-23-windows-saleor/) preserve the
run/head/attempt identities, DAG edges, timestamps, slack, and case inventories.
CI-esta computes the dependency path from the workflow DAG; it does not call the
longest individual step the entire critical path.

## Apply the optimization

Set temporary paths on the pytest **step**, where the runner context is valid:

```yaml
- run: uv run --locked pytest -q -n 4 --cov --junitxml=test-timings.xml
  env:
    TMP: ${{ runner.temp }}
    TEMP: ${{ runner.temp }}
    TMPDIR: ${{ runner.temp }}
```

Keep the matrix and full case inventory, collect before/after JUnit and job/step
reports, and repeat a control on the original revision. Do not disable security
software, mock Git, or drop coverage to make the graph look better. See
[CI-esta's portable recipes](https://github.com/gigaverse-app/ci-esta/blob/main/docs/critical-path-optimizations.md)
for database client matching and profiling recovery tests.

## Observed optimized workflow timeline

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontFamily": "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif", "fontSize": "13px", "doneTaskBkgColor": "#3B82F6", "doneTaskBorderColor": "#2563EB", "critBkgColor": "#EA580C", "activeTaskBkgColor": "#2EA043", "activeTaskBorderColor": "#1A7F37", "critBorderColor": "#C2410C", "taskBkgColor": "#3B82F6", "taskBorderColor": "#2563EB", "taskTextColor": "#FFFFFF", "taskTextDarkColor": "#FFFFFF", "taskTextLightColor": "#FFFFFF", "taskTextOutsideColor": "#8B949E", "titleColor": "#8B949E", "sectionBkgColor": "rgba(234, 88, 12, 0.07)", "altSectionBkgColor": "rgba(139, 148, 158, 0.05)", "sectionBkgColor2": "rgba(234, 88, 12, 0.07)", "gridColor": "rgba(139, 148, 158, 0.3)", "todayLineColor": "rgba(0, 0, 0, 0)"}, "gantt": {"barHeight": 20, "barGap": 6, "topPadding": 44, "leftPadding": 230, "sectionFontSize": 13, "fontSize": 12}}}%%
gantt
    title 3m 5s to merge-ready · orange is what the merge waited on
    dateFormat YYYY-MM-DD HH:mm:ss
    axisFormat %M:%S
    todayMarker off
    section distributions
    41s :done, j0, 2000-01-01 00:00:03, 2000-01-01 00:00:44
    section quality
    16s :done, j1, 2000-01-01 00:00:03, 2000-01-01 00:00:19
    section select-tests
    11s :crit, j2, 2000-01-01 00:00:03, 2000-01-01 00:00:14
    section pytest-minimum
    24s :done, j3, 2000-01-01 00:00:16, 2000-01-01 00:00:40
    section tests · 3.11, ubuntu-latest
    42s :done, j4, 2000-01-01 00:00:16, 2000-01-01 00:00:58
    section tests · 3.11, macos-latest
    59s :done, j5, 2000-01-01 00:00:17, 2000-01-01 00:01:16
    section tests · 3.14, macos-latest
    1m 33s :done, j6, 2000-01-01 00:00:17, 2000-01-01 00:01:50
    section tests · 3.14, ubuntu-latest
    43s :done, j7, 2000-01-01 00:00:17, 2000-01-01 00:01:00
    section tests · 3.14, windows-latest
    2m 42s :crit, j8, 2000-01-01 00:00:17, 2000-01-01 00:02:59
    section tests · 3.11, windows-latest
    1m 42s · ⏳ 42s :done, j9, 2000-01-01 00:00:56, 2000-01-01 00:02:38
    section Validation gate
    4s :crit, j10, 2000-01-01 00:03:01, 2000-01-01 00:03:05
    section ✅ merge-ready 3m 5s
    ✅ :active, m, 2000-01-01 00:03:05, 2000-01-01 00:04:01
```

Orange follows the actual `needs` graph. Bars are observed API timestamps,
normalized to workflow creation; gaps include runner/admission delay.
