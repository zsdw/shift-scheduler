"""v2.18 regression tests: partial vacancy (1.5+ absences) and vacancy-2 manager policy.

Rulebook v2.18 §0-4-1, §8-3-1, §8-7, §14-2-1.
"""
import unittest
from dataclasses import replace
from datetime import date

from night_shift.models import AssignmentKind, HistoryInput, Mode, NightType
from night_shift.service import (
    HistorySelection, ShiftRequest, SolveOptions, StaffInput, build_context,
    run_reoptimization, run_schedule,
)
from night_shift.solver import planned_vacancy
from night_shift.validator import validate_first_trial


NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
FIRST_HALF_OFF = tuple(range(7, 14))   # 전반부 반차: 01시 출근
SECOND_HALF_OFF = tuple(range(0, 7))   # 후반부 반차: 01시 퇴근
OPTIONS = SolveOptions(rules_version="2.18", seconds=20)


def request(night, *, leave=(), half=None, a_present=True, mode=Mode.FM):
    """leave: full-day absentees. half: {employee_id: available slots}."""
    half = half or {}
    staff = [StaffInput("A", "통제", a_present, False, None, a_present)]
    for employee_id, name in NAMES.items():
        is_proxy = employee_id == "6" and not a_present
        present = employee_id not in leave
        staff.append(StaffInput(employee_id, name, present, not is_proxy,
                                int(employee_id) if present else None, is_proxy,
                                half.get(employee_id)))
    return ShiftRequest(date(2026, 9, 30), night, mode, tuple(staff))


def rows(result, employee_id):
    return {row.slot.index: row for row in result.record.assignments
            if row.employee_id == employee_id}


def stages(result):
    return [attempt["stage"] for attempt in result.solve_result.attempts if "stage" in attempt]


class PlannedVacancyDetectionTests(unittest.TestCase):
    """Pure availability arithmetic; no solver call."""

    def effective(self, **kwargs):
        return planned_vacancy(build_context(request(NightType.N1, **kwargs)))[0]

    def test_leave_plus_half_day_is_two(self):
        self.assertEqual(self.effective(leave=("1",), half={"2": SECOND_HALF_OFF}), 2)

    def test_opposite_half_days_stay_one(self):
        self.assertEqual(self.effective(half={"1": FIRST_HALF_OFF, "2": SECOND_HALF_OFF}), 1)

    def test_same_side_half_days_are_two(self):
        self.assertEqual(self.effective(half={"1": SECOND_HALF_OFF, "2": SECOND_HALF_OFF}), 2)

    def test_leave_plus_two_same_side_half_days_are_three(self):
        self.assertEqual(self.effective(leave=("1",), half={"2": SECOND_HALF_OFF,
                                                            "3": SECOND_HALF_OFF}), 3)


