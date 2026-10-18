import unittest
from dataclasses import replace
from datetime import date, datetime
from night_shift import history_import as imp
from night_shift.models import Mode, RecordKind, Assignment, AssignmentKind
from night_shift.service import HistorySelection, prepare_engine_inputs, calculate_all_stats
from night_shift.balance_notes import history_influence_lines

class NightCompensationTests(unittest.TestCase):
    def actual(self, day, partial=False):
        grid={p:["G1"]*14 for p in ("A","1","2","3","4","5","6")}
        r=imp.build_import_record(day,Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
        if partial:
            missing=Assignment(AssignmentKind.UNAVAILABLE,"근무불가")
            r=replace(r,context=replace(r.context,attendance=tuple(
                replace(a,available_slot_indices=tuple(range(7))) if a.employee_id=="6" else a
                for a in r.context.attendance)),assignments=tuple(
                replace(row,displayed_assignment=missing,actual_post_or_work_type=missing,
                        fatigue_value=0,actual_work_time_value=0,actual_rest_time_value=0)
                if row.employee_id=="6" and row.slot.index>=7 else row for row in r.assignments))
        return replace(r,kind=RecordKind.ACTUAL,confirmed_at=datetime(2026,10,13))

    def test_partial_uses_same_day_full_worker_average_without_mutation(self):
        r=self.actual(date(2026,10,8),True)
        before=calculate_all_stats(r)["6"].fatigue_value
        p=prepare_engine_inputs(self.actual(date(2026,10,15)).context,
                                HistorySelection(actual_records=(r,),actual_weights=(1.0,)))
        full=[s.fatigue_value for s in calculate_all_stats(r).values() if not s.is_manager and s.available_time==14]
        expected=sum(full)/len(full)
        self.assertEqual(p.history_fatigue_averages["6"],expected)
        self.assertEqual(p.historical_nights["6"],1)
        self.assertEqual(calculate_all_stats(r)["6"].fatigue_value,before)
        self.assertNotEqual(before,expected)

    def test_future_history_rejected(self):
        r=self.actual(date(2026,10,15))
        with self.assertRaises(ValueError):
            prepare_engine_inputs(r.context,HistorySelection(actual_records=(r,)))

    def test_below_threshold_no_compensation_note(self):
        r=self.actual(date(2026,10,15));p=prepare_engine_inputs(r.context,
            HistorySelection(actual_records=(self.actual(date(2026,10,8)),),actual_weights=(1.0,)))
        self.assertFalse(any("손해 보상" in line for line in history_influence_lines(r,calculate_all_stats(r),p)))
