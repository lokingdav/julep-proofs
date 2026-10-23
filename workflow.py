#!/usr/bin/env python3
"""Heap-capped, source-addressed Tamarin runs; never infer success from exit 0 alone."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
VERDICT = re.compile(r"^\s+(\w+) \((all-traces|exists-trace)\): (verified|falsified|analysis incomplete)(?:.*?\((\d+) steps\))?\s*$", re.M)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lemma_dependencies(source):
    declarations = list(re.finditer(r"^lemma\s+(\w+)(?:\s*\[([^]]*)\])?\s*:", source, re.M))
    sources = [m[1] for m in declarations if "sources" in [a.strip() for a in (m[2] or "").split(",")]]
    prior = []
    result = {}
    for match in declarations:
        attrs = [a.strip() for a in (match[2] or "").split(",")]
        hidden = {a.split("=", 1)[1].strip() for a in attrs if a.startswith("hide_lemma=")}
        result[match[1]] = [] if "sources" in attrs else [n for n in dict.fromkeys(sources + prior) if n not in hidden]
        if "reuse" in attrs:
            prior.append(match[1])
    return result


def run(args):
    theory = Path(args.theory).resolve()
    names = re.findall(r"^lemma\s+(\w+)", theory.read_text(), re.M)
    selected = names if args.lemma == "ALL" else [args.lemma]
    if not selected or any(name not in names for name in selected):
        raise ValueError("No matching lemma in the source")
    source_hash = digest(theory)
    folder = HERE / "logs" / "review" / source_hash[:16]
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"-{time.time_ns() % 1000000000:09d}"
    base = folder / f"{theory.stem}-{args.lemma}-{stamp}"
    snapshot = folder / theory.name
    if not snapshot.exists():
        snapshot.write_bytes(theory.read_bytes())
    command = [args.prover, "--prove" if args.lemma == "ALL" else "--prove=" + args.lemma,
               "--derivcheck-timeout=0", "--quit-on-warning", "--quiet"]
    if args.heuristic:
        command += ["--heuristic=" + args.heuristic]
    if args.search:
        command += ["--stop-on-trace=" + args.search]
    oracle_hash = None
    if args.oracle:
        oracle = Path(args.oracle).resolve()
        oracle_hash = digest(oracle)
        saved_oracle = folder / ("oracle-" + oracle_hash[:16] + ".py")
        if not saved_oracle.exists():
            saved_oracle.write_bytes(oracle.read_bytes())
            saved_oracle.chmod(0o755)
        command += ["--oraclename=" + str(saved_oracle)]
    command += ["+RTS", f"-M{args.heap}g", f"-N{args.threads}", "-RTS", str(snapshot)]
    env = dict(os.environ)
    brew = "/home/linuxbrew/.linuxbrew/bin"
    if os.path.isdir(brew) and brew not in env.get("PATH", ""):
        env["PATH"] = brew + ":" + env.get("PATH", "")
    version = subprocess.run([args.prover, "--version"], env=env, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15).stdout.strip()
    started = time.monotonic()
    timed_out = False
    with base.with_suffix(".log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   env=env, cwd=HERE, start_new_session=True)
        try:
            code = process.wait(timeout=args.timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
    output = base.with_suffix(".log").read_text()
    verdicts = {name: {"kind": kind, "verdict": verdict, "steps": int(steps) if steps else None}
                for name, kind, verdict, steps in VERDICT.findall(output)}
    status = "complete"
    if timed_out:
        status = "timeout"
    elif "heap overflow" in output.lower() or "heap exhausted" in output.lower():
        status = "heap cap"
    elif code != 0:
        status = "prover error"
    elif any(verdicts.get(name, {}).get("verdict") not in ("verified", "falsified") for name in selected):
        status = "incomplete"
    record = {"prover_version": version, "dependencies": lemma_dependencies(snapshot.read_text()), "expected": args.expect, "theory": str(theory), "sha256": source_hash, "oracle_sha256": oracle_hash,
              "command": command, "selected": selected, "status": status, "exit_code": code,
              "seconds": round(time.monotonic() - started, 2), "verdicts": verdicts,
              "log": str(base.with_suffix(".log")), "note": "Individual results depend on any reused/source lemmas; check the complete matrix."}
    base.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"{theory.name} / {args.lemma}: {status} ({record['seconds']}s)")
    for name in selected:
        print(f"  {name}: {verdicts.get(name, {}).get('verdict', 'NO VERDICT')}")
    print("  " + str(base.with_suffix(".json")))
    if status != "complete":
        return 2
    return 0 if all(verdicts[name]["verdict"] == args.expect for name in selected) else 1


def collect_results(theories):
    """Return dependency-checked results for both human and technical reports."""
    success = True
    rows = []
    for value in theories:
        theory = Path(value).resolve()
        records = []
        for path in (HERE / "logs" / "review" / digest(theory)[:16]).glob("*.json"):
            record = json.loads(path.read_text())
            if record["sha256"] == digest(theory) and record["theory"] == str(theory):
                records.append(record)
        dependencies = lemma_dependencies(theory.read_text())
        outcomes_by_name = {}
        for r in records:
            if r["status"] == "complete":
                for n in r["selected"]:
                    outcomes_by_name.setdefault(n, set()).add(r["verdicts"][n]["verdict"])
        checked = {n for n, outcomes in outcomes_by_name.items() if outcomes == {"verified"}}
        # Require the entire transitive helper chain, not just a helper's local verdict.
        while True:
            valid = {n for n in checked if set(dependencies.get(n, [])).issubset(checked)}
            if valid == checked:
                break
            checked = valid
        for name in re.findall(r"^lemma\s+(\w+)", theory.read_text(), re.M):
            finished = [r for r in records if r["status"] == "complete" and name in r["selected"]]
            outcomes = {r["verdicts"][name]["verdict"] for r in finished}
            if len(outcomes) > 1:
                verdict, steps, seconds = "CONFLICT", "", ""
            elif finished:
                best = min(finished, key=lambda r: r["seconds"])
                verdict = best["verdicts"][name]["verdict"]
                steps, seconds = best["verdicts"][name]["steps"], best["seconds"]
                missing = [d for d in dependencies.get(name, []) if d not in checked]
                if missing:
                    verdict += " (dependencies pending: " + ", ".join(missing) + ")"
            else:
                attempted = [r for r in records if name in r["selected"]]
                verdict = attempted[-1]["status"] if attempted else "not run"
                steps = seconds = ""
            expected = "falsified" if name.endswith("_expected_falsified") else "verified"
            success &= verdict == expected
            rows.append(dict(theory=theory.stem, lemma=name, verdict=verdict,
                             steps=steps, seconds=seconds))
    return (0 if success else 2), rows


def result_table(rows):
    lines = ["| Theory | Lemma | Verdict | Steps | Run seconds |",
             "|---|---|---|---:|---:|"]
    for row in rows:
        lines.append("| {theory} | `{lemma}` | {verdict} | {steps} | {seconds} |".format(**row))
    return "\n".join(lines) + "\n"


def collect(args):
    status, rows = collect_results(args.theories)
    print(result_table(rows), end="")
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prove = sub.add_parser("run")
    prove.add_argument("theory")
    prove.add_argument("lemma", nargs="?", default="ALL")
    prove.add_argument("--timeout", type=int, default=120)
    prove.add_argument("--threads", type=int, default=2)
    prove.add_argument("--heap", type=int, default=4)
    prove.add_argument("--heuristic")
    prove.add_argument("--oracle")
    prove.add_argument("--search", choices=["DFS", "BFS", "SEQDFS"])
    prove.add_argument("--prover", default="tamarin-prover")
    prove.add_argument("--expect", choices=["verified", "falsified"], default="verified")
    table = sub.add_parser("collect")
    table.add_argument("theories", nargs="+")
    args = parser.parse_args()
    if args.action == "run" and min(args.timeout, args.threads, args.heap) < 1:
        parser.error("Timeout, threads and heap must be positive")
    return run(args) if args.action == "run" else collect(args)


if __name__ == "__main__":
    sys.exit(main())
