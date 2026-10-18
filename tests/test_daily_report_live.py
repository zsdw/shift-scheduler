import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from night_shift import daily_report as dr, leave_schedule as ls, date_check

DAY = date(2026, 10, 8)


class LiveReportTests(unittest.TestCase):
    def test_latest_schedule_overrides_old_saved_report_without_writing_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            report = dr.build(DAY, [], dr.load_roster(store))
            dr.save_report(store, DAY, report['rows'], '예전작성자', report['rows'])
            before = dr.load_saved(store, DAY)
            ls.save_manual(store, '김광희', 'A', DAY, DAY, '연차')
            rows = date_check._report(store, DAY)[1]
            self.assertIn('김광희', next(r for r in rows if r['조'] == 'A조')['비고'])
            self.assertEqual(dr.load_saved(store, DAY), before)
            self.assertFalse(any(i['kind'] in ('unsaved', 'leave_changed') for i in date_check.review(store, DAY, {})))

    def test_ui_pc_mobile_updates_without_save(self):
        for view in ('pc', 'mobile'):
            # 2026-10-11부터 일보는 편성표 자료가 있는 날만 → 빈 검사 저장소에서는 자료 있는 날로 고정
            with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'NIGHT_SHIFT_HISTORY_DIR': folder}), \
                    patch('night_shift.order_source.document_available', return_value=True), \
                    patch('night_shift.order_source.latest_file', return_value=None):   # 바탕화면 실제 편성표 안 읽음
                at = AppTest.from_string(f"import streamlit as st\nfrom datetime import date\nimport daily_report_ui as ui\nst.query_params['view'] = {view!r}\nui.render(date(2026,10,8))")
                at.run()
                self.assertFalse(at.exception)
                self.assertFalse(any('일보 저장' in b.label or '계산값으로 되돌리기' in b.label for b in at.button))
                ls.save_manual(Path(folder), '김광희', 'A', DAY, DAY, '연차')
                at.run()
                self.assertFalse(at.exception)
                self.assertTrue(any('연차 1명(김광희)' in m.value for m in at.markdown))
                ls.delete_manual(Path(folder), ls.load_manual(Path(folder))[0]['id'])
                at.run()
                self.assertFalse(any('연차 1명(김광희)' in m.value for m in at.markdown))
