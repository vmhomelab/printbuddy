"""Command line utilities for Printbuddy."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Printbuddy command line utilities")
    parser.parse_args()


if __name__ == "__main__":
    main()
