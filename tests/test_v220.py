"""v2.20 regression tests.

- §0-4-2 emergency switch: when re-optimization leaves four available general
  workers, the unlocked remainder uses flexible + vacancy-2 rules.
- H-11-2 patrol recovery ladder: one protected patrol per patroller.
- §21-8 diagnosis tries single rule families first.
"""
import unittest
from datetime import date

from night_shift.models import AssignmentKind, HistoryInput, Mode, NightType
from night_shift.service import (
    HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_reoptimization,
    run_schedule,
)
from night_shift.validator import validate_first_trial


NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
OPTIONS = SolveOptions(rules_version="2.20", seconds=20)
PATROL_SLOTS = (3, 4, 5, 7, 8, 9)


def request(night, *, leave=(), mode=Mode.FM):
    staff = [StaffInput("A", "통제", True, False, None, True)]
    for employee_id, name in NAMES.items():
        present = employee_id not in leave
        staff.append(StaffInput(employee_id, name, present, True,
                                int(employee_id) if present else None, False))
    return ShiftRequest(date(2026, 9, 30), night, mode, tuple(staff))


def rows(result, employee_id):
    return {row.slot.index: row for row in result.record.assignments
            if row.employee_id == employee_id}


class EmergencySwitchTests(unittest.TestCase):
    def base(self, night=NightType.N1, leave=("2",)):
        result = run_schedule(request(night, leave=leave), HistorySelection(), OPTIONS)
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.attempts)
        self.assertIsNone(result.context.flexible_from_slot)
        return result

    def assert_switched(self, revised, start):
        self.assertTrue(revised.valid, revised.validation_errors or revised.solve_result.attempts
                        or revised.failure_diagnosis)
        self.assertEqual(revised.validation_errors, ())
        self.assertEqual(revised.context.flexible_from_slot, start)
        self.assertIn("§0-4-2", revised.context.mode_change_reason)
        for row in revised.record.assignments:
            expected = Mode.FLEXIBLE if row.slot.index >= start else Mode.FM
            self.assertEqual(row.mode, expected, (row.employee_id, row.slot.index))

    def test_user_case_19_lock_second_half_leave(self):
        # N1 FM, 원종 on leave; at 19:00 제욱 becomes a second-half leave (01:00 out).
        revised = run_reoptimization(self.base(), 1, "3", 7, HistorySelection(), OPTIONS,
                                     "후반부 반차 (01시 퇴근)")
        self.assert_switched(revised, 1)
        # After the switch 00-03 I1 is rest-like (flexible §10-1).
        i1_night = [row for row in revised.record.assignments
                    if row.slot.index in (6, 7, 8, 9) and row.displayed_assignment.label == "I1"]
        self.assertTrue(i1_night)
        self.assertTrue(all(row.actual_work_time_value == 0 for row in i1_night))

    def test_22_lock_departure_from_01(self):
        revised = run_reoptimization(self.base(NightType.N2), 4, "3", 7, HistorySelection(), OPTIONS,
                                     "후반부 반차 (01시 퇴근)")
        self.assert_switched(revised, 4)

    def test_full_attendance_single_departure_keeps_fm(self):
        base = self.base(NightType.N2, leave=())
        revised = run_reoptimization(base, 4, "3", 7, HistorySelection(), OPTIONS,
                                     "후반부 반차 (01시 퇴근)")
        self.assertIsNone(revised.context.flexible_from_slot)
        self.assertEqual(revised.context.effective_mode, Mode.FM)

    def test_validator_rejects_switch_outside_reoptimization(self):
        revised = run_reoptimization(self.base(), 1, "3", 7, HistorySelection(), OPTIONS,
                                     "후반부 반차 (01시 퇴근)")
        self.assertIsNotNone(revised.record)
        errors = validate_first_trial(revised.record, HistoryInput((), ()), rules_v220=True)
        self.assertTrue(any(error["rule"] == "§0-4-2" for error in errors), errors)


class PatrolRecoveryLadderTests(unittest.TestCase):
    def test_vacancy_two_every_patroller_has_protected_recovery(self):
        result = run_schedule(request(NightType.N2, leave=("1", "2")), HistorySelection(), OPTIONS)
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.attempts)
        for employee_id in ("A", "3", "4", "5", "6"):
            person = rows(result, employee_id)
            windows = []
            for t in PATROL_SLOTS:
                if person[t].displayed_assignment.kind == AssignmentKind.PATROL:
                    rests = sum(person[j].actual_work_time_value == 0 and person[j].counts_as_post_patrol_rest
                                for j in (t + 1, t + 2))
                    windows.append(rests)
            if windows:
                self.assertGreaterEqual(max(windows), 1, (employee_id, windows))


class DiagnosisTests(unittest.TestCase):
    def test_three_remaining_general_workers_is_diagnosed(self):
        base = run_schedule(request(NightType.N2, leave=("1", "2")), HistorySelection(), OPTIONS)
        self.assertTrue(base.valid)
        failed = run_reoptimization(base, 1, "3", 1, HistorySelection(),
                                    SolveOptions(rules_version="2.20", seconds=8),
                                    "긴급 이탈 (19시부터)")
        self.assertFalse(failed.valid)
        self.assertIsNotNone(failed.failure_diagnosis)


if __name__ == "__main__":
    unittest.main()
