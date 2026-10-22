import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import team_schedule_ui as view


def source():
    return {'day':'2026-10-23','shift':'night','team':'C','names':{'1':'승회','10':'세명'},
            'controls':['C'],'cells':{'20':{'G2':'10','휴게':'1.C.CP1'},
                '21':{'순찰':'C','휴게':'1.10'},'23':{'순찰':'1'},
                '4':{'I1':'1','휴게':'10.C'},'7':{'G1':'1','휴게':'10.CP1.C'}}}


class TeamScheduleTests(TestCase):
    def test_counts_multi_digit_cp_and_missing_slots(self):
        rows={r['근무자']:r for r in view.metrics(source())}
        self.assertEqual(rows['승회']['차단봉 철수'],1)
        self.assertEqual(rows['세명']['차단봉 설치'],1)
        self.assertEqual(rows['승회']['하층'],1)
        self.assertEqual(rows['통제C']['상층'],1)
        self.assertEqual(rows['세명']['막휴게'],1)
        self.assertEqual(rows['승회']['막휴게'],0)
        self.assertEqual(rows['승회']['피로도'],4)
        self.assertEqual(rows['승회']['휴게'],2)
        self.assertEqual(len(rows),3)  # CP1은 일반 1번 아님

    def test_post_takes_precedence_over_duplicate_rest(self):
        s=source();s['cells']['7']['휴게']='1.10'
        self.assertEqual(view.metrics(s)[0]['막휴게'],0)
        s['day']='2026-10-01'
        self.assertEqual(view.metrics(s)[0]['차단봉 철수'],0)  # 당시 대기 담당 기준

    def test_sources_separate_teams_and_never_read_a_history(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'order_source';p.mkdir()
            c=source();b={**c,'team':'B','shift':'day'}
            (p/'uploaded_sources.json').write_text(json.dumps({'sources':{'2026-10-23':{'night':c,'day':b}}}),encoding='utf-8')
            (Path(folder)/'2026-10-23.json').write_text('invalid A history',encoding='utf-8')
            self.assertEqual(list(view.sources(folder,'C')),[('2026-10-23','night')])
            self.assertEqual(list(view.sources(folder,'B')),[('2026-10-23','day')])
            total=view.totals([c,c])[0]
            self.assertEqual(total['근무횟수'],2)
            self.assertEqual(total['순찰'],2)

    def test_team_pages_without_rule_messages(self):
        from streamlit.testing.v1 import AppTest
        for team in ('B','C'):
            with self.subTest(team=team),patch.object(view,'sources',return_value={('2026-10-23','night'):source()}):
                at=AppTest.from_string(f"from datetime import date\nimport streamlit as st\nimport team_schedule_ui\nst.session_state['shift_date']=date(2026,10,23)\nteam_schedule_ui.page('{team}','unused')",default_timeout=15).run()
                self.assertFalse(at.exception,[e.value for e in at.exception])
                self.assertEqual(len(at.dataframe),3)
                self.assertFalse(at.error)
                self.assertFalse(at.warning)

    def test_mode_conversion_and_formula(self):
        from team_schedule_analysis import metrics,details
        s=source();s['cells']={'22':{'I1':'1'},'23':{'휴게':'1'},'0':{'휴게':'1'},'1':{'휴게':'1'}}
        fm=metrics(s,'FM')[0];flex=metrics(s,'유도리')[0]
        self.assertEqual(fm['피로도'],1)
        self.assertEqual(flex['피로도'],0)
        self.assertEqual(flex['휴게'],fm['휴게']+1)
        row=details(s,'유도리')[4]
        self.assertIn('휴게성 0점',row['계산'])
        s['shift']='day';s['day']='2026-10-24';s['cells']={'8':{'G2':'1'},'17':{'G2':'1'}}
        self.assertEqual(metrics(s,'FM')[0]['피로도'],4)
        self.assertEqual(metrics(s,'유도리')[0]['피로도'],0)
        self.assertEqual(metrics(s,'유도리')[0]['막휴게'],1)
        s['day']='2026-10-23'
        self.assertEqual(metrics(s,'FM'),metrics(s,'유도리'))

    def test_exports_keep_team_and_cells(self):
        from io import BytesIO
        from openpyxl import load_workbook
        from team_schedule_export import export
        from PIL import Image
        s=source()
        for shift,day in (('night','2026-10-23'),('day','2026-10-23'),('day','2026-10-24')):
            with self.subTest(shift=shift,day=day):
                s={**s,'shift':shift,'day':day}
                book=load_workbook(BytesIO(export(s,'xlsx')))
                texts=[c.value for row in book.active for c in row if isinstance(c.value,str)]
                self.assertTrue(any('C조' in t for t in texts))
                book.close()
                image=Image.open(BytesIO(export(s,'png')))
                self.assertGreater(image.width,500)

