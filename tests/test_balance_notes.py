"""Balance explanations and monthly direction (plain-language notes)."""
import unittest
from dataclasses import replace
from datetime import date

from night_shift.balance_notes import balance_reasons, monthly_direction
from night_shift.models import Mode, NightType
from night_shift.service import (
    HistorySelection, ShiftRequest, SolveOptions, StaffInput, calculate_all_stats, run_schedule,
)

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


class BalanceNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        staff = [StaffInput("A", "통제", True, False, None, True)]
        staff += [StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()]
        cls.result = run_schedule(ShiftRequest(date(2026, 10, 1), NightType.N1, Mode.FM, tuple(staff)),
                                  HistorySelection(), SolveOptions(rules_version="2.20", seconds=20))
        assert cls.result.valid

    def test_routine_rules_are_not_listed(self):
        reasons = balance_reasons(self.result.record, self.result.employee_stats, self.result.prepared_inputs)
        # 2026-10-13: 3점 예외를 실제로 쓴 표는 예외 안내 줄이 정상(사용자 확정 '예외 사용 시 비고 표시') — 그 줄만 뺀다
        routine = [r for r in reasons if not r.startswith("통제A 피로도 격차 3점 예외")]
        self.assertFalse(any("0~2점" in r or "8-4" in r for r in routine), routine)
        self.assertTrue(reasons)

    def test_emergency_person_is_named(self):
        reasons = balance_reasons(self.result.record, self.result.employee_stats, None,
                                  emergency={"employee": "4", "from": 7, "reason": "후반부 반차 (01시 퇴근)",
                                             "locked_through": 2})
        self.assertIn("긴급반차·이탈자 광희 (01시부터 근무불가)", reasons[0])
        self.assertIn("18시~20시 LOCK", reasons[0])

    def test_edit_is_named_as_reason(self):
        record = self.result.record
        person = next(p for p in NAMES if calculate_all_stats(record)[p].fatigue_value > 0)
        rows = tuple(replace(r, fatigue_value=r.fatigue_value + 1)
                     if r.employee_id == person and r.actual_work_time_value == 1 else r
                     for r in record.assignments)
        edited = replace(record, assignments=rows)
        reasons = balance_reasons(edited, calculate_all_stats(edited), None,
                                  plan_stats=calculate_all_stats(record))
        # 2026-10-05: 사람별 설명은 실근무·피로도 둘 다 최고/최저인 사람만 → 수정 사실은 밸런스 판정 줄에 표시
        self.assertTrue(any("끌어서 수정한 표" in r for r in reasons), reasons)

    def test_monthly_direction(self):
        rows = [{"직원": "만년", "평균 피로도": 15.0}, {"직원": "원종", "평균 피로도": 12.0},
                {"직원": "제욱", "평균 피로도": 13.5}, {"직원": "통제", "평균 피로도": 11.0, "is_manager": True}]
        text = " ".join(monthly_direction(rows))
        self.assertIn("만년(15.0)", text)
        self.assertIn("원종(12.0)", text)
        self.assertNotIn("통제(", text)
        self.assertIn("기록이 아직 적어", monthly_direction([])[0])

    def test_monthly_direction_explains_day_mix_with_peer_gap(self):
        # 2026-10-19: 월 평균은 높지만 같은 날 동료 대비 차이가 작으면 날짜 구성 때문이라고 설명
        rows = [{"직원": "준호", "평균 피로도": 14.0, "동료 대비(±)": "+0.1"},
                {"직원": "광희", "평균 피로도": 12.7, "동료 대비(±)": "-0.2"},
                {"직원": "만년", "평균 피로도": 13.1, "동료 대비(±)": "+0.0"}]
        text = " ".join(monthly_direction(rows))
        self.assertIn("준호(같은 날 동료 대비 +0.1)", text)
        self.assertIn("출근한 날의 구성", text)
        rows[0]["동료 대비(±)"] = "+1.2"
        self.assertNotIn("준호(같은 날 동료 대비", " ".join(monthly_direction(rows)))


if __name__ == "__main__":
    unittest.main()
