"""H-18 [하드, 2026-10-05 사용자 확정]: 하루 전체 근무하는 일반근무자끼리 실근무 차이 최대 1시간.
0-2-1(FM·유도리 두 기준 해)보다 우선, 실제 운영 모드 표 기준. 반차·이탈자와 통제는 비교에서 뺀다."""
import unittest
from collections import Counter
from dataclasses import replace
from datetime import date

from night_shift.models import HistoryInput, Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def staff(absent=(), late=()):
    rows = [StaffInput("A", "통제", True, False, None, True)]
    rows += [StaffInput(p, n, p not in absent, True, int(p), False, tuple(range(7)) if p in late else None)
             for p, n in NAMES.items()]
    return tuple(rows)


def spread(result):
    whole = {a.employee_id for a in result.record.context.attendance if a.present and a.is_general_worker
             and not a.acts_as_manager and all(a.is_available(t) for t in range(14))}
    work = Counter()
    for r in result.record.assignments:
        if r.employee_id in whole:
            work[r.employee_id] += r.actual_work_time_value
    return max(work.values()) - min(work.values())


class WorkSpreadTests(unittest.TestCase):
    def test_generated(self):
        cases = ((date(2026, 10, 6), NightType.N1, Mode.FM, (), ()),
                 (date(2026, 10, 10), NightType.N4, Mode.FM, (), ()),
                 (date(2026, 10, 6), NightType.N1, Mode.FLEXIBLE, (), ()),
                 (date(2026, 10, 6), NightType.N1, Mode.FM, ("3",), ()),
                 (date(2026, 10, 6), NightType.N1, Mode.FM, ("3", "4"), ()),
                 (date(2026, 10, 6), NightType.N1, Mode.FM, (), ("6",)))
        for day, night, mode, absent, late in cases:
            with self.subTest(night=night, mode=mode, absent=absent, late=late):
                result = run_schedule(ShiftRequest(day, night, mode, staff(absent, late)), HistorySelection(),
                                      SolveOptions(rules_version="2.20", seconds=20))
                self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
                self.assertLessEqual(spread(result), 1)

    def test_validator_rejects_two_hours(self):
        result = run_schedule(ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, staff()), HistorySelection(),
                              SolveOptions(rules_version="2.20", seconds=20))
        rows = list(result.record.assignments)
        # 위반표: 한 사람의 휴게 칸 2개를 실근무로 바꾼 기록 (다른 규칙 위반과 별개로 H-18이 잡혀야 함)
        target = next(a.employee_id for a in result.record.context.attendance if a.is_general_worker and a.present)
        changed = 0
        for i, r in enumerate(rows):
            if r.employee_id == target and r.actual_work_time_value == 0 and changed < 3:
                rows[i] = replace(r, actual_work_time_value=1)
                changed += 1
        bad = replace(result.record, assignments=tuple(rows))
        rules = {e["rule"] for e in validate_first_trial(bad, HistoryInput((), ()), rules_v220=True)}
        self.assertIn("H-18", rules)
        rules = {e["rule"] for e in validate_first_trial(bad, HistoryInput((), ()), rules_v220=True, work_spread=False)}
        self.assertNotIn("H-18", rules)


if __name__ == "__main__":
    unittest.main()
