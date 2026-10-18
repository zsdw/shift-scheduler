"""H-17 (2026-10-05 사용자 확정, 하드): 누구든 같은 포스트 한 회차 최대 3번. 2명 완전결원 + 해 없음일 때만 일시 해제."""
import unittest
from collections import Counter
from datetime import date
from unittest.mock import patch

from night_shift import history_import as imp
from night_shift import service
from night_shift.models import AssignmentKind, HistoryInput, Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def staff(absent=()):
    rows = [StaffInput("A", "통제", True, False, None, True)]
    number = 0
    for p, n in NAMES.items():
        present = p not in absent
        number += present
        rows.append(StaffInput(p, n, present, True, number if present else None, False))
    return tuple(rows)


def post_counts(record):
    """평일 시작(N1/N2) 18시 통제 L3 표기는 세지 않는다 (실제 보안실 대기, 2026-10-05 사용자 확정)."""
    weekday = record.context.night_type in (NightType.N1, NightType.N2)
    return Counter((r.employee_id, r.displayed_assignment.label.partition("(")[0]) for r in record.assignments
                   if r.displayed_assignment.kind == AssignmentKind.POST
                   and not (weekday and r.slot.index == 0 and r.employee_id == "A"))


class PostCapTests(unittest.TestCase):
    def test_generated_tables_never_repeat_a_post_four_times(self):
        for day, night, absent in ((date(2026, 10, 9), NightType.N4, ()), (date(2026, 10, 6), NightType.N1, ()),
                                   (date(2026, 10, 6), NightType.N1, ("3",))):
            with self.subTest(night=night, absent=absent):
                result = run_schedule(ShiftRequest(day, night, Mode.FM, staff(absent)), HistorySelection(),
                                      SolveOptions(rules_version="2.20", seconds=20))
                self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
                self.assertFalse(result.post_cap_relaxed)
                self.assertLessEqual(max(post_counts(result.record).values()), 3, post_counts(result.record))

    def test_validator_rejects_four_times(self):
        grid = {t: ["휴게"] * 14 for t in ("A", *NAMES)}
        for t in (1, 3, 5, 7):
            grid["A"][t] = "L3"
        record = imp.build_import_record(date(2026, 10, 9), Mode.FM, grid, {t: t for t in grid}, imp.ROSTER)
        rules = {e["rule"] for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True)}
        self.assertIn("H-17", rules)
        relaxed = {e["rule"] for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True, post_cap=False)}
        self.assertNotIn("H-17", relaxed)

    def test_weekday_first_manager_l3_not_counted(self):
        grid = {t: ["휴게"] * 14 for t in ("A", *NAMES)}
        for t in (0, 3, 5, 7):                            # 18시 L3 표기(실제 보안실 대기) + 3번
            grid["A"][t] = "L3"
        record = imp.build_import_record(date(2026, 10, 6), Mode.FM, grid, {t: t for t in grid}, imp.ROSTER)
        rules = {e["rule"] for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True)}
        self.assertNotIn("H-17", rules)

    def test_weekend_start_manager_rests_at_18(self):
        for absent in ((), ("3",), ("3", "4")):
            with self.subTest(absent=absent):
                result = run_schedule(ShiftRequest(date(2026, 10, 9), NightType.N4, Mode.FM, staff(absent)),
                                      HistorySelection(), SolveOptions(rules_version="2.20", seconds=20))
                self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
                first = next(r for r in result.record.assignments if r.employee_id == "A" and r.slot.index == 0)
                self.assertEqual(first.displayed_assignment.label, "휴게")
        grid = {t: ["휴게"] * 14 for t in ("A", *NAMES)}
        grid["A"][0] = "L3"                               # 위반표: 주말 시작 통제 18시 L3
        record = imp.build_import_record(date(2026, 10, 9), Mode.FM, grid, {t: t for t in grid}, imp.ROSTER)
        rules = {e["rule"] for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True)}
        self.assertIn("6-2-1", rules)

    def test_relaxed_only_for_two_full_absences(self):
        calls = []

        def fake(context, history, config):
            calls.append(config.relax_post_cap)
            solved = service.SolveResult("INFEASIBLE", None, [], False) if not config.relax_post_cap else \
                service.SolveResult("OPTIMAL", object(), [], False)
            return service.ServiceResult(context, solved, (), {}, None, "2.20")
        with patch.object(service, "_run_schedule_modes", side_effect=fake):
            two = run_schedule(ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, staff(("3", "4"))),
                               None, SolveOptions(rules_version="2.20"))
            self.assertTrue(two.post_cap_relaxed)
            self.assertEqual(calls, [False, True])
            calls.clear()
            one = run_schedule(ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, staff(("3",))),
                               None, SolveOptions(rules_version="2.20"))
            self.assertFalse(one.post_cap_relaxed)
            self.assertEqual(calls, [False])                 # 1명 결원은 해제하지 않음 = 해 없음 그대로


if __name__ == "__main__":
    unittest.main()
