"""주말 주간 생성 화면 (2026-10-18 사용자 요청, 야간과 같게): 표 아래 저장·초기 생성표로·재생성,
재생성 후보 쌓기, 상태 표시, 직원 상세분석, 해 없음 원인 안내."""
import unittest

from night_shift.weekend_day import WeekendSchedule, stats
from tests.test_weekend_actual_edit import GRID, NAMES

APP = '''from datetime import date
import streamlit as st
from weekend_day_ui import render_weekend_day_page
render_weekend_day_page(date(2026,10,5), st.empty(), st.sidebar, {mobile})
'''


class WeekendCandidateTests(unittest.TestCase):
    def test_person_hours_match_stats(self):
        from weekend_day_ui import person_hours
        s = WeekendSchedule(day='2026-09-19', names=NAMES, grid={p: list(r) for p, r in GRID.items()},
                            annotations=[{'pid': '4', 't': 6, 'fatigue': 1, 'reason': '우천 순찰'}])
        for view in ('FM', '유도리'):
            for p, row in zip(s.grid, stats(s, view)):
                hours = person_hours(s, p, view)
                self.assertEqual(hours[-1]['누적 피로도'], row['피로도'], (view, p))
        self.assertEqual(person_hours(s, '4', 'FM')[6]['기록'], '우천 순찰')

    def test_delete_to_trash_and_restore(self):
        # 2026-10-18: 주말 저장본 삭제 = 휴지통 이동(야간과 같은 함수), 복구 가능, 재편성 백업 파일은 목록·비우기 대상 아님
        import json
        import tempfile
        from dataclasses import asdict
        from datetime import date
        from pathlib import Path
        from night_shift import history_store
        from night_shift.weekend_day import load
        s = WeekendSchedule(day='2026-09-19', names=NAMES, grid={p: list(r) for p, r in GRID.items()})
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, '2026-09-19.json').write_text(json.dumps(asdict(s), ensure_ascii=False), encoding='utf-8')
            (Path(tmp) / '.trash').mkdir()
            Path(tmp, '.trash', '2026-09-19_20261018_010101.json').write_text('{}', encoding='utf-8')  # 재편성 백업
            history_store.delete_to_trash(Path(tmp), date(2026, 9, 19))
            self.assertFalse(Path(tmp, '2026-09-19.json').exists())
            items = history_store.list_trash(Path(tmp))
            self.assertEqual([i['date'] for i in items], [date(2026, 9, 19)])
            history_store.restore_from_trash(Path(tmp), items[0]['name'])
            self.assertEqual(load(tmp, '2026-09-19').grid, s.grid)
            history_store.delete_to_trash(Path(tmp), date(2026, 9, 19))
            history_store.empty_trash(Path(tmp))
            self.assertTrue(Path(tmp, '.trash', '2026-09-19_20261018_010101.json').exists())

    def test_relaxed_generate_keeps_flag(self):
        # 10/18 수정: relaxed가 순서로 넘어가 rule_exempt_names 칸에 들어가면 검증이 TypeError로 멈췄음
        from night_shift.weekend_day import generate, validate
        names = {'A': '통제A', **{str(i): str(i) for i in range(1, 6)}}
        s, status = generate('2026-10-25', names, 'FM', seconds=10, relaxed=True)
        self.assertIsNotNone(s, status)
        self.assertTrue(s.relaxed)
        self.assertEqual(s.rule_exempt_names, ())
        self.assertEqual(validate(s), [])

    def test_regenerate_adds_candidates_pc_and_mobile(self):
        from streamlit.testing.v1 import AppTest
        for mobile in (False, True):
            with self.subTest(mobile=mobile):
                app = AppTest.from_string(APP.format(mobile=mobile), default_timeout=120).run()
                next(b for b in app.button if b.label == '공휴일 주간 근무표 생성').click().run()
                self.assertFalse(app.exception)
                labels = [b.label for b in app.button]
                for label in ('💾 저장', '↩ 초기 생성표로', '🔁 근무표 재생성'):
                    self.assertIn(label, labels)
                self.assertTrue(next(b for b in app.button if b.label == '↩ 초기 생성표로').disabled)  # 수정 전
                self.assertTrue(any('미저장' in m.value for m in app.markdown))                       # 상태 표시
                self.assertIn('직원 상세분석', [t.label for t in app.tabs])
                next(b for b in app.button if b.label == '🔁 근무표 재생성').click().run()
                self.assertFalse(app.exception)
                pick = next(r for r in app.radio if r.label == '표시할 근무표')
                self.assertEqual(len(pick.options), 2)
                self.assertEqual(pick.value, 1)                                # 새 후보가 선택됨
                self.assertIn('이전에 생성한 근무표', [m.value.strip('# ') for m in app.markdown])


if __name__ == '__main__':
    unittest.main()
