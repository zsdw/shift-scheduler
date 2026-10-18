import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from night_shift import date_check
from night_shift.calendar_info import document_day, PATTERN_START

class DocumentDaysTests(unittest.TestCase):
    def test_cycle_and_year_boundaries(self):
        for offset in range(-12,400):
            self.assertEqual(document_day(PATTERN_START+timedelta(days=offset)),offset%6 in (3,4))
        self.assertFalse(document_day(date(2026,10,9)))
        self.assertTrue(document_day(date(2026,10,10)))
        self.assertTrue(document_day(date(2026,10,11)))

    def test_review_only_mismatch_without_automatic_authority(self):
        report={'teams':{'주간조':'C조','야간조':'A조'}}
        roster=[{'이름':n,'소속':'A조','직책':'대원'} for n in ('한만년','김광희')]
        rows=[{'비고':'연차 1명(김광희)'}]
        with tempfile.TemporaryDirectory() as folder,patch.object(date_check,'_report',return_value=(report,rows,[],None,roster)):
            store=Path(folder)
            source={'night':{'names':{'1':'만년'},'controls':[]}}
            self.assertEqual(date_check.review(store,date(2026,10,10),source),[])
            source['night']['names']['2']='광희'
            issues=date_check.review(store,date(2026,10,10),source)
            mismatch=next(i for i in issues if i['kind']=='absent_listed')
            self.assertEqual(mismatch['level'],'error')
            labels=' '.join(c['label'] for c in mismatch['choices'])
            self.assertIn('근무표가 맞음',labels)
            self.assertIn('연차일정이 맞음',labels)
            self.assertFalse(any(i['level']=='auto' for i in issues))
            self.assertFalse(any(i['kind']=='order_source_missing' for i in issues))
            self.assertEqual(date_check.review(store,date(2026,10,9),source),[])

    def test_pages_pc_mobile_hide_downloads_outside_document_days(self):
        from streamlit.testing.v1 import AppTest
        for mobile in (False,True):
            for module,key in (('security_order_ui','order_day'),('daily_report_ui','daily_report_day')):
                for day in (date(2026,10,9),date(2026,10,10),date(2026,10,11)):
                    with self.subTest(mobile=mobile,module=module,day=day),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}),patch('mobile_ui.is_mobile',return_value=mobile),patch('night_shift.order_source.latest_file',return_value=None):
                        at=AppTest.from_string(f'import {module}\n{module}.page()',default_timeout=30)
                        at.session_state[key]=day
                        at.run()
                        self.assertFalse(at.exception,[e.value for e in at.exception])
                        self.assertEqual(bool(at.get('download_button')),document_day(day))
                        text=' '.join(m.value for m in at.markdown)
                        self.assertNotIn('서로 맞습니다',text)
                        self.assertNotIn('다시 확인이 필요합니다',text)

    def test_order_shows_any_day_with_schedule_data(self):
        """2026-10-11 사용자 요청: 명령서는 편성표 자료(엑셀·저장본)가 있는 날이면 A조 작성일이 아니어도 띄운다."""
        import json
        from streamlit.testing.v1 import AppTest
        from night_shift import order_source
        root=Path(__file__).resolve().parent
        for mobile in (False,True):
            with self.subTest(mobile=mobile),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}),patch('mobile_ui.is_mobile',return_value=mobile),patch('night_shift.order_source.latest_file',return_value=None):
                (Path(folder)/'day').mkdir()
                data=json.loads((root/'fixtures'/'day_2026-10-08_saved.json').read_text(encoding='utf-8'))
                data['date']='2026-10-09'
                (Path(folder)/'day'/'2026-10-09.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
                self.assertIn(date(2026,10,9),order_source.days_with_data(Path(folder)))
                at=AppTest.from_string('import security_order_ui\nsecurity_order_ui.page()',default_timeout=60)
                at.session_state['order_day']=date(2026,10,9)          # A조 작성일 아님
                at.run()
                self.assertFalse(at.exception,[e.value for e in at.exception])
                text=' '.join(c.value for c in at.caption)
                self.assertNotIn('편성표 자료(올린 엑셀·프로그램 저장본)가 없습니다',text)   # 명령서 화면이 열림
                # 자료끼리 다르면 기준 선택이 먼저(문서 대조), 같으면 바로 다운로드
                self.assertTrue(at.get('download_button') or '어느 쪽' in ' '.join(m.value for m in at.markdown)
                                or at.radio or at.button)

if __name__=='__main__':unittest.main()
