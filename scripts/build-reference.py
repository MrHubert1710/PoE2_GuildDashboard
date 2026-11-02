#!/usr/bin/env python3
"""Generate phase 0 reference evidence offline. Neither source is modified."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.reference import build_reference


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent / 'poe2-guild')
    args = parser.parse_args()
    reference = build_reference(ROOT / 'data', args.source)
    destination = ROOT / 'data/reference/phase0.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(reference, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(destination)
    for league in reference['leagues']:
        print(f"{league['name']}: {league['transactions']} transactions, "
              f"{len(league['verified_files'])} verified files, issues={league['issues']}")
