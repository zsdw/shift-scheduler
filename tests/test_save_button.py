"""2026-10-04 사용자 요청: '실제 근무 저장'은 항상 켜져 있고 누를 때마다 지금 화면을 최종본으로 덮어쓴다."""
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from night_shift import history_store
from night_shift.models import Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule

APP = str(Path(__file__).resolve().parents[1] / "app.py")
NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def generated(day):
    staff = [StaffInput("A", "통제", True, False, None, True)]
    staff += [StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()]
    result = run_schedule(ShiftRequest(day, NightType.N4, Mode.FM, tuple(staff)), HistorySelection(),
                          SolveOptions(rules_version="2.20", seconds=20))
    assert result.valid
    return result.record


class SaveButtonTests(unittest.TestCase):
    def test_save_keeps_note(self):
        with tempfile.TemporaryDirectory() as folder:
            day = date(2026, 10, 3)
            path = history_store.save_confirmed(Path(folder), generated(day), "2.20")
            data = json.loads(Path(path).read_text(encoding="utf-8")); data["note"] = "가져온 파일 메모"
            Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            history_store.save_edits(Path(folder), day, [])
            self.assertEqual(history_store.load(Path(folder), day)["note"], "가져온 파일 메모")

    def test_button_enabled_without_edits_and_saves(self):
        for view in ("pc", "mobile"):                                    # PC·폰 모두
            with self.subTest(view=view):
                self._enabled_and_saves(view)

    def _enabled_and_saves(self, view):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
            day = date(2026, 10, 3)
            history_store.save_confirmed(Path(folder), generated(day), "2.20")
            at = AppTest.from_file(APP, default_timeout=120)
            at.query_params["view"] = view
            at.run()
            at.session_state["shift_date"] = day
            at.run()
            button = at.button(key=f"saved_save_{day}")
            self.assertFalse(button.disabled)                            # 수정 없어도 켜져 있음
            self.assertNotIn("edited_at", history_store.load(Path(folder), day))
            button.click().run()
            self.assertFalse(at.exception)
            self.assertIn("edited_at", history_store.load(Path(folder), day))   # 누른 시점으로 최종본 저장
            self.assertTrue(any("최종본으로 저장" in s.value for s in at.success))


if __name__ == "__main__":
    unittest.main()
