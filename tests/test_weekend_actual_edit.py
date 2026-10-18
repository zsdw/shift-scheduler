"""주말 주간 저장본 실제 근무 수정 (2026-10-13 사용자 요청, 야간 저장본과 같은 흐름)."""
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from night_shift.weekend_day import WeekendSchedule, load, save_actual, stats

GRID = {'1': ['G1', 'I1', '휴게', 'G1', 'G2', '휴게', 'I1', 'L1', '순찰', 'G2'],
        '2': ['휴게', 'G1', 'G2', '휴게', 'G1', 'L1', '순찰', 'G1', 'L1', '휴게'],
        '3': ['G2', '휴게', 'G1', 'G2', '휴게', 'I1', 'L1', '순찰', 'I1', 'L1'],
        '4': ['I1', 'L1', '순찰', 'I1', 'L1', '휴게', 'G1', 'G2', '휴게', 'G1'],
        '5': ['L1', '순찰', 'I1', 'L1', '휴게', 'G1', 'G2', '휴게', 'G1', 'I1'],
        'A': ['휴게', 'G2', 'L1', '순찰', 'I1', 'G2', '휴게', 'I1', 'G2', '휴게']}
NAMES = {'A': '통제A', '1': '준호', '2': '광희', '3': '원종', '4': '제욱', '5': '만년'}


class ActualEditTests(unittest.TestCase):
    def test_save_keeps_source_backs_up_and_counts_fatigue(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = WeekendSchedule(day='2026-09-19', names=NAMES, grid={p: list(r) for p, r in GRID.items()})
            Path(tmp, '2026-09-19.json').write_text(json.dumps(
                {**asdict(s), 'source': 'excel-bulk', 'source_sheet': '26년09월19일(주)', 'note': '엑셀 원본',
                 'source_review': {'rows': []}, 'confirmed_at': '2026-10-11T23:25:28'}), encoding='utf-8')
            edited = load(tmp, '2026-09-19')
            edited.grid['1'][2], edited.grid['3'][2] = 'G1', '휴게'          # 10시 교환
            edited.annotations.append({'pid': '4', 't': 6, 'fatigue': 1, 'reason': '우천 순찰'})
            save_actual(tmp, edited, 2)
            data = json.loads(Path(tmp, '2026-09-19.json').read_text(encoding='utf-8'))
            self.assertEqual((data['source'], data['source_sheet'], data['final_save_method']),
                             ('excel-bulk', '26년09월19일(주)', 'screen-edit'))
            self.assertIn('실제 근무 수정 2칸', data['note'])
            self.assertTrue(data['note'].startswith('엑셀 원본'))
            self.assertEqual(len(list(Path(tmp, '.trash').glob('2026-09-19__before-edit-*.json'))), 1)
            again = load(tmp, '2026-09-19')
            self.assertEqual(again.grid['1'][2], 'G1')
            row = next(r for p, r in zip(again.grid, stats(again, 'FM')) if p == '4')
            self.assertEqual(row['기타 피로도'], 1)

    def test_sheet_marks_changed_and_annotation(self):
        from weekend_day_ui import sheet_html, weekend_notes
        s = WeekendSchedule(day='2026-09-19', names=NAMES, grid={p: list(r) for p, r in GRID.items()},
                            annotations=[{'pid': '4', 't': 6, 'fatigue': 1, 'reason': '우천 순찰'}])
        html = sheet_html(s, changed=frozenset({('1', 0)}))
        self.assertIn('#dc2626', html)
        self.assertIn('📝', html)
        self.assertTrue(any('우천 순찰' in n for n in weekend_notes(s)))


if __name__ == '__main__':
    unittest.main()
