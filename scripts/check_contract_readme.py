"""Check the README fragment against the selection contract's verified report."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- pytest-quint-connect:start -->"
END = "<!-- pytest-quint-connect:end -->"


def main() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    expected = (ROOT / "contracts/selection/verified-report.md").read_text(encoding="utf-8").rstrip("\n")
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise SystemExit("Expected exactly one selection contract block in README.md")
    block = readme.partition(START)[2].partition(END)
    if not block[1] or START + block[0] + END != expected:
        raise SystemExit("README contract block differs from contracts/selection/verified-report.md")


if __name__ == "__main__":
    main()
