#!/usr/bin/env python3
"""Run each declared lemma, with bounded concurrency and an aggregate failure status."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theories", nargs="+")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--heap", type=int, default=4)
    args = parser.parse_args()
    if min(args.jobs, args.timeout, args.threads, args.heap) < 1:
        parser.error("Resource limits must be positive")
    tasks = [(str(Path(t).resolve()), n) for t in args.theories
             for n in re.findall(r"^lemma\s+(\w+)", Path(t).read_text(), re.M)]

    def prove(task):
        theory, lemma = task
        return subprocess.run(["bash", str(HERE / "prove.sh"), theory, lemma,
                               str(args.timeout), str(args.threads), str(args.heap)]).returncode

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        codes = list(pool.map(prove, tasks))
    return 0 if all(c == 0 for c in codes) else 2


if __name__ == "__main__":
    raise SystemExit(main())
