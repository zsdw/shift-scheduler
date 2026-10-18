import unittest
from copy import deepcopy
from tempfile import TemporaryDirectory
from night_shift.weekend_day import generate, validate, stats, save, load

class WeekendDayTests(unittest.TestCase):
    def test_all_vacancies_dual_and_negative(self):
        for vacancy in range(3):
            with self.subTest(vacancy=vacancy):
                names = {'A':'통제A', **{str(i):str(i) for i in range(1,7-vacancy)}}
                s,status = generate('2026-10-05', names, seconds=30)
                self.assertIsNotNone(s, status)
                self.assertEqual(validate(s), [])
                self.assertEqual(sum(v['실근무'] for v in stats(s,'FM')), 46 if vacancy < 2 else 36)
                self.assertEqual(sum(v['순찰 피로도'] for v in stats(s,'FM')), 10)
                if vacancy == 2: self.assertTrue(all('G2' not in r for r in s.grid.values()))
                bad = deepcopy(s)
                bad.grid['A'][0] = '순찰'
                self.assertTrue(validate(bad))
                with TemporaryDirectory() as store:
                    save(store,s)
                    self.assertEqual(load(store,s.day), s)
                    with self.assertRaises(FileExistsError): save(store,s)

    def test_confirmed_hard_rules_negative(self):
        # 2026-10-05 사용자 확정: G2 최대 2회·3연속 입식 금지·일반 실근무 1시간/피로도 1점 이내
        names = {'A':'통제A', **{str(i):str(i) for i in range(1,7)}}
        s,status = generate('2026-10-05', names, seconds=30)
        self.assertIsNotNone(s, status)
        cases = {'G2 횟수 초과': ['G2','휴게']*5,
                 '3연속 입식': ['G1','L1','G1']+['휴게']*7,
                 '실근무 격차 초과': ['휴게']*10,
                 'FM 1 3연속 휴게': ['휴게']*3+['I1']*7,
                 # 2026-10-18 사용자 확정: 유도리 G2 휴게성이 끼면 3연속 허용, 4연속 휴게는 금지
                 '유도리 1 4연속 휴게': ['휴게','G2','휴게','G2']+['I1']*6,
                 '1 포스트 미배정: L1': ['G1','I1','G2','I1','G1','I1','G2','I1','G1','I1']}
        bad = deepcopy(s)                 # G2가 낀 3연속 휴게는 이제 위반 아님 (10/18)
        bad.grid['1'] = ['G2', 'G2', '휴게'] + ['I1'] * 7
        self.assertFalse(any('3연속 휴게' in e for e in validate(bad)))
        for message, row in {'통제A 17시 휴게 아님': s.grid['A'][:9]+['G1'],
                             '통제A 실근무 우대 위반': ['I1']*9+['휴게']}.items():
            with self.subTest(message=message):
                bad = deepcopy(s)
                bad.grid['A'] = row
                self.assertTrue(any(message in e for e in validate(bad)), validate(bad))
        for vacancy in range(3):          # 생성표는 결원 0~2명 모두 통제A 규칙 만족
            names = {'A':'통제A', **{str(i):str(i) for i in range(1,7-vacancy)}}
            s2,_ = generate('2026-10-05', names, seconds=30)
            self.assertEqual(s2.grid['A'][9], '휴게')
            posts = ['G1','I1','L1'] + (['G2'] if vacancy < 2 else [])   # 일반근무자 운영 포스트 최소 1번
            for pid, row in s2.grid.items():
                if pid != 'A':
                    self.assertTrue(all(v in row for v in posts), (vacancy, pid, row))
            # 2026-10-18 사용자 확정: 휴게·대기만 3연속 없음, 유도리 G2 휴게성이 끼면 3연속 허용·4연속은 없음
            for mode in ('FM','유도리'):
                for row in s2.grid.values():
                    pure = ''.join('1' if v in ('휴게', '대기') else '0' for v in row)
                    rest = ''.join('1' if v in ('휴게', '대기') or (mode == '유도리' and v == 'G2') else '0' for v in row)
                    self.assertNotIn('111', pure)
                    self.assertNotIn('1111', rest)
            for mode in ('FM','유도리'):
                rows = stats(s2, mode)
                self.assertLessEqual(rows[0]['실근무'], min(r['실근무'] for r in rows[1:]))
        for message, row in cases.items():
            with self.subTest(message=message):
                bad = deepcopy(s)
                bad.grid['1'] = row
                self.assertTrue(any(message in e for e in validate(bad)), validate(bad))

    def test_perfect_nbbang_first(self):
        # 2026-10-05 사용자 확정: 완벽한 n빵 먼저, 안 되면 1 차이.
        # 2026-10-12: 통제A도 포스트마다 1번(사용자 확정) → 결원 1명 FM 완벽 n빵 불가능 확인(180초). 찾으면 차이 0, 아니면 1
        from weekend_day_ui import nbbang_text, views_of
        names = {'A':'통제A', **{str(i):str(i) for i in range(1,6)}}
        for mode in ('FM','유도리'):
            s,status = generate('2026-10-05', names, mode, seconds=30)
            self.assertIn(status, ('OPTIMAL', 'NO_PERFECT', 'FEASIBLE'))
            for view in (('FM','유도리') if mode == 'FM' else ('유도리',)):
                rows = stats(s, view)[1:]
                for key in ('실근무','피로도'):
                    values = {r[key] for r in rows}
                    self.assertLessEqual(max(values) - min(values), 1, (mode, view, key))
            self.assertIn('완벽한 n빵' if all(len({r[k] for r in stats(s, v)[1:]}) == 1 for k in ('실근무', '피로도')
                                             for v in views_of(s)) else '1 차이 표', nbbang_text(s, status))
        s,status = generate('2026-10-05', {'A':'통제A', **{str(i):str(i) for i in range(1,5)}}, '유도리', seconds=30)
        self.assertEqual(status, 'OPTIMAL')          # 결원 2명: 차이 0 불가능 확인 → 1 차이 표
        self.assertIn('불가능함을 계산으로 확인', nbbang_text(s, status))
        from weekend_day_ui import views_of, sheet_html     # 결원 2명: G2 미운영 → 비교표 하나
        self.assertEqual(views_of(s), ('FM',))
        self.assertIn('G2 미운영', sheet_html(s))
        s,status = generate('2026-10-05', {'A':'통제A', **{str(i):str(i) for i in range(1,7)}}, 'FM', seconds=20)
        self.assertIn(status, ('OPTIMAL','NO_PERFECT'))  # 결원 0명 FM: 차이 0 불가능은 빠르게 확인
        self.assertIn('불가능함을 계산으로 확인', nbbang_text(s, status))

    def test_emergency_half_and_leave(self):
        # 2026-10-05 사용자 확정: 긴급 오후반차(13시)·이탈, LOCK 보존, 4명 남으면 결원 2명 규칙(G2 미운영)
        from night_shift.weekend_day import reoptimize, advisories, OFF
        names = {'A':'통제A', **{str(i):str(i) for i in range(1,6)}}      # 결원 1명
        base,_ = generate('2026-10-05', names, '유도리', seconds=20)
        for lock, kind in ((2,'half'), (4,'leave')):
            with self.subTest(lock=lock, kind=kind):
                s,status = reoptimize(base, lock, '1', kind, seconds=20)
                self.assertIsNotNone(s, status)
                self.assertEqual(validate(s, base), [])
                for pid in s.grid:
                    self.assertEqual(s.grid[pid][:lock+1], base.grid[pid][:lock+1])      # LOCK 그대로
                cut = 5 if kind == 'half' else lock+1
                self.assertEqual(s.grid['1'][cut:], [OFF]*(10-cut))
                self.assertNotIn(OFF, s.grid['1'][:cut])
                for t in range(cut, 10):                                           # 4명 남은 시간 G2 미운영
                    self.assertNotIn('G2', [row[t] for row in s.grid.values()])
                self.assertIsInstance(advisories(s), list)
                bad = deepcopy(s)                                                  # 위반표: LOCK 칸 변경
                t0 = 0
                a, b = [p for p in bad.grid if bad.grid[p][t0] != bad.grid['A'][t0]][:1] + ['A']
                bad.grid[a][t0], bad.grid[b][t0] = bad.grid[b][t0], bad.grid[a][t0]
                self.assertTrue(any('LOCK 칸 변경' in e for e in validate(bad, base)))
                bad = deepcopy(s)                                                  # 위반표: 빠진 뒤 근무
                bad.grid['1'][9] = '휴게'
                self.assertTrue(any('근무불가 칸 오류' in e for e in validate(bad)))
        from night_shift.weekend_day import half_rest_hours                        # 오후반차자 휴게 1시간 목표
        full_names = {'A':'통제A', **{str(i):str(i) for i in range(1,7)}}
        fm,_ = generate('2026-10-05', full_names, 'FM', seconds=15)
        s,_ = reoptimize(fm, 2, '1', 'half', seconds=20)
        self.assertLessEqual(half_rest_hours(s, '1', 'FM'), 2)   # 목표 1시간(밸런스 다음 순위·시간 제한 해)
        with self.assertRaises(ValueError):                                        # 13시 이후 오후반차 불가
            reoptimize(base, 6, '1', 'half')
        two = {'A':'통제A', **{str(i):str(i) for i in range(1,5)}}                # 결원 2명 + 1명 → 3명: 지원 밖
        base2,_ = generate('2026-10-05', two, 'FM', seconds=20)
        s,status = reoptimize(base2, 2, '1', 'leave', seconds=10)
        self.assertIsNone(s); self.assertEqual(status, 'UNSUPPORTED')

    def test_planned_half_days(self):
        # 2026-10-05 사용자 확정: 오후반차 08~12시 근무, 오전반차 13~17시 근무(평일과 같음). 4명인 시간만 G2 미운영
        from night_shift.weekend_day import OFF, half_rest_hours, partial_people
        names = {'A':'통제A', **{str(i):str(i) for i in range(1,6)}}      # 결원 1명 + 반차 1명
        for kind, off in (('오후반차', range(5,10)), ('오전반차', range(0,5))):
            with self.subTest(kind=kind):
                s,status = generate('2026-10-05', names, '유도리', seconds=20, half_days={'1': kind})
                self.assertIsNotNone(s, status)
                self.assertEqual(validate(s), [])
                self.assertEqual([t for t,v in enumerate(s.grid['1']) if v == OFF], list(off))
                for t in off:                                                   # 반차 시간엔 일반 4명 → G2 미운영
                    self.assertNotIn('G2', [row[t] for row in s.grid.values()])
                self.assertEqual(partial_people(s), {'1'})
                self.assertLessEqual(half_rest_hours(s, '1', '유도리'), 2)
                bad = deepcopy(s); bad.grid['1'][list(off)[0]] = '휴게'           # 위반표: 반차 시간 근무
                self.assertTrue(any('근무불가 칸 오류' in e for e in validate(bad)))
        two = {'A':'통제A', **{str(i):str(i) for i in range(1,5)}}                # 결원 2명 + 반차 → 3명: 지원 밖
        s,status = generate('2026-10-05', two, 'FM', seconds=10, half_days={'1':'오후반차'})
        self.assertIsNone(s); self.assertEqual(status, 'UNSUPPORTED')

    def test_emergency_mobile_form(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string('''from datetime import date
import streamlit as st
from weekend_day_ui import render_weekend_day_page
render_weekend_day_page(date(2026,10,5), st.empty(), st.sidebar, True)
''').run()
        next(b for b in app.button if b.label == '공휴일 주간 근무표 생성').click().run(timeout=60)
        self.assertFalse(app.exception)
        next(b for b in app.button if b.label == '재편성').click().run(timeout=60)
        self.assertFalse(app.exception)
        self.assertTrue(any('긴급 재편성표' in i.value for i in app.info))

    def test_ui_pc_mobile(self):
        from streamlit.testing.v1 import AppTest
        for mobile in (False,True):
            app = AppTest.from_string(f'''from datetime import date
import streamlit as st
from weekend_day_ui import render_weekend_day_page
render_weekend_day_page(date(2026,10,5), st.empty(), st.sidebar, {mobile})
''').run()
            self.assertFalse(app.exception)
            self.assertIn('주간 근무자', [h.value for h in app.subheader])
            # 표 순서가 아니라 열 이름으로 찾는다 (2026-10-13 '📊 주말 주간 기록' 표 추가)
            columns = lambda: [list(d.value.columns) for d in app.dataframe]
            if not mobile:                  # PC: 야간과 같은 이름·상태·역할 표
                self.assertIn(['이름','상태','역할'], columns())
            self.assertIn('공휴일 주간 근무표 생성', [b.label for b in app.button])
            next(b for b in app.button if b.label == '공휴일 주간 근무표 생성').click().run(timeout=60)
            self.assertFalse(app.exception)
            # 2026-10-16: 표 제목 줄 FM·유도리 보기 버튼 → 고른 기준(처음 FM) 비교표 한 장
            self.assertEqual(sum('실근무' in c for c in columns()), 1)
            self.assertTrue(any('검증 통과' in e.value for e in app.success))

if __name__ == '__main__': unittest.main()
