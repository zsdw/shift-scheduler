import io,tempfile,unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch
from openpyxl import Workbook
from night_shift import history_import as imp,history_store
from night_shift.models import Mode,RecordKind
from night_shift.service import calculate_all_stats
from night_shift.schedule_image import render_png

def field_book():
    wb=Workbook();ws=wb.active;ws.title='야간'
    ws.append(['2026년 10월 04일 일요일 근무조 : A조'])
    ws.append(['통제A','1원종','2만년','3제욱','4광희','5성호','6준호'])
    ws.append(['근무시간','G1','L3','I1','G3','G2','G2(1)','G2(2)','CP','셔틀','순찰','보안실','휴게'])
    for t in range(14):
        patrol='A' if t==3 else '5' if t in imp.PATROLS else ''
        ws.append([f'{(18+t)%24:02}:00','1','2','3','','','','','CP1.CP3','CP3',patrol,'4','A.4.5.6'])
    stream=io.BytesIO();wb.save(stream);return stream.getvalue()

def record(draft):
    ids={token:next(e for e,n in imp.ROSTER.items() if n==name) for token,name in draft.mapping.items()}
    return imp.build_import_record(draft.day,Mode.FM,draft.grid,ids,imp.ROSTER)

class ImportTests(unittest.TestCase):
    def test_excel_mapping_midnight_and_unlisted_rest(self):
        draft=imp.parse_excel(field_book(),'야간')
        self.assertEqual(draft.day,date(2026,10,4))
        self.assertEqual(draft.mapping['1'],'원종')
        self.assertEqual(draft.grid['6'],['휴게']*14)
        self.assertEqual(draft.grid['4'],['보안실 대기']*14)
        actual=record(draft)
        row=next(r for r in actual.assignments if r.employee_id=='2' and r.slot.index==6)
        self.assertEqual(row.displayed_assignment.label,'G1')
        self.assertEqual(next(a for a in actual.context.attendance if a.employee_id=='2').display_number,1)

    def test_duplicate_or_ocr_missing_cannot_be_silently_saved(self):
        draft=imp.parse_excel(field_book(),'야간')
        cells=draft.raw;cells[0]['보안실']='1';cells[1]['I1']=''
        bad=imp.draft_from_cells(cells,draft.day)
        self.assertEqual(bad.grid['1'][0],'확인 필요')
        self.assertEqual(bad.grid['A'][1],'확인 필요')
        with self.assertRaises(ValueError):record(bad)

    def test_partial_or_duplicate_time_rejected(self):
        draft=imp.parse_excel(field_book(),'야간')
        with self.assertRaises(ValueError):imp.draft_from_cells(draft.raw[:-1])
        with self.assertRaises(ValueError):imp.draft_from_cells(draft.raw+[draft.raw[0]])

    def test_invalid_historical_rules_can_be_recorded_and_replaced_recoverably(self):
        original=record(imp.parse_excel(field_book(),'야간'))
        with tempfile.TemporaryDirectory() as folder:
            imp.save_import(folder,original,'excel-import','확인한 실제 기록')
            actual=history_store.actual_record(Path(folder),date(2026,10,4))
            self.assertEqual(actual.kind,RecordKind.ACTUAL)
            self.assertEqual(calculate_all_stats(actual)['2'].actual_work_time_value,14)
            fp=imp.fingerprint(folder,date(2026,10,4))
            imp.save_import(folder,original,'image-import','교체',fp)
            self.assertEqual(imp.fingerprint(folder,date(2026,10,4)),fp)
            self.assertEqual(len(history_store.list_trash(Path(folder))),0)
            draft=imp.parse_excel(field_book(),'야간');draft.grid['1'][0]='휴게'
            changed=record(draft)
            imp.save_import(folder,changed,'excel-import','실제 배정 변경',fp)
            self.assertEqual(len(history_store.list_trash(Path(folder))),1)
            self.assertIn('덮어씌워진 근무표',history_store.load(Path(folder),date(2026,10,4))['note'])
            with self.assertRaises(ValueError):imp.save_import(folder,original,'excel-import','오래된 화면',fp)

    def test_atomic_failure_keeps_existing_and_removes_temp(self):
        original=record(imp.parse_excel(field_book(),'야간'))
        with tempfile.TemporaryDirectory() as folder:
            imp.save_import(folder,original,'excel-import','first')
            fp=imp.fingerprint(folder,date(2026,10,4))
            draft=imp.parse_excel(field_book(),'야간');draft.grid['1'][0]='휴게';changed=record(draft)
            with patch('night_shift.history_import.os.replace',side_effect=OSError('시험')):
                with self.assertRaises(OSError):imp.save_import(folder,changed,'image-import','second',fp)
            self.assertEqual(imp.fingerprint(folder,date(2026,10,4)),fp)
            self.assertFalse(list(Path(folder).glob('.import-*.tmp')))

    def test_download_png_contains_full_field_layout(self):
        from PIL import Image
        content=render_png(record(imp.parse_excel(field_book(),'야간')))
        image=Image.open(io.BytesIO(content))
        self.assertEqual(image.size,(2224,1580))
        self.assertTrue(content.startswith(b'\x89PNG'))

    def test_person_export_layout(self):
        wb=Workbook();ws=wb.active;ws.append(['기준일',date(2026,10,4)])
        ws.append(['직원']+[f'{(18+t)%24:02}시' for t in range(14)])
        ws.append(['통제']+['휴게']*14)
        for e,name in list(imp.ROSTER.items())[1:]:ws.append([f'{e} {name}']+['I1\n실제 상태 메모']*14)
        buffer=io.BytesIO();wb.save(buffer)
        draft=imp.parse_excel(buffer.getvalue(),ws.title)
        self.assertEqual(draft.day,date(2026,10,4))
        self.assertEqual(draft.grid['3'],['I1']*14)

    def test_review_ui_requires_confirmation_and_writes_actual(self):
        import os
        from hashlib import sha256
        from streamlit.testing.v1 import AppTest
        class Upload:
            name='현장.xlsx'
            def getvalue(self):return data
        data=field_book();prefix='import_'+sha256(data+'야간'.encode()).hexdigest()[:12]
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}):
            at=AppTest.from_string('from import_ui import render_importer\nrender_importer()',default_timeout=30)
            def run():
                with patch('streamlit.file_uploader',return_value=Upload()):at.run()
            run()  # 업로드만 하면 자동 분석되어 최종 저장 버튼까지 표시된다.
            self.assertFalse(at.exception)
            self.assertTrue(at.button(key=prefix+'_save').disabled)
            self.assertFalse(history_store.list_dates(Path(folder)))
            at.checkbox(key=prefix+'_verified').check();run()
            self.assertFalse(at.button(key=prefix+'_save').disabled)
            at.button(key=prefix+'_save').click();run()
            self.assertFalse(at.exception)
            self.assertEqual(history_store.actual_record(Path(folder),date(2026,10,4)).kind,RecordKind.ACTUAL)
            saved=history_store.load(Path(folder),date(2026,10,4))
            self.assertEqual(saved['source_file'],'현장.xlsx')
            self.assertEqual(saved['final_save_method'],'upload')
            from history_ui import upload_saved_label
            self.assertIn('현장.xlsx',upload_saved_label(saved))
            # 이미 저장된 날짜도 같은 업로드 파일로 최종 저장할 수 있고 이전 기록은 복구 가능하다.
            self.assertFalse(at.button(key=prefix+'_save').disabled)
            at.button(key=prefix+'_save').click();run()
            self.assertEqual(len(history_store.list_trash(Path(folder))),0)

    @unittest.skipUnless(__import__('os').name=='nt','Windows 문자 인식 필요')
    def test_image_reads_single_A_cells(self):
        # 2026-10-04: Windows 한국어 문자 인식은 칸에 'A' 한 글자만 있으면 읽지 않았다 (10/3 현장 양식 이미지).
        expected={
         'A':['휴게','휴게','보안실 대기','상층순찰','휴게','휴게','L3','휴게','G1','I1','휴게','휴게','I1','휴게'],
         '1':['휴게','G1','보안실 대기','G1','보안실 대기','I1','휴게','보안실 대기','I1','G1','L3','보안실 대기','휴게','G1'],
         '2':['G1','휴게','L3','I1','휴게','L3','I1','L3','보안실 대기','하층순찰','휴게','휴게','휴게','휴게'],
         '3':['L3','보안실 대기','휴게','L3','G1','보안실 대기','G1','상층순찰','휴게','휴게','I1','L3','보안실 대기','휴게'],
         '4':['보안실 대기','L3','휴게','휴게','중층순찰','휴게','보안실 대기','G1','휴게','L3','보안실 대기','휴게','G1','I1'],
         '5':['I1','휴게','I1','휴게','I1','G1','휴게','I1','중층순찰','휴게','휴게','G1','L3','보안실 대기'],
         '6':['휴게','I1','G1','보안실 대기','L3','하층순찰','휴게','휴게','L3','보안실 대기','G1','I1','휴게','L3']}
        draft=imp.parse_image((Path(__file__).parent/'fixtures'/'night_2026-10-03_field.png').read_bytes())
        self.assertEqual(draft.day,date(2026,10,3))
        self.assertEqual(draft.grid,expected)
        self.assertFalse([w for w in draft.warnings if '읽' in w and '원본' in w and '이미지 인식 결과' not in w])

    @unittest.skipUnless(__import__('os').name=='nt','Windows 문자 인식 필요')
    def test_downloaded_image_round_trip_keeps_A_patrol(self):
        draft=imp.parse_image(render_png(record(imp.parse_excel(field_book(),'야간'))))
        self.assertEqual(draft.grid['A'][3],'상층순찰')                 # 21시 순찰 'A' 한 글자
        self.assertEqual(draft.grid['4'],['보안실 대기']*14)

if __name__=='__main__':unittest.main()
