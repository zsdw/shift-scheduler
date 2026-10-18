"""주말 주간 표 제목 줄 FM·유도리 보기 버튼 (2026-10-16 사용자 요청, 야간과 같음)."""
import unittest

from night_shift.weekend_day import WeekendSchedule, stats
from tests.test_weekend_actual_edit import GRID, NAMES


def schedule(**kw):
    return WeekendSchedule(day='2026-09-19', names=NAMES, grid={p: list(r) for p, r in GRID.items()}, **kw)


class WeekendViewToggleTests(unittest.TestCase):
    def test_buttons_only_when_view_given(self):
        from weekend_day_ui import sheet_html
        s = schedule()
        self.assertNotIn("data-view=", sheet_html(s))
        fm = sheet_html(s, view='FM')
        self.assertIn("class='vbtn on' data-view='FM'", fm)
        self.assertNotIn("class='flexg2", fm)
        compact = sheet_html(s, compact=True, view='FM')
        self.assertIn("data-view='유도리'", compact)

    def test_flexible_view_marks_g2_column(self):
        from weekend_day_ui import sheet_html
        html = sheet_html(schedule(), view='유도리')
        self.assertIn("class='vbtn on flex' data-view='유도리'", html)
        self.assertEqual(html.count("class='flexg2"), 10)                       # G2 칸 10시간
        self.assertIn("<th class=flexg2>G2</th>", html)                          # 머리글
        self.assertIn("flexg2 end", html)
        self.assertIn('유도리 보기', html)

    def test_notes_use_selected_view_numbers(self):
        from weekend_day_ui import weekend_notes
        s = schedule()
        a = {v: next(r for p, r in zip(s.grid, stats(s, v)) if p == 'A') for v in ('FM', '유도리')}
        self.assertNotEqual(a['FM']['실근무'], a['유도리']['실근무'])            # A가 G2를 서는 날
        line = lambda notes: next(n for n in notes if n.startswith('통제A:'))
        self.assertIn(f"실근무 {a['FM']['실근무']}시간", line(weekend_notes(s)))
        self.assertIn(f"실근무 {a['유도리']['실근무']}시간", line(weekend_notes(s, view='유도리')))


if __name__ == '__main__':
    unittest.main()
