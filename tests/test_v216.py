import unittest
from datetime import date

from app import friendly_exception_message, solver_failure_message
from night_shift.models import Mode, NightType
from night_shift.service import (
    HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_reoptimization,
    run_schedule,
)


class V216Tests(unittest.TestCase):
    @staticmethod
    def request(*, first_half_employee=None, numbers=None):
        names = ("만년", "원종", "제욱", "광희", "성호", "준호")
        numbers = numbers or {str(index): index for index in range(1, 7)}
        staff = [StaffInput("A", "통제", True, False, None, True)]
        staff.extend(
            StaffInput(str(index), name, True, True, numbers[str(index)], False,
                       tuple(range(7, 14)) if str(index) == first_half_employee else None)
            for index, name in enumerate(names, 1)
        )
        return ShiftRequest(date(2026, 9, 29), NightType.N1, Mode.FM, tuple(staff))

    def test_normal_v216_schedule_keeps_v215_hard_rules(self):
        result = run_schedule(
            self.request(),
            HistorySelection(), SolveOptions(rules_version="2.16", seconds=15),
        )
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.attempts)
        self.assertEqual(result.rules_version, "2.16")
        self.assertEqual(result.validation_errors, ())

    def test_operator_messages_hide_python_exception_names(self):
        message = friendly_exception_message(
            AttributeError("'ShiftContext' object has no attribute 'staff'"), "긴급 재편성")
        self.assertNotIn("AttributeError", message)
        self.assertNotIn("context.staff", message)
        self.assertIn("내부 정보", message)
        self.assertIn("해가 없습니다", solver_failure_message("INFEASIBLE"))
        self.assertIn("해가 없다고 확정된 것은 아니", solver_failure_message("UNKNOWN"))

    def test_existing_half_day_then_number_6_mannyeon_01_departure(self):
        numbers = {"1": 6, "2": 3, "3": 2, "4": 5, "5": 4, "6": 1}
        options = SolveOptions(rules_version="2.16", seconds=15)
        base = run_schedule(self.request(first_half_employee="3", numbers=numbers),
                            HistorySelection(), options)
        self.assertTrue(base.valid)
        revised = run_reoptimization(base, 1, "1", 7, HistorySelection(), options,
                                     "후반부 반차 (01시 퇴근)")
        self.assertTrue(revised.valid, revised.validation_errors)
        self.assertEqual(revised.validation_errors, ())
        self.assertEqual(revised.employee_stats["1"].display_number, 6)

    def test_infeasible_emergency_exit_has_plain_language_diagnosis(self):
        options = SolveOptions(rules_version="2.16", seconds=8)
        base = run_schedule(self.request(first_half_employee="3"),
                            HistorySelection(), options)
        self.assertTrue(base.valid)
        failed = run_reoptimization(base, 1, "1", 1, HistorySelection(), options,
                                    "긴급 이탈 (19시부터)")
        self.assertEqual(failed.solve_result.status, "INFEASIBLE")
        self.assertFalse(failed.valid)
        self.assertIsNotNone(failed.failure_diagnosis)
        self.assertIn("해가 없습니다", failed.failure_diagnosis.title)
        self.assertIn("대체인력", failed.failure_diagnosis.next_action)


if __name__ == "__main__":
    unittest.main()
