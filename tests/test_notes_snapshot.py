"""2026-10-20 사용자 확정: 확정 저장 때 화면의 특이사항 문장을 스냅샷으로 함께 저장하고 그대로 읽는다."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.test_manager_late_half import request
from night_shift import history_store
from night_shift.service import HistorySelection, SolveOptions, run_schedule


class NotesSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_schedule(request(), HistorySelection(),
                                  SolveOptions(rules_version="2.20", seconds=15, prefer_dual_mode=False))

    def test_snapshot_saved_and_loaded(self):
        lines = ["차단봉: 마지막으로 설치·철수한 날이 오래된 제욱(마지막 10/16)에게 오늘 맡겼습니다(15-8, 막타임 다음 우선)."]
        with tempfile.TemporaryDirectory() as tmp:
            history_store.save_confirmed(Path(tmp), self.result.record, "2.20",
                                         now=datetime(2026, 10, 20, 9), notes_snapshot=lines)
            data = history_store.load(Path(tmp), self.result.context.shift_start_date)
            self.assertEqual(data["notes_snapshot"]["lines"], lines)
            self.assertEqual(data["notes_snapshot"]["saved_at"], "2026-10-20T09:00:00")

    def test_no_snapshot_keeps_old_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_store.save_confirmed(Path(tmp), self.result.record, "2.20")
            data = history_store.load(Path(tmp), self.result.context.shift_start_date)
            self.assertNotIn("notes_snapshot", data)


if __name__ == "__main__":
    unittest.main()
