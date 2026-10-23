"""An evidence bundle must not silently retain stale validation claims."""
import json
from pathlib import Path
import tempfile
import unittest

import export_evidence
import workflow


class EvidenceValidationTests(unittest.TestCase):
    def test_changed_source_or_audit_log_rejects_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, log, manifest = [root / name for name in ("model.spthy", "audit.log", "VALIDATION.json")]
            source.write_text("source used by audit")
            log.write_text("actual audit output")
            record = {"source_sha256": {source.name: workflow.digest(source)},
                      "artifact_sha256": {log.name: workflow.digest(log)}}
            manifest.write_text(json.dumps(record))
            self.assertEqual(export_evidence.checked_validation(manifest, root), record)
            for changed in (source, log):
                with self.subTest(changed=changed.name):
                    original = changed.read_bytes()
                    changed.write_bytes(original + b"changed")
                    with self.assertRaisesRegex(ValueError, "Stale validation evidence"):
                        export_evidence.checked_validation(manifest, root)
                    changed.write_bytes(original)

    def test_missing_hash_inventory_cannot_masquerade_as_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "VALIDATION.json"
            manifest.write_text(json.dumps({"result": "passed"}))
            with self.assertRaisesRegex(ValueError, "lacks source_sha256"):
                export_evidence.checked_validation(manifest, root)


if __name__ == "__main__":
    unittest.main()
