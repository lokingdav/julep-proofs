#!/usr/bin/env python3
"""Archive one current-source run per lemma, including unresolved obligations."""
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

import workflow
import results_report

HERE = Path(__file__).resolve().parent


def checked_validation(path, root):
    """Do not package validation claims against sources or logs that changed."""
    validation = json.loads(Path(path).read_text())
    for group in ("source_sha256", "artifact_sha256"):
        hashes = validation.get(group)
        if not isinstance(hashes, dict) or not hashes:
            raise ValueError(f"Validation metadata lacks {group}; refresh VALIDATION.json")
        for name, expected in hashes.items():
            current = Path(root) / name
            if not current.is_file() or workflow.digest(current) != expected:
                raise ValueError(f"Stale validation evidence: {name}; refresh VALIDATION.json")
    return validation


def main():
    theories = [HERE / f"julep_{name}.spthy" for name in ("pairing", "auth", "oda", "ratchet_regression")]
    dest = HERE / "review"
    dest.mkdir(exist_ok=True)
    checked_validation(dest / "audits" / "VALIDATION.json", results_report.PAPER_ROOT)
    status, rows = workflow.collect_results(theories)
    report = results_report.render_report(theories, rows, status)
    findings_path = HERE / "MODELING_FINDINGS.md"
    appendix = results_report.render_findings_appendix(theories, rows, status)
    findings = results_report.update_findings(findings_path.read_text(), appendix)
    records = []
    files = {}
    for theory in theories:
        sha = workflow.digest(theory)
        files["sources/" + theory.name] = theory.read_bytes()
        candidates = [json.loads(p.read_text()) for p in (HERE / "logs" / "review" / sha[:16]).glob("*.json")]
        candidates = [r for r in candidates if r["sha256"] == sha and r["theory"] == str(theory)]
        for name in re.findall(r"^lemma\s+(\w+)", theory.read_text(), re.M):
            runs = [r for r in candidates if name in r["selected"]]
            completed = [r for r in runs if r["status"] == "complete"]
            if not runs:
                records.append({"theory": theory.name, "lemma": name, "sha256": sha, "status": "not run"})
                continue
            chosen = dict(min(completed, key=lambda r: r["seconds"]) if completed else max(runs, key=lambda r: Path(r["log"]).stat().st_mtime))
            log = Path(chosen["log"]).read_bytes()
            member = f"logs/{theory.stem}-{name}.log"
            files[member] = log
            chosen.update(lemma=name, archived_log=member, log_sha256=hashlib.sha256(log).hexdigest())
            if chosen["oracle_sha256"]:
                saved = Path(chosen["log"]).parent / ("oracle-" + chosen["oracle_sha256"][:16] + ".py")
                files["oracles/" + saved.name] = saved.read_bytes()
            records.append(chosen)
    for name in ("workflow.py", "suite.py", "oracle.py", "prove.sh", "sweep.sh",
                 "collect.sh", "finish.sh", "export_evidence.py", "test_workflow.py",
                 "results_report.py", "lemma_explanations.json", "test_results_report.py",
                 "test_export_evidence.py", "watchdog.sh"):
        files["workflow/" + name] = (HERE / name).read_bytes()
    for reference in results_report.REFERENCE_FILES:
        files["references/" + reference] = (results_report.PAPER_ROOT / reference).read_bytes()
    for p in sorted((dest / "audits").glob("*")):
        if p.is_file():
            files["audits/" + p.name] = p.read_bytes()
    files["references/tamarin/proofs/review/RESULTS.md"] = report.encode()
    files["references/tamarin/proofs/MODELING_FINDINGS.md"] = findings.encode()
    counts = Counter(r["verdict"] for r in rows)
    manifest = {"collector_exit_code": status, "counts": dict(counts), "runs": records,
                "files_sha256": {name: hashlib.sha256(data).hexdigest()
                                 for name, data in sorted(files.items())}}
    encoded = (json.dumps(manifest, indent=2) + "\n").encode()
    (dest / "MANIFEST.json").write_bytes(encoded)
    files["MANIFEST.json"] = encoded
    with (dest / "evidence.tar.gz").open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as archive:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    (dest / "RESULTS.md").write_text(report)
    findings_path.write_text(findings)
    print(dict(counts))
    print(f"Evidence written to {dest}; collector status {status}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
