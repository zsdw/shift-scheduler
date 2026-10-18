import unittest
from datetime import date

from night_shift.models import Mode, NightType
from night_shift.service import (
    HistorySelection, ShiftRequest, SolveOptions, StaffInput,
    build_context, calculate_employee_stats, prepare_engine_inputs, run_schedule,
)
from run_oct_n4_fm import GENERAL, NAMES, SOURCE_27


def request():
    staff = tuple(StaffInput(p, NAMES[p], True, True, int(p), False) for p in GENERAL)
    staff += (StaffInput("A", NAMES["A"], True, False, None, True),)
    return ShiftRequest(date(2026, 9, 28), NightType.N3, Mode.FM, staff)


def assumed_history():
    return HistorySelection(
        assumed_totals={name: dict(zip(GENERAL, values)) for name, values in SOURCE_27.items()},
        assumed_nights={p: int(p != "6") for p in GENERAL},
        previous_install_ids=("4",), previous_remove_ids=("A",), forbid_install_ids=("4",),
    )


class ServiceTests(unittest.TestCase):
    def test_ui_context_and_explicit_history_preparation(self):
        context = build_context(request())
        self.assertEqual((context.night_type, context.requested_mode, len(context.attendance)),
                         (NightType.N3, Mode.FM, 7))
        prepared = prepare_engine_inputs(context, assumed_history())
        self.assertEqual((prepared.engine_history.actual_nights, prepared.engine_history.barrier_entries), ((), ()))
        self.assertTrue(prepared.assumed_history_used)
        self.assertEqual(prepared.actual_record_count, 0)
        self.assertEqual(prepared.historical_totals["fatigue_value"]["4"], 16)
        self.assertEqual(prepared.historical_nights["6"], 0)
        self.assertEqual(prepared.forbid_install_ids, ("4",))
        self.assertEqual(prepared.previous_remove_ids, ("A",))

    def test_service_result_is_validated_and_has_reusable_statistics(self):
        outcome = run_schedule(request(), assumed_history(),
                               SolveOptions(rules_version="2.13", seconds=15,
                                            prioritize_history_within_daily_targets=True))
        self.assertTrue(outcome.valid, outcome.validation_errors or outcome.solve_result.attempts)
        self.assertEqual(len(outcome.record.assignments), 98)
        self.assertEqual(set(outcome.employee_stats), set(GENERAL) | {"A"})
        for person, stats in outcome.employee_stats.items():
            barrier_only = sum(r.employee_id == person and r.actual_post_or_work_type.kind.value == "barrier_only"
                               for r in outcome.record.assignments)          # 11-0: 차단봉만 한 칸은 실근무·실휴게 0
            self.assertEqual(stats.actual_work_time_value + stats.actual_rest_time_value + barrier_only, 14)
            self.assertEqual(sum(stats.displayed_counts.values()), 14)
            self.assertEqual(stats.displayed_post_total, sum(stats.displayed_counts.get(label, 0)
                                                             for label in ("G1", "L3", "I1", "G2", "G3", "G2(1)")))
            self.assertEqual(stats, calculate_employee_stats(outcome.record, person))
        self.assertFalse(any(r.employee_id == "4" and r.barrier_install_flag for r in outcome.record.assignments))

    def test_incomplete_assumed_history_is_rejected(self):
        context = build_context(request())
        with self.assertRaises(ValueError):
            prepare_engine_inputs(context, HistorySelection(assumed_totals={"fatigue_value": {"1": 1}},
                                                            assumed_nights={"1": 1}))


if __name__ == "__main__":
    unittest.main()
