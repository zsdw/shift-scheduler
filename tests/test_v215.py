import unittest
from datetime import date

from night_shift.models import AssignmentKind, Mode, NightType
from night_shift.service import (
    HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_reoptimization,
    run_schedule,
)


NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def request(available_slots):
    staff = [StaffInput("A", "통제", True, False, None, True)]
    staff.extend(StaffInput(employee_id, name, True, True, int(employee_id), False,
                            available_slots if employee_id == "1" else None)
                 for employee_id, name in NAMES.items())
    return ShiftRequest(date(2026, 9, 29), NightType.N1, Mode.FM, tuple(staff))


def request_with_mannyeon_as_number_6():
    numbers = {"1": 6, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5}
    staff = [StaffInput("A", "통제", True, False, None, True)]
    staff.extend(StaffInput(employee_id, name, True, True, numbers[employee_id], False)
                 for employee_id, name in NAMES.items())
    return ShiftRequest(date(2026, 9, 29), NightType.N1, Mode.FM, tuple(staff))


class V215Tests(unittest.TestCase):
    def solve(self, slots):
        result = run_schedule(request(slots), HistorySelection(),
                              SolveOptions(rules_version="2.15", seconds=15))
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.attempts)
        return result

    def test_first_half_leave_means_01_start_and_manager_07_rest(self):
        result = self.solve(tuple(range(7, 14)))
        rows = sorted((row for row in result.record.assignments if row.employee_id == "1"),
                      key=lambda row: row.slot.index)
        self.assertTrue(all(row.displayed_assignment.kind == AssignmentKind.UNAVAILABLE
                            and row.actual_work_time_value == row.actual_rest_time_value == 0
                            for row in rows[:7]))
        self.assertTrue(all(row.displayed_assignment.kind != AssignmentKind.UNAVAILABLE
                            for row in rows[7:]))
        self.assertEqual(result.employee_stats["1"].available_time, 7)
        manager_07 = next(row for row in result.record.assignments
                          if row.employee_id == "A" and row.slot.index == 13)
        self.assertEqual((manager_07.actual_work_time_value,
                          manager_07.actual_rest_time_value), (0, 1))

    def test_second_half_leave_means_01_departure(self):
        result = self.solve(tuple(range(0, 7)))
        rows = sorted((row for row in result.record.assignments if row.employee_id == "1"),
                      key=lambda row: row.slot.index)
        self.assertTrue(all(row.displayed_assignment.kind != AssignmentKind.UNAVAILABLE
                            for row in rows[:7]))
        self.assertTrue(all(row.displayed_assignment.kind == AssignmentKind.UNAVAILABLE
                            for row in rows[7:]))

    def test_emergency_reoptimization_locks_prefix_and_validates_whole_shift(self):
        original = self.solve(None)
        revised = run_reoptimization(
            original, reoptimization_start_index=1,
            unavailable_employee_id="1", unavailable_from_index=7,
            history=HistorySelection(),
            options=SolveOptions(rules_version="2.15", seconds=15),
            reason="후반부 반차 (01시 퇴근)",
        )
        self.assertTrue(revised.valid, revised.validation_errors or revised.solve_result.attempts)
        original_rows = {(row.employee_id, row.slot.index): row
                         for row in original.record.assignments}
        revised_rows = {(row.employee_id, row.slot.index): row
                        for row in revised.record.assignments}
        for employee_id in revised.employee_stats:
            self.assertEqual(revised_rows[employee_id, 0], original_rows[employee_id, 0])
        self.assertTrue(all(
            revised_rows["1", slot].displayed_assignment.kind == AssignmentKind.UNAVAILABLE
            for slot in range(7, 14)
        ))
        self.assertEqual(revised.record.source_plan_id, original.record.record_id)
        self.assertEqual(revised.rebalance_info.reoptimization_start_index, 1)

    def test_19_hour_number_6_mannyeon_second_half_leave_regression(self):
        options = SolveOptions(rules_version="2.15", seconds=15)
        original = run_schedule(request_with_mannyeon_as_number_6(),
                                HistorySelection(), options)
        self.assertTrue(original.valid, original.validation_errors)
        self.assertFalse(hasattr(original.context, "staff"))
        self.assertEqual(original.employee_stats["1"].display_number, 6)
        self.assertEqual(original.employee_stats["1"].name, "만년")

        revised = run_reoptimization(
            original,
            reoptimization_start_index=1,  # 19시부터, 18시는 LOCK
            unavailable_employee_id="1",  # 표시번호 6 만년
            unavailable_from_index=7,      # 01시 퇴근
            history=HistorySelection(),
            options=options,
            reason="후반부 반차 (01시 퇴근)",
        )

        self.assertTrue(revised.valid, revised.validation_errors or revised.solve_result.attempts)
        self.assertEqual(revised.validation_errors, ())
        self.assertEqual(revised.employee_stats["1"].display_number, 6)
        before = {(row.employee_id, row.slot.index): row
                  for row in original.record.assignments}
        after = {(row.employee_id, row.slot.index): row
                 for row in revised.record.assignments}
        for employee_id in revised.employee_stats:
            self.assertEqual(after[employee_id, 0], before[employee_id, 0])
        self.assertTrue(all(
            after["1", slot].displayed_assignment.kind == AssignmentKind.UNAVAILABLE
            for slot in range(7, 14)
        ))


if __name__ == "__main__":
    unittest.main()
