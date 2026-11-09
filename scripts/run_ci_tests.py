"""Compatibility entry point for the public shared-plan executor."""
import sys

from pytest_selective.execution import main

if __name__ == "__main__":
    raise SystemExit(main(["--", *sys.argv[1:]]))
