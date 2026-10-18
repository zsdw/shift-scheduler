"""Drag-and-drop edits: display-only cell swaps and person number swaps."""
import unittest
from datetime import date

from night_shift.models import HistoryInput, Mode, NightType
from night_shift.schedule_edit import (
    grid_payload, locked_through, swap_cells, swap_person_numbers, swap_person_schedules,
)
from night_shift.service import (
    HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_reoptimization, run_schedule,
)
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
OPTIONS = SolveOptions(rules_version="2.20", seconds=20)


def request():
    staff = [StaffInput("A", "통제", True, False, None, True)]
    for employee_id, name in NAMES.items():
        present = employee_id != "2"
        staff.append(StaffInput(employee_id, name, present, True,
                                int(employee_id) if present else None, False))
    return ShiftRequest(date(2026, 9, 30), NightType.N2, Mode.FM, tuple(staff))


class DragEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = run_schedule(request(), HistorySelection(), OPTIONS)
        assert base.valid, base.validation_errors
        cls.base = base
        # LOCK 18-20, 만년 leaves from 01:00.
        cls.result = run_reoptimization(base, 3, "1", 7, HistorySelection(), OPTIONS,
                                        "후반부 반차 (01시 퇴근)")
        assert cls.result.valid, cls.result.validation_errors

    def test_locked_and_unavailable_cells_cannot_move(self):
        self.assertEqual(locked_through(self.result), 2)
        with self.assertRaises(ValueError):
            swap_cells(self.result, {}, ("4", 1), ("5", 5))      # 19:00 is LOCKed
        with self.assertRaises(ValueError):
            swap_cells(self.result, {}, ("1", 8), ("5", 5))      # 만년 02:00 is ×

    def test_cell_swap_is_display_only_and_reversible(self):
        records_before = self.result.record.assignments
        view = swap_cells(self.result, {}, ("4", 5), ("5", 9))
        self.assertEqual(view, {"4|5": "5|9", "5|9": "4|5"})
        self.assertEqual(self.result.record.assignments, records_before)
        rows = {row["id"]: row for row in grid_payload(self.result, view)["rows"]}
        self.assertTrue(rows["4"]["cells"][5]["edited"])
        self.assertTrue(all(cell["locked"] for cell in rows["4"]["cells"][:3]))
        self.assertEqual(swap_cells(self.result, view, ("5", 9), ("4", 5)), {})

    def test_person_swap_moves_numbers_not_assignments(self):
        swapped = swap_person_numbers(self.result, "4", "6")
        numbers = {a.employee_id: a.display_number for a in swapped.context.attendance}
        self.assertEqual((numbers["4"], numbers["6"]), (6, 4))
        rows = lambda r, p: [(x.slot.index, x.displayed_assignment.label)
                             for x in r.record.assignments if x.employee_id == p]
        for p in ("4", "6"):
            self.assertEqual(rows(swapped, p), rows(self.result, p))
        errors = validate_first_trial(swapped.record, HistoryInput((), ()), rules_v220=True,
                                      reoptimization=True)
        self.assertEqual(errors, [])
        order = [row["id"] for row in grid_payload(swapped, {})["rows"]]
        self.assertLess(order.index("6"), order.index("4"))
        with self.assertRaises(ValueError):
            swap_person_numbers(self.result, "A", "4")

    def test_name_drag_keeps_schedule_rows_in_place(self):
        rows = lambda r, p: [(x.slot.index, x.displayed_assignment.label, x.fatigue_value)
                             for x in sorted((y for y in r.record.assignments if y.employee_id == p),
                                             key=lambda y: y.slot.index)]
        numbers = lambda r: {a.employee_id: a.display_number for a in r.context.attendance}
        swapped, reasons = swap_person_schedules(self.base, "4", "6")
        if swapped is None:
            self.assertTrue(reasons)
        else:
            self.assertEqual(swapped.validation_errors, ())
            self.assertEqual((numbers(swapped)["4"], numbers(swapped)["6"]),
                             (numbers(self.base)["6"], numbers(self.base)["4"]))
            self.assertEqual(rows(swapped, "4"), rows(self.base, "6"))   # the row stays at its position
            self.assertEqual(rows(swapped, "6"), rows(self.base, "4"))
        # Different availability (만년 leaves at 01) or a manager can never swap places.
        self.assertIsNone(swap_person_schedules(self.result, "1", "4")[0])
        self.assertIsNone(swap_person_schedules(self.base, "A", "4")[0])

    def test_regenerate_under_same_lock(self):
        from app import exclusion_payloads
        again = run_reoptimization(self.base, 3, "1", 7, HistorySelection(), OPTIONS,
                                   "후반부 반차 (01시 퇴근)", exclude=exclusion_payloads([self.result]))
        if again.record is None:
            self.assertEqual(again.solve_result.status, "INFEASIBLE")
            return
        self.assertTrue(again.valid, again.validation_errors)
        prefix = lambda r: sorted((x.employee_id, x.slot.index, x.displayed_assignment.label)
                                  for x in r.record.assignments if x.slot.index < 3)
        self.assertEqual(prefix(again), prefix(self.result))
        self.assertNotEqual(again.record.assignments, self.result.record.assignments)

    def test_flexible_schedule_outlines_00_04_without_rest_notes(self):
        staff = [StaffInput("A", "통제", True, False, None, True)]
        staff += [StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()]
        flexible = run_schedule(ShiftRequest(date(2026, 9, 30), NightType.N1, Mode.FLEXIBLE, tuple(staff)),
                                HistorySelection(), OPTIONS)
        self.assertTrue(flexible.valid, flexible.validation_errors)
        payload = grid_payload(flexible, {})
        self.assertEqual(payload["band"], (4, 10))      # 2026-10-13: 새 기본 I1 22~03시 → 22~04시 띠
        notes = " ".join(cell["notes"] for row in payload["rows"] for cell in row["cells"])
        self.assertNotIn("휴게성", notes)
        self.assertIsNone(grid_payload(self.base, {})["band"])   # FM: no band

    def test_sheet_meta_for_field_form_layout(self):
        # 2026-10-06 사용자 요청: 야간 표를 주간 편성표 모양으로. 번호·색·머리글은 같은 칸 정보에서 만든다
        sheet = grid_payload(self.base, {})["sheet"]
        self.assertEqual(sheet["title"], "야간 근무 편성표")
        self.assertEqual(len(sheet["hours"]), 14)
        self.assertEqual(sheet["hours"][6], "24:00")
        present = {a.employee_id for a in self.base.context.attendance if a.present}
        self.assertEqual(set(sheet["tokens"]), present)
        numbered = {a.employee_id: a.display_number for a in self.base.context.attendance if a.present}
        self.assertEqual({sheet["tokens"][e] for e, n in numbered.items() if n is None}, {"A"})
        self.assertNotEqual(sheet["colors"][next(e for e, n in numbered.items() if n == 1)],
                            sheet["colors"][next(e for e, n in numbered.items() if n == 3)])   # 1·3번 다른 색


if __name__ == "__main__":
    unittest.main()
