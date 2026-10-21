"""이름을 고친 주간 이미지 확인본은 빈 배정 때문에 저장 버튼을 숨기지 않는다."""
import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from io import BytesIO

from PIL import Image
from streamlit.testing.v1 import AppTest
from night_shift import schedule_image_import as images
from night_shift.day_shift import load_day


class ImageSaveEditedTests(unittest.TestCase):
    def test_missing_duty_is_rest_but_leave_and_known_auxiliary_are_preserved(self):
        rows=[{'시간':f'{h:02d}:00','G1':'1','휴게':'2','4C':''} for h in range(8,18)]
        rows[0]['G2']='2';rows[0]['휴게']=''
        rows[5]['휴게']='';rows[5]['4C']='A.2'
        rows[6]['휴게']=''
        names={'1':'성호','2':'용주','3':'여진'}
        schedule=images.build_day(date(2026,10,26),rows,names,
            statuses={'1':'출근','2':'출근','3':'연차'},allow_unassigned=True)
        self.assertEqual(schedule.grid['용주'][0],'G2')
        self.assertEqual(schedule.grid['용주'][5],'교육')
        self.assertEqual(schedule.grid['용주'][6],'휴게')
        self.assertEqual(schedule.grid['여진'],[None]*10)
        self.assertNotIn('3',schedule.source_layout['applied_rows'][6]['휴게'].split('.'))

    def test_weekend_missing_duty_is_rest_for_worker_and_manager(self):
        rows=[{'시간':f'{h:02d}:00','G1':'1','휴게':'A.2'} for h in range(8,18)]
        rows[5]['휴게']=''
        schedule=images.build_day(date(2026,10,25),rows,{'1':'성호','2':'용주'},
            kind='weekend_day',allow_unassigned=True)
        self.assertEqual(schedule.grid['2'][5],'휴게')
        self.assertEqual(schedule.grid['A'][5],'휴게')

    def test_corrected_names_and_missing_assignment_save_on_pc_and_mobile(self):
        b=BytesIO(); Image.new('RGB',(20,20),'white').save(b,'PNG'); data=b.getvalue()
        digest=hashlib.sha256(data).hexdigest(); key='image_review_'+digest[:12]
        rows=[{'시간':f'{h:02d}:00','G1':'1','휴게':'2','CP':''} for h in range(8,18)]
        rows[5]['휴게']=''; rows[6]['CP']=images.UNKNOWN
        draft=images.ImageDraft(date(2026,10,26),'day','A',{'1':'성호','2':'성호'},[],rows,[],digest,'')
        for view in ('pc','mobile'):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder:
                source=f'''
import streamlit as st
from types import SimpleNamespace
from image_import_ui import render_image_review
render_image_review(SimpleNamespace(name='review.png'),{data!r},{digest!r})
'''
                app=AppTest.from_string(source,default_timeout=30)
                app.query_params['view']=view
                app.session_state['schedule_image_draft']=(digest,draft)
                def run():
                    with patch.dict('os.environ',{'NIGHT_SHIFT_HISTORY_DIR':folder}):
                        app.run()
                    self.assertFalse(app.exception,[e.message for e in app.exception])
                run()
                self.assertFalse(app.button(key=key+'_save_edited').disabled)
                self.assertTrue(any('같은 이름' in e.value for e in app.error))
                app.session_state[key+'_names']={'edited_rows':{1:{'이름':'용주'}},'added_rows':[],'deleted_rows':[]}
                run()
                self.assertFalse(app.error,[e.value for e in app.error])
                app.button(key=key+'_save_edited').click()
                app.session_state[key+'_names']={'edited_rows':{1:{'이름':'용주'}},'added_rows':[],'deleted_rows':[]}
                run()
                path=Path(folder)/'day'/'2026-10-26.json'
                self.assertTrue(path.exists(), {'errors':[e.value for e in app.error], 'files':[str(p) for p in Path(folder).rglob('*')], 'info':[e.value for e in app.info]})
                payload=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(payload['source_review']['mapping'],{'1':'성호','2':'용주'})
                self.assertEqual(payload['source_review']['rows'],rows)
                self.assertEqual(load_day(path.parent,date(2026,10,26))['schedule'].grid['용주'][5],'휴게')
                self.assertIn('2',payload['source_layout']['applied_rows'][5]['휴게'].split('.'))
                self.assertIn('확인 필요',payload['source_review']['rows'][6]['CP'])

    def test_default_builder_stays_strict(self):
        rows=[{'시간':f'{h:02d}:00','G1':'1','휴게':'2'} for h in range(8,18)]
        rows[5]['휴게']=''
        with self.assertRaisesRegex(ValueError,'13시.*배정을 읽지'):
            images.build_day(date(2026,10,26),rows,{'1':'성호','2':'용주'})

    def test_explicit_save_keeps_rest_only_edits_and_backs_up_previous(self):
        b=BytesIO(); Image.new('RGB',(20,20),'white').save(b,'PNG'); data=b.getvalue()
        rows=[{'시간':f'{h:02d}:00','G1':'1','휴게':'2','대기':''} for h in range(8,18)]
        names={'1':'성호','2':'용주'}
        draft=images.ImageDraft(date(2026,10,26),'day','A',names,[],rows,[],'','')
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder)
            def save():
                schedule=images.build_day(draft.day,rows,names,allow_unassigned=True)
                return images.save_day_image(store,schedule,draft,rows,names,data,'review.png',
                    images.fingerprint(store,draft.day),team='A',exact_edits=True)
            path=save(); original=path.read_bytes()
            rows[5]['휴게']=''; rows[5]['대기']='2'
            save()
            self.assertEqual(load_day(store,draft.day)['schedule'].grid['용주'][5],'대기')
            self.assertEqual(next((store/'.trash').glob('*.json')).read_bytes(),original)
            unchanged=path.read_bytes(); save()
            self.assertEqual(path.read_bytes(),unchanged)
