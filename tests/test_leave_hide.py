"""연차일정 달력 칩 삭제 (2026-10-23 사용자 확정): 원본(파일) 일정은 파일을 고치지 않고 그날만 '원본 숨김' 직접 등록으로 지운다.
기간 일정에서 하루만 지우면 나머지 날은 그대로, 숨김을 지우면 원본이 다시 보이고, 새 연차일정 파일을 올리면 초기화."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from night_shift import leave_schedule as ls


class LeaveHideTests(unittest.TestCase):
    def test_hide_one_day_keeps_other_days_and_file(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            ls.save_text(store, "10월 21일\nC조 조백호 사원 - 연차\n10월 22일\nC조 조백호 사원 - 연차\n안내 김은예 사원 - 연차")
            original = (store / ls.LEAVE_FILE).read_bytes()
            hid = ls.hide_original(store, "조백호", "C", date(2026, 10, 22))
            entries = ls.load(store)
            self.assertEqual([e["name"] for e in entries[date(2026, 10, 22)]], ["김은예"])
            self.assertEqual([e["name"] for e in entries[date(2026, 10, 21)]], ["조백호"])
            self.assertEqual((store / ls.LEAVE_FILE).read_bytes(), original)
            ls.delete_manual(store, hid)                     # 숨김을 지우면 원본이 다시 보인다
            self.assertIn("조백호", [e["name"] for e in ls.load(store)[date(2026, 10, 22)]])

    def test_hidden_day_overlapping_manual_is_refused_and_upload_resets(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            ls.save_text(store, "10월 23일\nC조 허승회 사원 - 연차")
            ls.hide_original(store, "허승회", "C", date(2026, 10, 23))
            with self.assertRaises(ValueError):
                ls.save_manual(store, "허승회", "C", date(2026, 10, 23), date(2026, 10, 24), "교육")
            ls.replace_uploaded_text(store, "10월 23일\nC조 허승회 사원 - 연차")
            self.assertEqual([e["kind"] for e in ls.load(store)[date(2026, 10, 23)]], ["연차"])


if __name__ == "__main__":
    unittest.main()
