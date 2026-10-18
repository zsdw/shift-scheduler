import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from night_shift import date_check

class OrderSourceMissingTests(unittest.TestCase):
    def test_absent_order_sources_do_not_claim_mismatch(self):
        report = {"teams": {"주간조": "B조", "야간조": "A조"}}
        with patch.object(date_check, "_report", return_value=(report, [], [], None, [])):
            issues = date_check.review(Path("nonexistent_test_store"), date(2026, 10, 9), {})
        missing = [i for i in issues if i["kind"] == "order_source_missing"]
        self.assertEqual(missing, [])
