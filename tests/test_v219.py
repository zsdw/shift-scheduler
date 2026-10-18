"""v2.19 regression tests.

- §8-4-2 (v2.19): A on duty, at most one absence -> A's total fatigue is not
  above any full-time general worker and at most 2 points below.
- Candidate diversity: a regenerated schedule must differ from every previous
  one however the general-worker rows are matched to names (>=3 people x >=3 slots).
"""
import unittest
from dataclasses import replace
from datetime import date
from itertools import permutations

from app import exclusion_payloads
from night_shift.models import HistoryInput, Mode, NightType
from night_shift.service import (
    HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule,
)
from night_shift.validator import validate_first_trial


NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
OPTIONS = SolveOptions(rules_version="2.19", seconds=20)


def request(night, *, leave=(), a_present=True):
    staff = [StaffInput("A", "통제", a_present, False, None, a_present)]
    for employee_id, name in NAMES.items():
        is_proxy = employee_id == "6" and not a_present
        present = employee_id not in leave
        staff.append(StaffInput(employee_id, name, present, not is_proxy,
                                int(employee_id) if present else None, is_proxy))
    return ShiftRequest(date(2026, 9, 30), night, Mode.FM, tuple(staff))


def fatigue(result, employee_id):
    return sum(row.fatigue_value for row in result.record.assignments
               if row.employee_id == employee_id)


def general_ids(result):
    return [a.employee_id for a in result.context.attendance
            if a.present and a.is_general_worker]


def signature(result, employee_id):
    rows = sorted((row for row in result.record.assignments if row.employee_id == employee_id),
                  key=lambda row: row.slot.index)
    return [(row.displayed_assignment.label, row.actual_post_or_work_type.label,
             row.barrier_install_flag, row.barrier_remove_flag) for row in rows]


class V219FatigueGapTests(unittest.TestCase):
    def solve(self, req, options=OPTIONS):
        result = run_schedule(req, HistorySelection(), options)
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.attempts)
        return result

    def assert_a_lowest_within_two(self, result):
        a = fatigue(result, "A")
        for p in general_ids(result):
            gap = fatigue(result, p) - a
            self.assertTrue(0 <= gap <= 2, (p, fatigue(result, p), a))

    def test_n1_full_attendance(self):
        self.assert_a_lowest_within_two(self.solve(request(NightType.N1)))

    def test_n3_one_absence(self):
        self.assert_a_lowest_within_two(self.solve(request(NightType.N3, leave=("1",))))

    def test_proxy_manager_keeps_previous_rule(self):
        self.solve(request(NightType.N2, a_present=False))

    def test_validator_rejects_a_above_general(self):
        # Negative test: a v2.18 schedule where A's fatigue is outside
        # [general-2, general] must fail the v2.19 validator.
        old = self.solve(request(NightType.N1), SolveOptions(rules_version="2.18", seconds=20))
        a = fatigue(old, "A")
        outside = [p for p in general_ids(old) if not 0 <= fatigue(old, p) - a <= 2]
        if not outside:
            self.skipTest("v2.18 schedule already satisfies the v2.19 gap")
        errors = validate_first_trial(old.record, HistoryInput((), ()), rules_v219=True)
        self.assertTrue(any(error["rule"] == "8-4-2" for error in errors), errors)


class V219DiversityTests(unittest.TestCase):
    def test_regenerated_schedule_differs_under_every_name_matching(self):
        req = request(NightType.N1)
        first = run_schedule(req, HistorySelection(), OPTIONS)
        self.assertTrue(first.valid, first.validation_errors)
        second = run_schedule(req, HistorySelection(),
                              replace(OPTIONS, exclude_assignments=exclusion_payloads([first])))
        self.assertTrue(second.valid, second.validation_errors or second.solve_result.attempts)
        generals = general_ids(first)
        for order in permutations(generals):
            mapping = dict(zip(generals, order))
            mapping["A"] = "A"
            changed = 0
            for new_id, old_id in mapping.items():
                diff = sum(x != y for x, y in zip(signature(second, new_id), signature(first, old_id)))
                changed += diff >= 3
            self.assertGreaterEqual(changed, 3, order)


if __name__ == "__main__":
    unittest.main()
