"""5-7 추가 남문 (2026-10-05 사용자 확정): 남문을 원래 안 여는 시간이 있는 회차(N2/N3/N4)는 생성 전에
'G2 추가 운영 시간'을 확인받는다(답하기 전 생성 버튼 잠금, PC·폰). 고른 시간은 G2 1명 필수(통제 포함 누구나)."""
import os
import tempfile

os.environ["NIGHT_SHIFT_HISTORY_DIR"] = tempfile.mkdtemp(prefix="night_shift_extra_south_")

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from night_shift.models import HistoryInput, Mode, NightType, extra_south_choices
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, build_context, run_schedule
from night_shift.validator import validate_first_trial

APP = str(Path(__file__).resolve().parents[1] / "app.py")
NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
STAFF = (StaffInput("A", "통제", True, False, None, True),
         *(StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()))


class ExtraSouthTests(unittest.TestCase):
    def test_choices(self):
        self.assertEqual(extra_south_choices(NightType.N1), ())
        self.assertEqual(extra_south_choices(NightType.N2), (12, 13))
        self.assertEqual(extra_south_choices(NightType.N3), (0, 1, 2))
        self.assertEqual(extra_south_choices(NightType.N4), (0, 1, 2, 12, 13))
        with self.assertRaises(ValueError):                 # 원래 남문 여는 시간은 고를 수 없음
            build_context(ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, STAFF, extra_south_slots=(0,)))

    def test_generated_has_g2_and_validator_checks_it(self):
        from dataclasses import replace
        result = run_schedule(ShiftRequest(date(2026, 10, 10), NightType.N4, Mode.FM, STAFF, extra_south_slots=(1, 13)),
                              HistorySelection(), SolveOptions(rules_version="2.20", seconds=20))
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
        for t in (1, 13):
            self.assertEqual(sum(r.displayed_assignment.label == "G2" for r in result.record.assignments
                                 if r.slot.index == t), 1)
        # 위반표: 추가 남문을 확인하지 않은 회차에 G2가 있으면 포스트 구성 위반
        without = replace(result.record, context=replace(result.record.context, extra_south_slots=()))
        details = {e["detail"] for e in validate_first_trial(without, HistoryInput((), ()), rules_v220=True)}
        self.assertIn("Post coverage mismatch at 1", details)
        self.assertIn("Post coverage mismatch at 13", details)

    def test_generate_locked_until_answer_pc_and_mobile(self):
        for view in ("pc", "mobile"):
            with self.subTest(view=view):
                at = AppTest.from_file(APP, default_timeout=180)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = date(2026, 10, 10)          # 토→일 = N4
                at.run()
                self.assertTrue(at.button(key="generate_button").disabled)  # 답하기 전 잠금
                key = "extra_south_2026-10-10_N4"
                at.radio(key=key).set_value("추가 있음").run()
                self.assertTrue(at.button(key="generate_button").disabled)  # 시간 안 고르면 잠금
                at.multiselect(key=key + "_hours").set_value([1]).run()
                self.assertFalse(at.button(key="generate_button").disabled)
                seen = []

                def fake(request, *args, **kwargs):
                    seen.append(request.extra_south_slots)
                    raise RuntimeError("시험 중단")
                with patch("night_shift.service.run_schedule", side_effect=fake):
                    at.button(key="generate_button").click().run()
                self.assertEqual(seen, [(1,)])
                at.radio(key=key).set_value("추가 없음").run()
                self.assertFalse(at.button(key="generate_button").disabled)


if __name__ == "__main__":
    unittest.main()
