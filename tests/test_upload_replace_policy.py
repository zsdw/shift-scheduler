import json
import tempfile
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch
from night_shift.import_compare import identical, post_signature
from night_shift.leave_schedule import replace_uploaded_text, load
from tests.test_history_import import field_book, record
from night_shift import history_import, history_store

class UploadReplacePolicyTests(unittest.TestCase):
    def test_rest_standby_number_and_metadata_changes_keep_existing(self):
        old={'date':'2026-10-10','people':[{'pid':'만년','number':1}], 'grid':{'만년':['G1','휴게','대기']}}
        new={'date':'2026-10-10','people':[{'pid':'만년','number':4}], 'grid':{'만년':['G1','대기','휴게']},'note':'new'}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'2026-10-10.json'; path.write_text(json.dumps(old),encoding='utf-8')
            before=path.read_bytes()
            self.assertTrue(identical(path,new))
            self.assertEqual(path.read_bytes(),before)
            new['grid']['만년'][0]='L3'
            self.assertFalse(identical(path,new))

    def test_night_identical_posts_do_not_write_or_backup(self):
        draft=history_import.parse_excel(field_book(),'야간'); original=record(draft)
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder)
            path=history_store.save_confirmed(store,original,'2.20')
            data=json.loads(path.read_text(encoding='utf-8'))
            for row in data['plan']['assignments']:
                if row['displayed'][0]=='security_standby':
                    row['displayed']=['rest','휴게']
            path.write_text(json.dumps(data),encoding='utf-8')
            before=path.read_bytes()
            history_import.save_import(store,original,'excel-import','upload',history_import.fingerprint(store,draft.day))
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse((store/'.trash').exists())

    def test_night_name_or_hour_change_is_different(self):
        draft=history_import.parse_excel(field_book(),'야간'); data={'plan':history_store.record_to_json(record(draft))}
        other=json.loads(json.dumps(data)); next(r for r in other['plan']['assignments'] if r['displayed'][0]=='post')['slot']=13
        self.assertNotEqual(post_signature(data),post_signature(other))

    def test_leave_upload_replaces_manual_and_attendance_with_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder)
            old={'manual_leave.json':'[{"name":"김광희","start":"2026-10-10","end":"2026-10-10","kind":"연차"}]',
                 'attendance_fix.json':'{"2026-10-10":{"김광희":{"kind":"연차"}}}',
                 'leave_schedule.txt':'10월 10일(토)\nA조 김광희 사원 - 연차\n'}
            for filename,value in old.items(): (store/filename).write_text(value,encoding='utf-8')
            text='10월 10일(토)\nA조 이성호 사원 - 연차\n'
            with patch('night_shift.order_source.SOURCE_DIR',store/'no_source'):
                replace_uploaded_text(store,text)
            self.assertEqual((store/'leave_schedule.txt').read_text(encoding='utf-8'),text)
            self.assertEqual(json.loads((store/'manual_leave.json').read_text()),[])
            self.assertEqual(json.loads((store/'attendance_fix.json').read_text()),{})
            self.assertEqual(len(list((store/'.trash').iterdir())),2)
            self.assertFalse(list((store/'.trash').glob('*.txt')))
            self.assertFalse(any(e['name']=='김광희' for e in load(store)[date(2026,10,10)]))

    def test_invalid_leave_keeps_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder); path=store/'leave_schedule.txt';path.write_text('old')
            with self.assertRaises(ValueError): replace_uploaded_text(store,'unreadable')
            self.assertEqual(path.read_text(),'old')

    def test_upload_ui_replaces_in_pc_and_mobile(self):
        import os
        from streamlit.testing.v1 import AppTest
        script = """import streamlit as st
from types import SimpleNamespace
from import_ui import render_leave_text
render_leave_text(SimpleNamespace(getvalue=lambda: '10월 10일(토)\\nA조 이성호 사원 - 연차\\n'.encode('utf-8')))
"""
        for view in ('pc','mobile'):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder:
                store=Path(folder)
                (store/'manual_leave.json').write_text('[{"name":"김광희"}]',encoding='utf-8')
                with patch.dict(os.environ, {'NIGHT_SHIFT_HISTORY_DIR':folder}), patch('night_shift.order_source.SOURCE_DIR',store/'no_source'):
                    app=AppTest.from_string(script,default_timeout=15)
                    app.query_params['view']=view
                    app.run(); app.button(key='leave_save').click().run()
                    self.assertFalse(app.exception)
                self.assertEqual(json.loads((store/'manual_leave.json').read_text()),[])
                self.assertIn('이성호',(store/'leave_schedule.txt').read_text(encoding='utf-8'))
