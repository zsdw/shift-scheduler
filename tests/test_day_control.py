import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from night_shift.day_control import control_e_slots
from night_shift import daily_report as dr


class ControlETests(unittest.TestCase):
    def test_saved_report_attendance(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            day = date(2026, 10, 2)
            report = dr.build(day, [], dr.load_roster(store))
            for note, expected in [('', [1,3,5,7,9]), ('야간지원 1명(최정식)', []),
                                   ('연차 1명(최정식)', []), ('연차 1명(김수환)', [1,3,5,7,9]),
                                   ('오전반차 1명(최정식)', [5,7,9]), ('오후반차 1명(최정식)', [1,3])]:
                rows = [dict(r) for r in report['rows']]
                rows[0]['비고'] = note
                dr.save_report(store, day, rows, '')
                self.assertEqual(control_e_slots(store, day), expected, note)
            self.assertEqual(control_e_slots(store, date(2026,10,3)), [])

    def test_html_and_save(self):
        from night_shift.day_shift import DaySchedule, save_day
        from day_ui import day_sheet_html
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            s = DaySchedule(date(2026,10,2), (), {})
            with patch('day_ui.store_dir', return_value=store):
                html = day_sheet_html(s)
                self.assertEqual(html.count("font-weight:700'>E</td>"), 5)
                self.assertEqual(html.count("font-weight:700'>A</td>"), 5)
                self.assertIn('통제E 최정식', html)
            path = save_day(store / 'day', s)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['control_e_slots'], [1,3,5,7,9])
