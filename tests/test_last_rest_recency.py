import unittest
from datetime import date,datetime
from dataclasses import replace
from night_shift import history_import as imp
from night_shift.models import Mode,RecordKind,HistoryInput
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial
from night_shift.service import prepare_engine_inputs,HistorySelection

def record(day,recipient):
    grid={p:['G1']*14 for p in ('A','1','2','3','4','5','6')}
    grid[recipient][13]='휴게'
    r=imp.build_import_record(day,Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
    return replace(r,kind=RecordKind.ACTUAL,confirmed_at=datetime(2026,10,16))

class LastRestRecencyTests(unittest.TestCase):
    def test_independent_validator_rejects_next_attendance(self):
        prior=record(date(2026,10,15),'1');current=record(date(2026,10,22),'1')
        absent=record(date(2026,10,16),'2')
        absent=replace(absent,context=replace(absent.context,attendance=tuple(
            replace(a,present=False,available_slot_indices=None) if a.employee_id=='1' else a for a in absent.context.attendance)),
            assignments=tuple(r for r in absent.assignments if r.employee_id!='1'))
        errors=validate_first_trial(current,HistoryInput((),()),rules_v220=True,last_rest_records=(prior,absent))
        self.assertTrue(any(e['rule']=='16-next' for e in errors))
        prepared=prepare_engine_inputs(current.context,HistorySelection(last_rest_records=(prior,absent)))
        self.assertIn('1',prepared.forbid_last_rest_ids)
        errors=validate_first_trial(current,HistoryInput((),()),rules_v220=True,last_rest_records=(prior,absent),locked_cells=(('1',13),))
        self.assertFalse(any(e['rule']=='16-next' for e in errors))
    def test_oldest_recipient_is_first_solver_objective(self):
        past=tuple(record(date(2026,10,d),str(i)) for i,d in enumerate((3,9,10,15,16,21),1))
        current=record(date(2026,10,22),'5')
        solved=solve_first_trial(current.context,HistoryInput((),()),seconds=20,rules_v220=True,last_rest_records=past)
        self.assertIsNotNone(solved.record,solved.status)
        rest=[r.employee_id for r in solved.record.assignments if r.slot.index==13 and r.actual_rest_time_value==1 and r.employee_id!='A']
        self.assertEqual(rest,['1'])
        self.assertTrue(solved.attempts[0]['stage'].startswith('last_rest_oldest_'))
        self.assertFalse([e for e in validate_first_trial(solved.record,HistoryInput((),()),rules_v220=True,last_rest_records=past) if e['rule']=='16-next'])
