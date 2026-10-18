import unittest
from dataclasses import replace
from datetime import date, datetime

from night_shift.models import (
    Assignment, AssignmentKind, AssignmentRecord, Attendance, Employee,
    HistoryInput, Mode, NightType, Posture, RecordKind, ShiftContext,
    ShiftRecord, SLOTS,
)


def initial_context():
    # Synthetic identities/date, not imported real attendance or history.
    workers = tuple(Employee(f"test-{n}", f"Test {n}") for n in range(1, 7))
    return ShiftContext(
        date(2026, 7, 1), NightType.N1, Mode.FLEXIBLE, Mode.FLEXIBLE,
        workers + (Employee("test-A", "Test A"),),
        tuple(Attendance(w.employee_id, True, True, n, False)
              for n, w in enumerate(workers, 1))
        + (Attendance("test-A", True, False, None, True),),
    )


class ModelTests(unittest.TestCase):
    def test_initial_case_and_midnight(self):
        context = initial_context()
        self.assertEqual(sum(a.present and a.is_general_worker for a in context.attendance), 6)
        self.assertEqual(len(SLOTS), 14)
        self.assertEqual(SLOTS[6].starts_at(context.shift_start_date), datetime(2026, 7, 2, 0))
        self.assertEqual(SLOTS[-1].starts_at(context.shift_start_date), datetime(2026, 7, 2, 7))

    def test_display_actual_are_independent(self):
        row = AssignmentRecord(
            "test-1", SLOTS[13], Assignment(AssignmentKind.POST, "I1"),
            Assignment(AssignmentKind.POST, "L3"), 2, 1, 0,
            Posture.STANDING, True, True, False, False, False, False,
            Mode.FLEXIBLE, ("§7", "user-supplement-2026-09-27"),
        )
        self.assertNotEqual(row.displayed_assignment, row.actual_post_or_work_type)
        # The neighboring worker can also actually work L3 (§7 clarification).
        other = replace(row, employee_id="test-2", displayed_assignment=Assignment(AssignmentKind.POST, "L3"))
        self.assertEqual(row.actual_post_or_work_type, other.actual_post_or_work_type)

    def test_number_changes_do_not_change_identity(self):
        context = initial_context()
        a, b, *remaining = context.attendance
        changed = replace(context, attendance=(replace(a, display_number=2), replace(b, display_number=1), *remaining))
        self.assertEqual(context.employees, changed.employees)
        self.assertEqual(context.attendance[0].employee_id, changed.attendance[0].employee_id)

    def test_history_cannot_silently_use_plan(self):
        plan = ShiftRecord("test-plan", RecordKind.PLAN, initial_context(), ())
        with self.assertRaises(ValueError):
            HistoryInput((plan,), ())
        self.assertNotEqual(HistoryInput(None, None), HistoryInput((), ()))

    def test_duplicate_identity_rejected(self):
        context = initial_context()
        with self.assertRaises(ValueError):
            replace(context, employees=context.employees + (context.employees[0],))


if __name__ == "__main__":
    unittest.main()
