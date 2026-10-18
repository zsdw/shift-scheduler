import unittest
from dataclasses import replace
from datetime import date
from night_shift.models import Mode, NightType, HistoryInput
from night_shift.service import build_context, ShiftRequest
from night_shift.profiles import options_for, make_record
from night_shift.validator import validate_first_trial
from night_shift.actual_edit import _state
from tests.test_barrier_v2 import staff

class BarrierSingleTests(unittest.TestCase):
    def test_roles_and_accounting(self):
        for night in (NightType.N1, NightType.N4):
            for mode in (Mode.FM, Mode.FLEXIBLE):
                c=build_context(ShiftRequest(date(2026,10,10),night,mode,staff()))
                rows=options_for(c,'1',2)
                target='G2' if any(r.displayed_assignment.label=='G2' for r in rows) else 'I1'
                flagged=[r for r in rows if r.barrier_install_flag]
                self.assertEqual([r.displayed_assignment.label for r in flagged],[target])
                self.assertEqual(flagged[0].fatigue_value,2 if target=='G2' else 1)
                standby=next(r for r in rows if r.displayed_assignment.label=='보안실 대기')
                self.assertEqual((standby.fatigue_value,standby.actual_rest_time_value),(0,1))
                self.assertEqual([r.displayed_assignment.label for r in options_for(c,'1',10) if r.barrier_remove_flag],['I1'])
                with self.assertRaises(ValueError):make_record(c,'1',2,'보안실 대기',install=True)

    def test_historical_options_preserved(self):
        c=build_context(ShiftRequest(date(2026,10,8),NightType.N1,Mode.FM,staff()))
        self.assertEqual({r.displayed_assignment.label for r in options_for(c,'1',2) if r.barrier_install_flag},{'G2','보안실 대기'})

    def test_saved_records_and_rejection(self):
        from pathlib import Path
        from night_shift.history_store import actual_record
        for d in (9,10):
            record=actual_record(Path('history'),date(2026,10,d))
            self.assertEqual(sum(r.barrier_install_flag for r in record.assignments),1)
            remove=next(r for r in record.assignments if r.barrier_remove_flag)
            self.assertEqual((remove.displayed_assignment.label,remove.fatigue_value,remove.actual_rest_time_value),('I1',1,0))
            changed=_state(record,2,10,{'I1':'rest'})
            self.assertEqual(next(r for r in changed.assignments if r.barrier_remove_flag).fatigue_value,1)
            rows=tuple(replace(r,barrier_install_flag=True) if r.slot.index==2 and r.displayed_assignment.label=='보안실 대기' else r for r in record.assignments)
            self.assertIn('15-0',{e['rule'] for e in validate_first_trial(replace(record,assignments=rows),HistoryInput((),()),rules_v220=True)})

if __name__=='__main__':unittest.main()
