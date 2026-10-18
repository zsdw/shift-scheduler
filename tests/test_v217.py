"""v2.17 regression tests: manager objective split (§0-5, §8-4, §8-4-1, §25-11).

v2.17 is an objective-policy change only. A on duty -> minimize A's actual work
time only. 준호 acting as manager (A absent) -> actual work, then fatigue.
No hard rule is removed or relaxed.
"""
import unittest
from dataclasses import replace
from datetime import date

from night_shift.models import HistoryInput, Mode, NightType
from night_shift.profiles import options_for
from night_shift.service import (
    SERVICE_API_VERSION, HistorySelection, ShiftRequest, SolveOptions, StaffInput,
    run_schedule,
)
from night_shift.solver import manager_objectives
from night_shift.validator import validate_first_trial


NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def request(*, a_present=True, night=NightType.N1):
    staff = [StaffInput("A", "통제", a_present, False, None, a_present)]
    for employee_id, name in NAMES.items():
        is_proxy = employee_id == "6" and not a_present
        staff.append(StaffInput(employee_id, name, True, not is_proxy,
                                int(employee_id), is_proxy))
    return ShiftRequest(date(2026, 9, 30), night, Mode.FM, tuple(staff))


def stages(result):
    return [attempt["stage"] for attempt in result.solve_result.attempts if "stage" in attempt]


def manager_work(result, manager_id):
    return sum(row.actual_work_time_value for row in result.record.assignments
               if row.employee_id == manager_id)


class ManagerObjectivePolicyTests(unittest.TestCase):
    """Pure policy table; does not depend on solver timing."""

    def names(self, **kwargs):
        return [name for name, _ in manager_objectives("work", "fatigue", **kwargs)]

    def test_a_on_duty_uses_actual_work_only(self):
        self.assertEqual(self.names(rules_v217=True, manager_is_proxy=False),
                         ["manager_work"])

    def test_junho_proxy_keeps_work_then_fatigue(self):
        self.assertEqual(self.names(rules_v217=True, manager_is_proxy=True),
                         ["manager_work", "manager_fatigue"])

    def test_pre_v217_behaviour_is_unchanged(self):
        for proxy in (False, True):
            self.assertEqual(self.names(rules_v217=False, manager_is_proxy=proxy),
                             ["manager_work", "manager_fatigue"])


class V217ScheduleTests(unittest.TestCase):
    def solve(self, version, **kwargs):
        result = run_schedule(request(**kwargs), HistorySelection(),
                              SolveOptions(rules_version=version, seconds=15))
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.attempts)
        self.assertEqual(result.validation_errors, ())
        return result

    def test_service_reports_v217_or_later(self):
        major_minor = tuple(int(x) for x in SERVICE_API_VERSION.split(".")[:2])
        self.assertGreaterEqual(major_minor, (2, 17))

    def test_a_on_duty_has_no_manager_fatigue_stage(self):
        result = self.solve("2.17")
        self.assertEqual(result.rules_version, "2.17")
        self.assertEqual(stages(result)[0], "post_coverage")             # 17-2: 하드 바로 다음
        self.assertEqual([s for s in stages(result) if s != "post_coverage"][0], "manager_work")
        self.assertNotIn("manager_fatigue", stages(result))

    def test_a_minimum_work_matches_v216(self):
        # Removing only the fatigue tie-breaker cannot change A's minimum work.
        v216 = self.solve("2.16")
        v217 = self.solve("2.17")
        self.assertIn("manager_fatigue", stages(v216))
        self.assertEqual(manager_work(v217, "A"), manager_work(v216, "A"))

    def test_junho_proxy_keeps_fatigue_tie_breaker(self):
        result = self.solve("2.17", a_present=False)
        self.assertEqual([s for s in stages(result) if s != "post_coverage"][:2], ["manager_work", "manager_fatigue"])

    def test_n1_manager_07_rest_hard_rule_still_rejects_violation(self):
        # Negative test: v2.17 must not weaken §8-3 (N1/N3 manager 07 rest).
        result = self.solve("2.17")
        record = result.record
        work_row = next(row for row in options_for(record.context, "A", 13, patrol_standing=True)
                        if row.actual_work_time_value == 1)
        tampered = replace(record, assignments=tuple(
            work_row if row.employee_id == "A" and row.slot.index == 13 else row
            for row in record.assignments))
        errors = validate_first_trial(tampered, HistoryInput((), ()), rules_v216=True)
        self.assertTrue(any(error["rule"] == "§8-3" for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
