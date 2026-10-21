import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from hashlib import sha256

from streamlit.testing.v1 import AppTest
from night_shift.day_shift import DayPerson,DaySchedule,save_day,load_day,rename_saved_person


class DayNameEditTests(unittest.TestCase):
    def make_saved(self,folder):
        day=date(2026,10,26); store=Path(folder)/'day'
        s=DaySchedule(day,(DayPerson('용준','용준','출근',3),DayPerson('성호','성호','출근',1)),
            {'용준':['G1']+['휴게']*9,'성호':['G2']*10},shuttle={0:'용준'},
            trainees={'교육생':'용준'}, emergency={'pid':'용준','events':[{'pid':'용준'}]},
            rule_exempt_names=('용준',),source_layout={'mapping':{'3':'용준'},'rows':[{'시간':'08:00','G1':'3'}]})
        save_day(store,s,extra={'source':'image-import','source_file':'original.png','source_hash':'original-hash',
            'source_attachment':{'path':'source.png'},'source_review':{'mapping':{'3':'용준'},'rows':[{'시간':'08:00','G1':'3'}]}})
        return store,day

    def test_rename_preserves_assignments_numbers_and_source_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,day=self.make_saved(tmp);path=store/f'{day}.json';raw=path.read_bytes()
            rename_saved_person(store,day,'용준','용주',sha256(raw).hexdigest())
            saved=load_day(store,day);s=saved['schedule']
            self.assertEqual(s.people[0].number,3)
            self.assertEqual((s.people[0].pid,s.people[0].name),('용주','용주'))
            self.assertEqual(s.grid['용주'],['G1']+['휴게']*9)
            self.assertEqual(s.grid['성호'],['G2']*10)
            self.assertEqual(s.shuttle[0],'용주')
            self.assertEqual(s.trainees,{'교육생':'용주'})
            self.assertEqual(s.emergency['events'][0]['pid'],'용주')
            self.assertEqual(s.rule_exempt_names,('용주',))
            self.assertEqual(saved['source_layout']['mapping']['3'],'용주')
            self.assertEqual(saved['source_review']['mapping']['3'],'용주')
            self.assertEqual(saved['source_review']['rows'],[{'시간':'08:00','G1':'3'}])
            self.assertEqual(saved['source_hash'],'original-hash')
            self.assertEqual(saved['source_attachment'],{'path':'source.png'})
            self.assertEqual(next((store/'.trash').glob('*.json')).read_bytes(),raw)

    def test_blank_duplicate_and_stale_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,day=self.make_saved(tmp);path=store/f'{day}.json';raw=path.read_bytes()
            for name,expected in [(' ',None),('성호',None),('용주','stale')]:
                with self.assertRaises(ValueError):rename_saved_person(store,day,'용준',name,expected)
                self.assertEqual(path.read_bytes(),raw)

    def test_pc_mobile_name_save_button(self):
        for view in ('pc','mobile'):
            with self.subTest(view=view),tempfile.TemporaryDirectory() as tmp:
                store,day=self.make_saved(tmp)
                source=f'''
from datetime import date
from pathlib import Path
from night_shift.day_shift import load_day
from day_ui import _rename_person_ui
base=load_day(Path({str(store)!r}),date(2026,10,26))['schedule']
_rename_person_ui(base,'test')
'''
                app=AppTest.from_string(source,default_timeout=30)
                app.query_params['view']=view
                with patch.dict('os.environ',{'NIGHT_SHIFT_HISTORY_DIR':tmp}):
                    app.run()
                    app.text_input(key='day_rename_name_test_용준').set_value('용주').run()
                    app.button(key='day_rename_save_test').click().run()
                self.assertFalse(app.exception,[e.message for e in app.exception])
                self.assertEqual(load_day(store,day)['schedule'].people[0].name,'용주')
