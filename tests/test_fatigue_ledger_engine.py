"""대표 야간·주말 실제 Solver의 장기 보상 연결 검사."""
import unittest
from dataclasses import replace
from datetime import date
from night_shift.service import (StaffInput, ShiftRequest, SolveOptions, HistorySelection,
                                 run_schedule, calculate_all_stats)
from night_shift.models import Mode, NightType
from tests.test_fatigue_ledger import LedgerTests
from night_shift.weekend_day import generate, validate, stats

NAMES = {'A':'통제A','1':'만년','2':'원종','3':'제욱','4':'광희','5':'성호','6':'준호'}


class LedgerEngineTests(unittest.TestCase):
    def test_night_below_one_debt_is_repaid_after_daily_balance(self):
        previous = LedgerTests().record(date(2026,10,4))
        staff = tuple(StaffInput(p,n,True,p!='A',None if p=='A' else int(p),p=='A') for p,n in NAMES.items())
        request=ShiftRequest(date(2026,10,27),NightType.N1,Mode.FM,staff)
        result=run_schedule(request,HistorySelection(long_term_records=(previous,)),
                            SolveOptions(rules_version='2.20',seconds=20,prefer_dual_mode=False))
        self.assertTrue(result.valid,(result.solve_result.status,result.validation_errors))
        stages={a.get('stage') for a in result.solve_result.attempts}
        self.assertIn('long_term_fatigue_worst',stages)
        self.assertNotIn('history_one_point_compensation',stages)
        values={p:s.fatigue_value for p,s in result.employee_stats.items() if p!='A'}
        self.assertLessEqual(max(values.values())-min(values.values()),1)
        self.assertEqual(values['6'],min(values.values()))

    def test_weekend_debt_before_personal_preferences(self):
        result,status=generate('2026-10-25',NAMES,'FM',seconds=20,history={'준호':2})
        self.assertIsNotNone(result,status)
        self.assertEqual(validate(result),[])
        values={p:r['피로도'] for p,r in zip(result.grid,stats(result,'FM')) if p!='A'}
        self.assertLessEqual(max(values.values())-min(values.values()),1)
        self.assertEqual(values['6'],min(values.values()))

    def test_weekend_planned_and_emergency_with_ledger(self):
        from night_shift.weekend_day import reoptimize, partial_people
        base,status=generate('2026-10-25',NAMES,'FM',seconds=20,
                             half_days={'3':'오전반차'},history={})
        self.assertIsNotNone(base,status)
        result,status=reoptimize(base,4,'2','half',seconds=40,history={'준호':1})
        self.assertIsNotNone(result,status)
        self.assertEqual(validate(result,base),[])
        self.assertIn(status,('EMERGENCY_GAP_1','EMERGENCY_GAP_2'))
        for pid in base.grid:
            self.assertEqual(result.grid[pid][:5],base.grid[pid][:5])
        for mode in ('FM','유도리'):
            values=[r['피로도'] for p,r in zip(result.grid,stats(result,mode))
                    if p!='A' and p not in partial_people(result)]
            self.assertLessEqual(max(values)-min(values),1 if status.endswith('_1') else 2)


if __name__ == '__main__':
    unittest.main()
