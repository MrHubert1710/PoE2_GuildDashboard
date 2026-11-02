#!/usr/bin/env python3
"""Rebuild local archive copies from the legacy checkout without using its code/API."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.archive_files import import_archives


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent / 'poe2-guild')
    args = parser.parse_args()
    import_archives(args.source, ROOT / 'data')
