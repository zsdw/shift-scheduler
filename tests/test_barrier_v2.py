"""15-0 차단봉 고정 담당 (2026-10-05 사용자 확정, 이 날짜 야간부터, FM·유도리 공통):
20시 설치 = G2 운영 시 G2 + 보안실 대기 1명, G2 없으면 I1 + 보안실 대기 1명 / 04시 철수 = I1 근무자.
피로도는 대기 설치자만 1점(포스트 겸임은 원래 회계). 통제A 불참. 20시 대기 표기 1명(H-16).
이전 날짜 기록은 옛 규칙 그대로."""
import unittest
from dataclasses import replace
from datetime import date

from night_shift.models import HistoryInput, Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def staff(absent=()):
    return (StaffInput("A", "통제", True, False, None, True),
            *(StaffInput(p, n, p not in absent, True, int(p), False) for p, n in NAMES.items()))


def solve(day, night, mode, absent=()):
    result = run_schedule(ShiftRequest(day, night, mode, staff(absent)), HistorySelection(),
                          SolveOptions(rules_version="2.20", seconds=20))
    assert result.valid, (result.validation_errors, result.solve_result.status)
    return result.record


def roles(record):
    install = sorted(r.displayed_assignment.label for r in record.assignments if r.barrier_install_flag)
    remove = [(r.displayed_assignment.label, r.slot.index) for r in record.assignments if r.barrier_remove_flag]
    return install, remove


class BarrierV2Tests(unittest.TestCase):
    def test_generated_roles(self):
        cases = ((date(2026, 10, 6), NightType.N1, Mode.FM, (), ["G2", "보안실 대기"]),
                 (date(2026, 10, 6), NightType.N1, Mode.FLEXIBLE, (), ["G2", "보안실 대기"]),
                 (date(2026, 10, 6), NightType.N1, Mode.FM, ("3", "4"), ["I1", "보안실 대기"]),
                 (date(2026, 10, 10), NightType.N4, Mode.FM, (), ["I1"]))
        for day, night, mode, absent, expected in cases:
            with self.subTest(night=night, mode=mode, absent=absent):
                record = solve(day, night, mode, absent)
                install, remove = roles(record)
                self.assertEqual(install, expected)
                self.assertEqual(remove, [("I1", 10)])
                for r in record.assignments:
                    if r.barrier_install_flag or r.barrier_remove_flag:
                        self.assertNotEqual(r.employee_id, "A")                 # 통제A 불참
                        expected_fatigue = {"G2": 2, "I1": 1, "보안실 대기": 1}[r.displayed_assignment.label]
                        self.assertEqual(r.fatigue_value, expected_fatigue)       # 대기만 차단봉 1점
                standby_20 = sum(r.slot.index == 2 and r.displayed_assignment.label == "보안실 대기"
                                 for r in record.assignments)
                self.assertEqual(standby_20, 1)                                  # 20시 대기 표기 1명

    def test_old_date_keeps_old_rule(self):
        install, remove = roles(solve(date(2026, 9, 28), NightType.N1, Mode.FM))
        self.assertEqual(install, ["보안실 대기"])
        self.assertEqual(remove, [("보안실 대기", 10)])

    def test_validator_rejects_standby_removal_under_new_rule(self):
        record = solve(date(2026, 10, 6), NightType.N1, Mode.FM)
        rows = [replace(r, barrier_remove_flag=False) if r.barrier_remove_flag else r for r in record.assignments]
        bad = replace(record, assignments=tuple(rows))
        rules = {e["rule"] for e in validate_first_trial(bad, HistoryInput((), ()), rules_v220=True)}
        self.assertIn("15-0", rules)

    def test_g2_install_choices_require_standby_instead_of_i1(self):
        from night_shift.service import build_context
        from night_shift.profiles import options_for
        context = build_context(ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, staff()))
        rows = options_for(context, "1", 2)
        self.assertEqual({r.displayed_assignment.label for r in rows if r.barrier_install_flag},
                         {"G2", "보안실 대기"})


if __name__ == "__main__":
    unittest.main()
