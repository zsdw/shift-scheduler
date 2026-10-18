"""2026-10-05: 저장된 야간 표에서도 근무자 번호(이름) 끌기 → 번호·자리 교환 (근무표 줄은 그대로). PC·폰."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from night_shift import history_store
from night_shift.actual_edit import apply_edits, describe_edit
from night_shift.models import Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule

APP = str(Path(__file__).resolve().parents[1] / "app.py")
NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
DAY = date(2026, 10, 9)


def plan():
    staff = [StaffInput("A", "통제", True, False, None, True)]
    staff += [StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()]
    result = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, tuple(staff)), HistorySelection(),
                          SolveOptions(rules_version="2.20", seconds=20))
    assert result.valid
    return result.record


class PersonSwapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = plan()

    def test_numbers_and_schedule_move_together(self):
        rows = lambda rec, who: [r.displayed_assignment.label for r in sorted(  # noqa: E731
            (r for r in rec.assignments if r.employee_id == who), key=lambda r: r.slot.index)]
        number = lambda rec, who: next(a.display_number for a in rec.context.attendance if a.employee_id == who)  # noqa: E731
        swapped = apply_edits(self.plan, [{"type": "person", "a": "1", "b": "2"}])
        self.assertEqual(rows(swapped, "1"), rows(self.plan, "2"))           # 만년이 원종의 하루를 받음
        self.assertEqual(number(swapped, "1"), number(self.plan, "2"))       # 번호도 같이
        with self.assertRaises(ValueError):
            apply_edits(self.plan, [{"type": "person", "a": "A", "b": "2"}])  # 통제는 안 됨
        self.assertIn("번호·자리 교환", describe_edit({"type": "person", "a": "1", "b": "2"}, NAMES))

    def test_saved_editor_name_drag_pc_and_mobile(self):
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                history_store.save_confirmed(Path(folder), self.plan, "2.20")
                at = AppTest.from_file(APP, default_timeout=180)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = DAY
                at.run()
                calls = []

                def fake(component, **kw):
                    if component.name.endswith("drag_schedule") and kw.get("key") == f"saved_grid_{DAY}":
                        calls.append(kw["data"])
                        return {"kind": "person", "source": "1", "target": "2", "nonce": f"p-{view}"}
                    return None
                with patch("streamlit.components.v1.custom_component.CustomComponent.__call__", autospec=True,
                           side_effect=fake):
                    at.run()
                self.assertFalse(at.exception)
                self.assertTrue(any(r["movable"] for r in calls[0]["rows"]))  # 이름 칸 끌기 가능
                self.assertEqual(calls[0]["compact"], view == "mobile")       # 폰은 한 화면 표
                at.button(key=f"saved_save_{DAY}").click().run()
                self.assertEqual(history_store.load(Path(folder), DAY)["edits"][-1], {"type": "person", "a": "1", "b": "2"})


if __name__ == "__main__":
    unittest.main()
