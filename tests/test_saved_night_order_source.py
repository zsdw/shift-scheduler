import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from night_shift import order_source
from night_shift.models import AssignmentKind

class SavedNightOrderSourceTests(unittest.TestCase):
    def test_saved_actual_excludes_absent_and_uses_display_numbers(self):
        day = date(2026,10,10)
        record = NS(context=NS(employees=[NS(employee_id='1',name='만년'),NS(employee_id='4',name='광희')],
                              attendance=[NS(employee_id='1',present=True,display_number=2,acts_as_manager=False),
                                          NS(employee_id='4',present=False,display_number=None,acts_as_manager=False)]),
                    assignments=[NS(employee_id='1',slot=NS(index=0),displayed_assignment=NS(kind=AssignmentKind.POST,label='G1'))])
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder); (store/'2026-10-10.json').write_text('{}')
            with patch('night_shift.history_store.actual_record',return_value=record) as actual, \
                 patch('night_shift.cp_schedule.for_day',return_value={}), \
                 patch('night_shift.daily_report.teams_for',return_value={'야간조':'A조'}):
                source=order_source.saved_night_source(store,day)
            actual.assert_called_once_with(store,day)
            self.assertEqual(source['names'],{'2':'만년'})
            self.assertEqual(source['cells']['18']['G1'],'2')
            self.assertTrue(source['program'])

    def test_saved_night_replaces_excel_and_ignores_excel_name_fixes(self):
        saved={'program':True,'names':{'2':'만년'}}
        with patch.object(order_source,'latest_file',return_value=Path('dummy.xlsx')), \
             patch.object(order_source,'read_day',return_value={'night':{'names':{'2':'광희'}}}), \
             patch.object(order_source,'saved_day_source',return_value=None), \
             patch.object(order_source,'saved_night_source',return_value=saved), \
             patch.object(order_source,'load_name_fixes',return_value={'2026-10-10':{'night':{'2':'광희'}}}):
            source=order_source.sources_for(Path('.'),date(2026,10,10))
        self.assertEqual(source['night']['names'],{'2':'만년'})