class V218ScheduleTests(unittest.TestCase):
    def solve(self, req):
        result = run_schedule(req, HistorySelection(), OPTIONS)
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.attempts)
        self.assertEqual(result.validation_errors, ())
        return result

    def assert_partial_flexible(self, result):
        self.assertTrue(result.context.partial_vacancy_profile)
        self.assertEqual(result.context.effective_mode, Mode.FLEXIBLE)
        self.assertIn("§0-4-1", result.context.mode_change_reason)

    def test_n1_leave_plus_second_half_switches_and_manager_works_07(self):
        result = self.solve(request(NightType.N1, leave=("1",), half={"2": SECOND_HALF_OFF}))
        self.assert_partial_flexible(result)
        manager = rows(result, "A")
        self.assertEqual((manager[11].actual_work_time_value, manager[11].actual_rest_time_value), (0, 1))
        self.assertEqual(manager[12].displayed_assignment.label, "G2")
        self.assertEqual(manager[13].actual_work_time_value, 1)
        self.assertIn(manager[13].displayed_assignment.label, ("L3", "I1"))
        # South gate at 18 only in the evening (§0-4-1 / four-worker profile).
        evening_gates = [row for row in result.record.assignments
                         if row.slot.index in (1, 2) and row.displayed_assignment.label in ("G2", "G3")]
        self.assertEqual(evening_gates, [])
        # §14-2-1: one patrol per available person.
        patrols = {p: sum(row.displayed_assignment.kind == AssignmentKind.PATROL
                          for row in rows(result, p).values()) for p in ("A", "2", "3", "4", "5", "6")}
        self.assertEqual(set(patrols.values()), {1})
        # §8-7: manager barrier participation is strongly avoided, not a privilege stage.
        self.assertEqual(stages(result)[0], "manager_barrier_avoidance")
        self.assertNotIn("manager_work", stages(result))
        self.assertFalse(any(row.barrier_install_flag or row.barrier_remove_flag
                             for row in manager.values()))

    def test_n1_leave_plus_first_half_switches_and_manager_rests_07(self):
        result = self.solve(request(NightType.N1, leave=("1",), half={"2": FIRST_HALF_OFF}))
        self.assert_partial_flexible(result)
        manager = rows(result, "A")
        self.assertEqual((manager[13].actual_work_time_value, manager[13].actual_rest_time_value), (0, 1))

    def test_n2_proxy_manager_with_half_day_switches(self):
        result = self.solve(request(NightType.N2, a_present=False, half={"2": SECOND_HALF_OFF}))
        self.assert_partial_flexible(result)

    def test_full_vacancy_two_n1_is_now_feasible(self):
        # Before v2.18 §8-3 (07 rest) and the 07 south gate made this impossible.
        result = self.solve(request(NightType.N1, leave=("1", "2")))
        self.assertFalse(result.context.partial_vacancy_profile)
        self.assertEqual(result.context.effective_mode, Mode.FLEXIBLE)
        manager = rows(result, "A")
        self.assertIn(manager[13].displayed_assignment.label, ("L3", "I1"))
        self.assertEqual(manager[13].actual_work_time_value, 1)

    def test_three_or_fewer_available_is_out_of_scope(self):
        with self.assertRaises(NotImplementedError):
            run_schedule(request(NightType.N1, leave=("1",),
                                 half={"2": SECOND_HALF_OFF, "3": SECOND_HALF_OFF}),
                         HistorySelection(), OPTIONS)

    def test_validator_rejects_manager_rest_at_07_when_four_general(self):
        # Negative test for §8-3-1.
        result = self.solve(request(NightType.N1, leave=("1",), half={"2": SECOND_HALF_OFF}))
        rest_row = next(row for row in result.record.assignments
                        if row.displayed_assignment.label == "휴게")
        manager_rest = replace(rest_row, employee_id="A", slot=rows(result, "A")[13].slot)
        tampered = replace(result.record, assignments=tuple(
            manager_rest if row.employee_id == "A" and row.slot.index == 13 else row
            for row in result.record.assignments))
        errors = validate_first_trial(tampered, HistoryInput((), ()), rules_v218=True)
        self.assertTrue(any(error["rule"] in ("§8-3-1", "H-02/§5") for error in errors), errors)

    def test_validator_rejects_missing_partial_flag(self):
        result = self.solve(request(NightType.N1, leave=("1",), half={"2": FIRST_HALF_OFF}))
        unflagged = replace(result.record, context=replace(result.record.context,
                                                           partial_vacancy_profile=False))
        errors = validate_first_trial(unflagged, HistoryInput((), ()), rules_v218=True)
        self.assertTrue(any(error["rule"] == "§0-4-1" for error in errors), errors)

    def test_reoptimization_keeps_original_fm_mode(self):
        base = self.solve(request(NightType.N2, leave=("1",)))
        self.assertFalse(base.context.partial_vacancy_profile)
        self.assertEqual(base.context.effective_mode, Mode.FM)
        revised = run_reoptimization(base, 7, "2", 7, HistorySelection(), OPTIONS,
                                     "후반부 반차 (01시 퇴근)")
        self.assertFalse(revised.context.partial_vacancy_profile)
        self.assertEqual(revised.context.effective_mode, Mode.FM)
        if revised.record is not None:
            self.assertEqual(revised.validation_errors, ())


if __name__ == "__main__":
    unittest.main()
