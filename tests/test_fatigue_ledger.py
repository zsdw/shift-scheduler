import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace, asdict
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
from ortools.sat.python import cp_model
from night_shift import fatigue_ledger as ledger, history_store
from night_shift.service import prepare_engine_inputs, HistorySelection
from tests.test_night_compensation import NightCompensationTests
from tests.test_weekend_actual_edit import GRID, NAMES
from night_shift.weekend_day import WeekendSchedule


class LedgerTests(unittest.TestCase):
    def record(self, day, partial=False):
        r = NightCompensationTests().actual(day, partial)
        return replace(r, assignments=tuple(replace(a, fatigue_value=a.fatigue_value + 1)
                       if a.employee_id == '6' and a.slot.index == 0 else a for a in r.assignments))

    def test_exact_zero_sum_start_and_long_horizon(self):
        days = [(date(2026,10,3), {'a':100,'b':0}),
                (date(2026,10,4), {'a':14,'b':13,'c':13}),
                (date(2030,1,1), {'a':13,'b':14,'c':13})]
        balances, entries = ledger.from_days(days, date(2030,1,2))
        self.assertEqual(balances['a'], Fraction(1,3))
        self.assertEqual(sum(balances.values()), 0)
        self.assertEqual(len(entries), 6)
        self.assertEqual(ledger.from_days(days, date(2026,10,4))[0], {})

    def test_partial_manager_and_proxy_excluded(self):
        r = self.record(date(2026,10,4), True)
        values = ledger.night_values(r)
        self.assertNotIn('준호', values)
        self.assertEqual(len(values), 5)
        full = self.record(date(2026,10,4))
        proxy = replace(full, context=replace(full.context, manager_handover=(7,'6')))
        self.assertNotIn('준호', ledger.night_values(proxy))

    def test_history_service_uses_all_records_and_names(self):
        r = self.record(date(2026,10,4))
        # 표시 번호가 달라도 직원 이름으로 장부를 현재 엔진 ID에 연결한다.
        current = replace(r.context, shift_start_date=date(2026,10,27),
                          attendance=tuple(replace(a,display_number=7-a.display_number)
                                           if a.display_number else a for a in r.context.attendance))
        p = prepare_engine_inputs(current, HistorySelection(long_term_records=(r,)))
        self.assertGreater(p.long_term_balances['6'], 0)
        self.assertEqual(sum(p.long_term_balances.values()), 0)

    def test_disk_rebuild_edit_delete_restore_and_no_double_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            day = date(2026,10,4)
            r = self.record(day)
            history_store.save_confirmed(store, r, '2.20')
            old_bytes = (store/f'{day}.json').read_bytes()
            before = ledger.read(store, day + timedelta(days=1))[0]
            self.assertEqual(ledger.read(store, day + timedelta(days=1))[0], before)
            self.assertEqual((store/f'{day}.json').read_bytes(), old_bytes)
            self.assertEqual(ledger.read(store, day)[0], {})
            history_store.save_edits(store, day, [{'type':'fatigue','cell':['6',0], 'value':0,'note':'실제 수정'}])
            changed = ledger.read(store, day + timedelta(days=1))[0]
            self.assertNotEqual(before, changed)
            history_store.save_edits(store, day, [{'type':'fatigue','cell':['6',0], 'value':0,'note':'실제 수정'}])
            self.assertEqual(ledger.read(store, day + timedelta(days=1))[0], changed)
            stored = (store/f'{day}.json').read_bytes()
            (store/f'{day}.json').unlink()
            self.assertEqual(ledger.read(store, day + timedelta(days=1))[0], {})
            (store/f'{day}.json').write_bytes(stored)
            self.assertEqual(ledger.read(store, day + timedelta(days=1))[0], changed)

    def test_kind_separation_and_weekend_partial_proxy_annotation(self):
        s = WeekendSchedule('2026-10-04', deepcopy(NAMES), deepcopy(GRID))
        values = ledger.weekend_values(s)
        annotated = replace(s, annotations=[{'pid':'1','t':0,'fatigue':2,'reason':'추가 부담'}])
        self.assertEqual(ledger.weekend_values(annotated)[NAMES['1']], values[NAMES['1']]+2)
        partial = replace(s, half_days={'1':'오전반차'}, a_half='오후반차', proxy='2')
        self.assertNotIn(NAMES['1'], ledger.weekend_values(partial))
        self.assertNotIn(NAMES['2'], ledger.weekend_values(partial))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'weekend_day').mkdir()
            (root/'weekend_day'/'2026-10-04.json').write_text(json.dumps(asdict(s)),encoding='utf-8')
            self.assertEqual(ledger.read(root,date(2026,10,5))[0], {})
            self.assertTrue(ledger.read(root/'weekend_day',date(2026,10,5),'weekend')[0])

    def test_corrupt_record_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'2026-10-04.json').write_text('{bad',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'2026-10-04'):
                ledger.read(tmp,date(2026,10,5))

    def test_subpoint_debt_before_other_preferences(self):
        model = cp_model.CpModel()
        a=model.NewIntVar(1,2,'a'); b=model.NewIntVar(1,2,'b')
        model.Add(a+b==3)
        model.Minimize(-1000000*a)  # 기존 선호가 a의 큰 피로도를 원해도 장부 우선
        goals=[v for _,v in ledger.objectives(model,{'a':a,'b':b}, {'a':Fraction(1,10),'b':-Fraction(1,10)})]
        def solve(probe, seconds):
            solver=cp_model.CpSolver()
            solver.parameters.max_time_in_seconds=seconds
            return solver, solver.Solve(probe)
        solver,status=ledger.optimize(model,goals,solve,3)
        self.assertIn(status,(cp_model.OPTIMAL,cp_model.FEASIBLE))
        self.assertEqual((solver.Value(a),solver.Value(b)),(1,2))

    def test_repayment(self):
        balances, _ = ledger.from_days([(date(2026,10,4),{'a':14,'b':13}),
                                        (date(2026,10,5),{'a':13,'b':14})], date(2026,10,6))
        self.assertEqual(balances,{'a':0,'b':0})

    def test_ui_pc_mobile_read_only(self):
        from streamlit.testing.v1 import AppTest
        for mobile in (False, True):
            with self.subTest(mobile=mobile), tempfile.TemporaryDirectory() as tmp:
                r=self.record(date(2026,10,4))
                history_store.save_confirmed(Path(tmp),r,'2.20')
                raw=(Path(tmp)/'2026-10-04.json').read_bytes()
                with patch('mobile_ui.is_mobile',return_value=mobile):
                    app=AppTest.from_string(f'''
from datetime import date
from night_shift.fatigue_ledger_ui import render
from night_shift.history_store import actual_record
from pathlib import Path
store=Path({tmp!r})
render(store,date(2026,10,5),current=actual_record(store,date(2026,10,4)))
''').run()
                self.assertFalse(app.exception,[e.value for e in app.exception])
                self.assertTrue(any('장기 피로도 손해 장부' in e.value for e in app.markdown))
                self.assertEqual((Path(tmp)/'2026-10-04.json').read_bytes(),raw)


if __name__ == '__main__':
    unittest.main()
