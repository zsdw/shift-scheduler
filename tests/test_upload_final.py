"""업로드 파일 최종 저장과 저장본 출처 표시: PC·폰, 주간·야간."""
import os
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from night_shift import bulk_import, history_store
from history_ui import upload_saved_label
from tests.test_bulk_leave import workbook, DAY_NAMES

APP=str(Path(__file__).resolve().parents[1]/'app.py')


class UploadFinalTests(unittest.TestCase):
    def test_upload_preview_drag_and_final_save_pc_mobile(self):
        from tests.test_history_import import field_book
        from hashlib import sha256
        from night_shift.history_import import ROSTER
        data=field_book()
        prefix='import_'+sha256(data+'야간'.encode()).hexdigest()[:12]
        class Upload:
            name='교환할표.xlsx'
            def getvalue(self):return data
        for view in ('pc','mobile'):
            with self.subTest(view=view),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}):
                at=AppTest.from_string('from import_ui import render_importer\nrender_importer()',default_timeout=30)
                at.query_params['view']=view
                def run(event=None):
                    def fake(component,**kw):
                        if component.name.endswith('upload_sheet'):
                            self.assertTrue(kw['data']['edit'])
                            return event
                        return None
                    with patch('streamlit.file_uploader',return_value=Upload()),patch('streamlit.components.v1.custom_component.CustomComponent.__call__',autospec=True,side_effect=fake):at.run()
                run()
                run({'kind':'swap','a':['1',0],'b':['2',0],'nonce':f'upload-{view}'})
                self.assertFalse(at.exception)
                draft=at.session_state['history_import_draft'][1]
                self.assertEqual((draft.grid['1'][0],draft.grid['2'][0]),('L3','G1'))
                at.checkbox(key=prefix+'_verified').check();run()
                at.button(key=prefix+'_save').click();run()
                actual=history_store.actual_record(Path(folder),date(2026,10,4))
                row=next(r for r in actual.assignments if r.employee_id=='2' and r.slot.index==0)
                self.assertEqual(row.displayed_assignment.label,'L3')

    def test_bulk_upload_preview_drag_then_save(self):
        data=workbook()
        class Upload:
            name='일괄교환.xlsx'
            def getvalue(self):return data
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}):
            at=AppTest.from_string('from import_ui import render_importer\nrender_importer()',default_timeout=30)
            def run(event=None):
                def fake(component,**kw):
                    if component.name.endswith('upload_night'):return event
                    return None
                with patch('streamlit.file_uploader',return_value=Upload()),patch('streamlit.components.v1.custom_component.CustomComponent.__call__',autospec=True,side_effect=fake):at.run()
            run()
            ready=[p for p in at.session_state['bulk_plans'] if p.record is not None]
            item=ready[0]
            a=next(r for r in item.record.assignments if r.employee_id=='1' and r.slot.index==0).displayed_assignment.label
            b=next(r for r in item.record.assignments if r.employee_id=='2' and r.slot.index==0).displayed_assignment.label
            run({'kind':'cell','source':['1',0],'target':['2',0],'nonce':'bulk-swap'})
            self.assertFalse(at.exception)
            at.button(key='bulk_apply').click();run()
            actual=history_store.actual_record(Path(folder),item.day)
            self.assertEqual(next(r for r in actual.assignments if r.employee_id=='1' and r.slot.index==0).displayed_assignment.label,b)
            self.assertEqual(next(r for r in actual.assignments if r.employee_id=='2' and r.slot.index==0).displayed_assignment.label,a)

    def test_saved_file_banner_pc_mobile_night_day(self):
        for view in ('pc','mobile'):
            with self.subTest(view=view),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}):
                night=Path(folder);day=night/'day'
                plans=bulk_import.plan(workbook(),night,day,file_name='최종.xlsx',day_roster=DAY_NAMES,force=True)
                bulk_import.apply(plans,night,day)
                at=AppTest.from_file(APP,default_timeout=30)
                at.query_params['view']=view
                at.session_state['shift_date']=date(2026,10,3)
                at.run()
                # 2026-10-07 결정(2.21.44): 출처는 안내 띄우기 대신 제목 괄호 '(엑셀저장본)'
                titles=lambda:[s.value for s in at.subheader]+[c.value for c in at.caption]+[m.value for m in at.markdown]
                self.assertFalse(at.exception)
                self.assertTrue(any('엑셀저장본' in t for t in titles()))
                at.session_state['shift_date']=date(2026,10,7)
                at.run()
                self.assertFalse(at.exception)
                self.assertTrue(any('엑셀저장본' in t for t in titles()))

    def test_legacy_filename_and_later_edit_label(self):
        label=upload_saved_label({'source':'excel-import','note':'가져온 파일: 기존.xlsx / 야간\n확인'})
        self.assertIn('기존.xlsx',label)
        self.assertIn('이후 화면 수정',upload_saved_label({'source':'image-import','source_file':'사진.jpg','edited_at':'2026-10-04'}))
        self.assertEqual(upload_saved_label({'source':'generated'}),'')


if __name__=='__main__':unittest.main()
