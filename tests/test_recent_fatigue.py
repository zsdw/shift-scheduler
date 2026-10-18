import unittest
import tempfile
from pathlib import Path
from datetime import date
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from night_shift import history_import as imp, history_store
from night_shift.models import Mode
import history_ui

class RecentFatigueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        for day in range(1,9):
            grid={p:["휴게"]*14 for p in ("A","1","2","3","4","5","6")}
            grid["1"][1]="I1"
            rec=imp.build_import_record(date(2026,10,day),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
            history_store.save_confirmed(self.folder,rec,"2.20")
    def test_only_previous_six_actuals_with_mobile_links(self):
        with patch.object(history_ui,"store_dir",return_value=self.folder):
            html=history_ui.recent_fatigue_html(date(2026,10,8),"mobile")
        self.assertNotIn('night_date=2026-10-01',html)
        self.assertNotIn('night_date=2026-10-08',html)
        for day in range(2,8):
            self.assertIn(f'night_date=2026-10-{day:02d}',html)
        self.assertEqual(html.count('target="_self"'),6)
        self.assertIn('view=mobile',html)
        self.assertIn('table-layout:fixed',html)
    def test_pc_mobile_date_navigation_and_render(self):
        source="""
from datetime import date
import streamlit as st
from history_ui import apply_fatigue_navigation, render_recent_fatigue
apply_fatigue_navigation()
st.write(st.session_state.get('shift_date'))
render_recent_fatigue(date(2026,10,8))
"""
        for view in ("pc","mobile"):
            with patch.dict('os.environ',{'NIGHT_SHIFT_HISTORY_DIR':str(self.folder)}):
                app=AppTest.from_string(source)
                app.query_params['view']=view
                app.query_params['night_date']='2026-10-04'
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state['shift_date'],date(2026,10,4))
                self.assertEqual(app.session_state['app_tab'],'🗓 근무표')
                self.assertEqual(app.query_params['view'],[view])
                self.assertNotIn('night_date',app.query_params)
                self.assertTrue(any('recent-fatigue' in m.value for m in app.markdown))

    def test_average_uses_day_mean_instead_of_partial_actual(self):
        from types import SimpleNamespace
        stats={p:SimpleNamespace(fatigue_value=12,available_time=14,is_manager=p=="A") for p in ("A","1","2","3","4","5","6")}
        stats["A"].fatigue_value=2
        stats["6"].fatigue_value=7
        stats["6"].available_time=7
        with patch.object(history_ui,"store_dir",return_value=self.folder), patch.object(history_ui,"calculate_all_stats",return_value=stats):
            html=history_ui.recent_fatigue_html(date(2026,10,8))
        self.assertEqual(html.count('<td>12<sup'),6)
        self.assertIn('실제 7점',html)
        footer=html.split('<tfoot>')[1].split('</tfoot>')[0]
        self.assertIn('<th>평균</th>',footer)
        self.assertEqual(footer.count('<td>12.00</td>'),6)   # 모두 같으면 색 없음
        self.assertNotIn('7.00',footer)
        self.assertNotIn('보상',html)

    def test_average_row_colors_highest_and_lowest(self):
        # 2번은 10/6·10/7, 3번은 10/5에 근무 3칸 추가 → 2번 평균 최고(주황), 근무 없는 4·5·6번 최저 동점(모두 파랑)
        for day,pid in ((6,"2"),(7,"2"),(5,"3")):
            grid={p:["휴게"]*14 for p in ("A","1","2","3","4","5","6")}
            grid["1"][1]="I1"
            grid[pid][2]="G1"; grid[pid][3]="G1"; grid[pid][4]="G2"
            rec=imp.build_import_record(date(2026,10,day),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
            history_store.save_confirmed(self.folder,rec,"2.20")
        with patch.object(history_ui,"store_dir",return_value=self.folder):
            html=history_ui.recent_fatigue_html(date(2026,10,8))
        cells=html.split('<tfoot>')[1].split('</tfoot>')[0].split('<td')[1:]
        self.assertNotIn('class=',cells[0])              # 통제A 제외
        self.assertIn('class="more"',cells[2])            # 2번
        self.assertEqual(sum('class="less"' in c for c in cells),3)
        self.assertEqual([i for i,c in enumerate(cells) if 'class="less"' in c],[4,5,6])