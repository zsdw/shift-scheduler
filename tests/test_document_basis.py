import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from night_shift import document_basis as basis, daily_report as dr
from night_shift.leave_schedule import save_text

DAY=date(2026,10,10)
def sources():
    return {'night':{'team':'A','sheet':'test','names':dict(zip(map(str,range(1,7)),['성호','광희','만년','준호','원종','제욱'])),
                     'cp':{'1':'혁준','2':'덕영','3':'철룡'},'controls':['A'],'cells':{'18':{'G1':'2','I1':'1','CP':'CP2'}}}}

class DocumentBasisTests(unittest.TestCase):
    def test_choices_shared_and_invalidated_without_changing_original(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder);save_text(store,'10월 10일(토)\nA조 김광희 사원 - 연차\n')
            original=(store/'leave_schedule.txt').read_bytes()
            src=sources()
            with patch('night_shift.order_source.sources_for',return_value=src):
                _,issues,stamp,choice=basis.state(store,DAY)
                self.assertTrue(issues);self.assertIsNone(choice)
                self.assertIsNone(basis.report_for(store,DAY))
                basis.save(store,DAY,stamp,'leave')
                leave=basis.report_for(store,DAY)
                self.assertEqual(leave['document_basis'],'leave')
                filtered=basis.sources_for_report(src,leave,dr.load_roster(store))
                self.assertNotIn('2',filtered['night']['names'])
                self.assertEqual(filtered['night']['cells']['18']['G1'],'')
                self.assertEqual(filtered['night']['cells']['18']['CP'],'CP2')
                self.assertIn('2',src['night']['names'])
                basis.save(store,DAY,stamp,'schedule')
                schedule=basis.report_for(store,DAY)
                row=lambda r:next(x for x in r['rows'] if x['행']==15)
                self.assertEqual(row(leave)['사고'],row(schedule)['사고']+1)
                self.assertEqual((store/'leave_schedule.txt').read_bytes(),original)
                src['night']['cells']['18']['G1']='3'
                self.assertIsNone(basis.state(store,DAY)[3])
                self.assertIsNone(basis.report_for(store,DAY))

    def test_choice_blocks_then_enables_both_pages_pc_mobile(self):
        from streamlit.testing.v1 import AppTest
        for mobile in (False,True):
            for module,key in (('daily_report_ui','daily_report_day'),('security_order_ui','order_day')):
                with self.subTest(mobile=mobile,module=module),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}),patch('mobile_ui.is_mobile',return_value=mobile),patch('night_shift.order_source.sources_for',side_effect=lambda *a:sources()),patch('night_shift.order_source.latest_file',return_value=Path('fake.xlsx')),patch('night_shift.order_source.read_day',side_effect=lambda *a:sources()):
                    save_text(Path(folder),'10월 10일(토)\nA조 김광희 사원 - 연차\n')
                    at=AppTest.from_string(f'import {module}\n{module}.page()',default_timeout=30)
                    at.session_state[key]=DAY;at.run()
                    self.assertFalse(at.exception,[e.value for e in at.exception])
                    self.assertFalse(at.get('download_button'))
                    chooser=next(r for r in at.radio if r.label=='작성 기준')
                    self.assertIsNone(chooser.value)
                    chooser.set_value('근무표 기준').run()
                    next(b for b in at.button if b.label=='선택한 기준으로 작성').click().run()
                    self.assertFalse(at.exception,[e.value for e in at.exception])
                    self.assertTrue(at.get('download_button'))

if __name__=='__main__':unittest.main()
