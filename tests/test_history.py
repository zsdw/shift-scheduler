"""Confirmed history store, actual-shift corrections and equal 5:5 weighting."""
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta

from night_shift import history_store
from night_shift.actual_edit import actual_checks, apply_edits, changed_cells
from night_shift.models import AssignmentKind, Mode, NightType, RecordKind
from night_shift.service import (
    HistorySelection, ShiftRequest, SolveOptions, StaffInput, calculate_all_stats,
    prepare_engine_inputs, run_schedule, build_context,
)

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
OPTIONS = SolveOptions(rules_version="2.20", seconds=20)


def request(day):
    staff = [StaffInput("A", "통제", True, False, None, True)]
    staff += [StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()]
    return ShiftRequest(day, NightType.N2, Mode.FM, tuple(staff))


def at_date(record, day):
    return replace(record, context=replace(record.context, shift_start_date=day))


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = run_schedule(request(date(2026, 10, 1)), HistorySelection(), OPTIONS)
        assert cls.base.valid, cls.base.validation_errors

    def setUp(self):
        self.store = tempfile.mkdtemp()

    def test_roundtrip_and_actual_defaults_to_plan(self):
        history_store.save_confirmed(self.store, self.base.record, "2.20")
        data = history_store.load(self.store, date(2026, 10, 1))
        self.assertEqual(data["plan_record"].assignments, self.base.record.assignments)
        self.assertEqual(data["plan_record"].context, self.base.record.context)
        actual = history_store.actual_record(self.store, date(2026, 10, 1))
        self.assertEqual(actual.kind, RecordKind.ACTUAL)
        self.assertIsNotNone(actual.confirmed_at)
        self.assertEqual(actual.assignments, self.base.record.assignments)

    def test_same_hour_swap_and_state_edit(self):
        plan = self.base.record
        rows = {(r.employee_id, r.slot.index): r for r in plan.assignments}
        worker = next(p for p in NAMES if rows[(p, 7)].displayed_assignment.kind == AssignmentKind.POST)
        rester = next(p for p in NAMES if rows[(p, 7)].displayed_assignment.label == "휴게")
        actual = apply_edits(plan, [{"type": "swap", "a": [worker, 7], "b": [rester, 7]}])
        self.assertEqual(changed_cells(plan, actual), {(worker, 7), (rester, 7)})
        before, after = calculate_all_stats(plan), calculate_all_stats(actual)
        self.assertEqual(after[worker].actual_work_time_value, before[worker].actual_work_time_value - 1)
        # FM planned, but I1 00-03 actually rest-like.
        relaxed = apply_edits(plan, [{"type": "state", "from": 6, "to": 9, "posts": {"I1": "rest"}}])
        i1 = [r for r in relaxed.assignments if 6 <= r.slot.index <= 9 and r.displayed_assignment.label == "I1"]
        self.assertTrue(i1 and all(r.actual_work_time_value == 0 and r.actual_rest_time_value == 1 for r in i1))
        self.assertIsInstance(actual_checks(relaxed), list)

    def test_cross_hour_swap_rejects_impossible_moves(self):
        plan = self.base.record
        patroller = next(r.employee_id for r in plan.assignments
                         if r.slot.index == 7 and r.displayed_assignment.kind == AssignmentKind.PATROL)
        other = next(r.employee_id for r in plan.assignments
                     if r.slot.index == 0 and r.employee_id != patroller)
        with self.assertRaises(ValueError):
            apply_edits(plan, [{"type": "swap", "a": [patroller, 7], "b": [other, 0]}])

    def test_cycle_weights_and_weighted_totals(self):
        self.assertEqual(history_store.cycle_weights(4), (0.25, 0.25, 0.25, 0.25))
        self.assertEqual(history_store.cycle_weights(2), (0.5, 0.5))
        days = [date(2026, 9, 20) + timedelta(days=i) for i in range(5)]
        for day in days:
            history_store.save_confirmed(self.store, at_date(self.base.record, day), "2.20")
        # Make the newest night differ so weighting is observable.
        history_store.save_edits(self.store, days[-1], [{"type": "state", "from": 6, "to": 9, "posts": {"I1": "rest"}}])
        selection = history_store.history_selection(self.store, date(2026, 10, 1))
        self.assertEqual(len(selection.actual_records), 4)
        self.assertEqual(selection.actual_records[0].context.shift_start_date, days[-1])
        prepared = prepare_engine_inputs(build_context(request(date(2026, 10, 1))), selection)
        stats = [calculate_all_stats(r) for r in selection.actual_records]
        for p in NAMES:
            expected = round(sum(w * s[p].fatigue_value for w, s in zip((0.25, 0.25, 0.25, 0.25), stats)) * 4)
            self.assertEqual(prepared.historical_totals["fatigue_value"][p], expected)
            self.assertEqual(prepared.historical_nights[p], 4)

    def test_generation_uses_stored_actual_history(self):
        for offset in (2, 1):
            history_store.save_confirmed(self.store, at_date(self.base.record, date(2026, 10, 1) - timedelta(days=offset)), "2.20")
        selection = history_store.history_selection(self.store, date(2026, 10, 1))
        result = run_schedule(request(date(2026, 10, 1)), selection, OPTIONS)
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.attempts)
        self.assertEqual(result.prepared_inputs.actual_record_count, 2)


    def test_latest_revision_overwrites_and_first_save_is_kept(self):
        day = date(2026, 10, 1)
        history_store.save_confirmed(self.store, self.base.record, "2.20")
        first = [{"type": "state", "from": 6, "to": 7, "posts": {"I1": "rest"}}]
        second = [{"type": "state", "from": 8, "to": 9, "posts": {"I1": "seated"}}]
        history_store.save_edits(self.store, day, first)
        history_store.save_edits(self.store, day, second)
        data = history_store.load(self.store, day)
        self.assertEqual(data["edits"], second)
        self.assertEqual(data["plan_record"].assignments, self.base.record.assignments)
        latest = history_store.record_from_json(data["latest"])
        self.assertEqual(latest.assignments, apply_edits(self.base.record, second).assignments)

    def test_delete_goes_to_trash_and_restores(self):
        day = date(2026, 10, 1)
        history_store.save_confirmed(self.store, self.base.record, "2.20")
        history_store.save_edits(self.store, day, [{"type": "state", "from": 6, "to": 7, "posts": {"I1": "rest"}}])
        history_store.delete_to_trash(self.store, day)
        self.assertEqual(history_store.list_dates(self.store), [])
        self.assertFalse(history_store.history_selection(self.store, date(2026, 10, 2)).actual_records)
        trash = history_store.list_trash(self.store)
        self.assertEqual([t["date"] for t in trash], [day])
        # A new confirmation for the same date blocks restore instead of overwriting it.
        history_store.save_confirmed(self.store, self.base.record, "2.20")
        with self.assertRaises(ValueError):
            history_store.restore_from_trash(self.store, trash[0]["name"])
        history_store.delete_to_trash(self.store, day)
        restored = history_store.restore_from_trash(self.store, trash[0]["name"])
        self.assertEqual(restored, day)
        self.assertEqual(len(history_store.load(self.store, day)["edits"]), 1)
        self.assertEqual(len(history_store.list_trash(self.store)), 1)
        self.assertEqual(history_store.empty_trash(self.store), 1)
        self.assertEqual(history_store.list_trash(self.store), [])
        self.assertEqual(history_store.list_dates(self.store), [day])

    def test_preconfirm_swap_is_validated(self):
        from night_shift.schedule_edit import swap_schedule_cells
        plan = self.base.record
        patroller = next(r.employee_id for r in plan.assignments
                         if r.slot.index == 7 and r.displayed_assignment.kind == AssignmentKind.PATROL)
        other = next(r.employee_id for r in plan.assignments
                     if r.slot.index == 0 and r.employee_id != patroller)
        new, reasons = swap_schedule_cells(self.base, (patroller, 7), (other, 0))
        self.assertIsNone(new)
        self.assertTrue(reasons)
        accepted = None
        people = list(NAMES)
        for t in range(3, 14):
            for i, a in enumerate(people):
                for b in people[i + 1:]:
                    result, reasons = swap_schedule_cells(self.base, (a, t), (b, t))
                    if result is not None and result.record.assignments != plan.assignments:
                        accepted = result
                        break
                    if result is None:
                        self.assertTrue(reasons)
                if accepted:
                    break
            if accepted:
                break
        self.assertIsNotNone(accepted)
        self.assertTrue(accepted.valid)
        self.assertEqual(accepted.validation_errors, ())

    def test_fatigue_override_with_note(self):
        from night_shift.actual_edit import cell_notes, describe_edit
        plan = self.base.record
        cell = next((r.employee_id, r.slot.index) for r in plan.assignments
                    if r.slot.index == 7 and r.displayed_assignment.label == "I1")
        edits = [{"type": "fatigue", "cell": list(cell), "value": 2, "note": "민원 대응"},
                 {"type": "state", "from": 6, "to": 9, "posts": {"I1": "rest"}}]
        actual = apply_edits(plan, edits)
        row = next(r for r in actual.assignments if (r.employee_id, r.slot.index) == cell)
        self.assertEqual(row.fatigue_value, 2)          # applied after the state edit
        self.assertEqual(cell_notes(edits)[cell]["note"], "민원 대응")
        self.assertIn("피로도 2", describe_edit(edits[0], {}))
        with self.assertRaises(ValueError):
            apply_edits(plan, [{"type": "fatigue", "cell": list(cell), "value": 3}])
        day = date(2026, 10, 1)
        history_store.save_confirmed(self.store, plan, "2.20")
        history_store.save_edits(self.store, day, edits)
        stored = history_store.actual_record(self.store, day)
        self.assertEqual(next(r for r in stored.assignments if (r.employee_id, r.slot.index) == cell).fatigue_value, 2)

    def test_manager_emergency_hands_over_to_junho(self):
        from night_shift.service import revalidate, run_reoptimization, seat_form_record
        outcome = run_reoptimization(self.base, 7, "A", 7, HistorySelection(), OPTIONS, "후반부 반차 (01시 퇴근)")
        self.assertTrue(outcome.valid, outcome.validation_errors or outcome.failure_diagnosis)
        self.assertEqual(outcome.context.manager_handover, (7, "6"))
        self.assertEqual(outcome.rebalance_info.unavailable_employee_id, "A")
        rows = {(r.employee_id, r.slot.index): r for r in outcome.record.assignments}
        base_rows = {(r.employee_id, r.slot.index): r for r in self.base.record.assignments}
        for t in range(7):
            self.assertEqual(rows["A", t], base_rows["A", t])      # LOCKed past untouched
            self.assertEqual(rows["6", t], base_rows["6", t])
        for t in range(7, 14):
            self.assertEqual(rows["A", t].displayed_assignment.kind, AssignmentKind.UNAVAILABLE)
            self.assertNotEqual(rows["6", t].displayed_assignment.kind, AssignmentKind.UNAVAILABLE)
        self.assertEqual(rows["6", 11].actual_work_time_value, 0)  # 준호 inherits the 05 manager rest
        self.assertEqual(revalidate(outcome, outcome.record).validation_errors, ())
        seat = seat_form_record(outcome.record)
        self.assertIsNone(seat.context.manager_handover)
        # Round trip through the history store keeps the handover.
        history_store.save_confirmed(self.store, outcome.record, "2.20")
        data = history_store.load(self.store, date(2026, 10, 1))
        self.assertEqual(data["plan_record"].context.manager_handover, (7, "6"))

    def test_lock_is_kept_for_saved_reoptimization(self):
        from night_shift.schedule_edit import record_grid_payload
        from night_shift.service import run_reoptimization
        day = date(2026, 10, 1)
        revised = run_reoptimization(self.base, 3, "1", 7, HistorySelection(), OPTIONS, "후반부 반차 (01시 퇴근)")
        self.assertTrue(revised.valid, revised.validation_errors)
        history_store.save_confirmed(self.store, revised.record, "2.20", rebalance=revised.rebalance_info)
        data = history_store.load(self.store, day)
        self.assertEqual(history_store.locked_through(data), 2)
        self.assertEqual(data["rebalance"]["employee"], "1")
        # Files saved before this change: recovered from the plan id.
        legacy = {"plan": {"record_id": "trial-2026-09-15-FM-rebalance-3"}}
        self.assertEqual(history_store.locked_through(legacy), 2)
        self.assertEqual(history_store.locked_through({"plan": {"record_id": "trial-2026-09-16-FM"}}), -1)
        payload = record_grid_payload(data["plan_record"], locked_through=2)
        cells = payload["rows"][1]["cells"]
        self.assertTrue(all(c["locked"] and not c["movable"] for c in cells[:3]))
        self.assertFalse(cells[3]["locked"])

    def test_monthly_leave_labels(self):
        from history_ui import _leave_label
        from night_shift.models import Attendance
        self.assertEqual(_leave_label(Attendance("1", False, True, None, False), None), "연차")
        self.assertEqual(_leave_label(Attendance("A", False, False, None, True), None), "결근")
        self.assertEqual(_leave_label(Attendance("1", True, True, 1, False, tuple(range(7, 14))), None), "전반부 반차")
        self.assertEqual(_leave_label(Attendance("1", True, True, 1, False, tuple(range(0, 7))), None), "후반부 반차")
        self.assertEqual(_leave_label(Attendance("A", True, False, None, True, tuple(range(0, 9))), (9, "6")),
                         "긴급 이탈 03시부터 · 준호 관리자 대행")
        self.assertIsNone(_leave_label(Attendance("1", True, True, 1, False), None))

    def test_three_cycle_duty_rates(self):
        from night_shift.service import duty_rates_from
        rates = duty_rates_from([self.base.record], tuple(NAMES))
        for p in NAMES:
            self.assertEqual(rates["barrier"][p], 0)  # 10/1 차단봉은 10/4 집계 시작 전
        history_store.save_confirmed(self.store, self.base.record, "2.20")
        selection = history_store.history_selection(self.store, date(2026, 10, 2))
        self.assertEqual(len(selection.duty_records), 1)
        prepared = prepare_engine_inputs(build_context(request(date(2026, 10, 2))), selection)
        self.assertEqual(prepared.duty_rates, rates)


if __name__ == "__main__":
    unittest.main()
