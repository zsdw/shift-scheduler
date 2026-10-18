"""주말 주간 (2026-10-18 사용자 확정): 보안실 대기 매시간 정확히 1명·순찰 직후 1시간 휴게 표기·일반근무자 대기
차이 ≤1·통제A 대기 비권장, 휴게·대기만 3연속 금지(유도리 G2 끼면 허용)·4연속 휴게 금지, 4연속 실근무엔 G2·I1,
통제A G1 11~15시 최소 1번, 통제A 피로도(결원 1·2명 1점 이상 적게, 결원 0명 최저 이하)."""
import unittest
from dataclasses import replace

from night_shift.weekend_day import STANDBY, PATROL, WeekendSchedule, generate, stats, validate
from tests.test_weekend_actual_edit import GRID, NAMES as SIX


def team(vacancy):
    return {'A': '통제A', **{str(i): str(i) for i in range(1, 7 - vacancy)}}


class WeekendStandbyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zero, _ = generate('2026-10-25', team(0), 'FM', seconds=30)
        cls.one, _ = generate('2026-10-25', team(1), 'FM', seconds=30)

    def test_generated_tables_follow_rules(self):
        for s, need in ((self.zero, 0), (self.one, 1)):
            self.assertTrue(s.standby)
            self.assertEqual(validate(s), [])
            for t in range(10):
                self.assertEqual([r[t] for r in s.grid.values()].count(STANDBY), 1)
            counts = [r.count(STANDBY) for p, r in s.grid.items() if p != 'A']
            self.assertLessEqual(max(counts) - min(counts), 1)
            self.assertEqual(s.grid['A'].count(STANDBY), 0)                    # 비권장: 필요 없으면 0
            self.assertIn('G1', [s.grid['A'][t] for t in range(3, 8)])
            f = {p: r['피로도'] for p, r in zip(s.grid, stats(s, 'FM'))}
            self.assertLessEqual(f['A'], min(v for p, v in f.items() if p != 'A') - need)

    def test_standby_violations_rejected(self):
        s = self.zero
        grid = {p: list(r) for p, r in s.grid.items()}
        holder = next(p for p, r in grid.items() if r[4] == STANDBY)
        grid[holder][4] = '휴게'                                              # 12시 대기 0명
        self.assertIn('12시 대기 인원 오류', validate(replace(s, grid=grid)))
        grid = {p: list(r) for p, r in s.grid.items()}
        t = 1                                                                  # 09시 순찰(통제A) 직후 10시
        a10, holder = grid['A'][2], next(p for p, r in grid.items() if r[2] == STANDBY)
        grid['A'][2], grid[holder][2] = STANDBY, a10
        self.assertIn('A 순찰 직후 대기', validate(replace(s, grid=grid)))
        self.assertNotIn('대기 인원 오류', ' '.join(validate(replace(s, grid={p: [('휴게' if v == STANDBY else v)
                                                                        for v in r] for p, r in s.grid.items()},
                                                                standby=False))))   # 대기 전 저장본은 대상 아님

    def test_rest_and_run_rules(self):
        base = WeekendSchedule(day='2026-09-19', names=SIX, grid={p: list(r) for p, r in GRID.items()})
        grid = {p: list(r) for p, r in GRID.items()}
        grid['2'] = ['휴게', STANDBY, '휴게'] + grid['2'][3:]                  # 휴게·대기만 3연속
        self.assertTrue(any('3연속 휴게' in e for e in validate(replace(base, grid=grid))))
        grid = {p: list(r) for p, r in GRID.items()}
        grid['1'] = ['G1', 'I1', 'L1', '순찰'] + grid['1'][4:]                  # 4연속에 G2 없음
        self.assertTrue(any('4연속 실근무에 G2·I1 없음' in e for e in validate(replace(base, grid=grid))))

    def test_control_a_rules_rejected(self):
        s = self.one
        grid = {p: list(r) for p, r in s.grid.items()}                     # 통제A 11~15시에 G1 없음
        self.assertIn('통제A 11~15시 G1 없음',
                      validate(replace(s, grid={**grid, 'A': ['휴게'] * 3 + ['L1'] * 5 + ['휴게'] * 2})))
        grid = {p: list(r) for p, r in s.grid.items()}
        t = next(t for t in range(10) if grid['A'][t] == '휴게' and t not in (0, 9))
        holder = next(p for p, r in grid.items() if r[t] in ('L1', 'G1') and p != 'A')
        grid['A'][t], grid[holder][t] = grid[holder][t], '휴게'               # 통제A +2점
        self.assertTrue(any('통제A 피로도' in e for e in validate(replace(s, grid=grid))))


class WeekendLastRestTests(unittest.TestCase):
    def test_previous_receiver_excluded_and_oldest_first(self):
        # 2026-10-18 사용자 확정: 야간 07시·빨간날 주간 17시 이어서 — 직전 출근 수혜자 17시 휴게 금지, 오래된 사람부터
        names = team(0)
        last = {'1': {'prev': True, 'last': 100}, '2': {'prev': False, 'last': -1}, '3': {'prev': False, 'last': -1},
                '4': {'prev': False, 'last': 90}, '5': {'prev': False, 'last': 95}, '6': {'prev': False, 'last': 99}}
        s, status = generate('2026-10-25', names, 'FM', seconds=30, last_rest=last)
        self.assertIsNotNone(s, status)
        rest = {p for p, r in s.grid.items() if p != 'A' and r[9] in ('휴게', STANDBY)}
        self.assertNotIn('1', rest)
        self.assertEqual(rest, {'2', '3'})                                  # 한 번도 안 받은 사람 먼저
        self.assertEqual(validate(s), [])
        bad = {p: list(r) for p, r in s.grid.items()}
        other = next(iter(rest))
        bad['1'][9], bad[other][9] = bad[other][9], bad['1'][9]
        self.assertIn('1 직전 출근에 이어 막타임 휴게', validate(replace(s, grid=bad)))


class WeekendFlexLastRestTests(unittest.TestCase):
    def test_previous_receiver_kept_off_17_g2_and_flex_counts(self):
        # 2026-10-18: 직전 수혜자 17시 G2도 피함(아주 강한 권장), 지난 FM 표 17시 G2는 실제 유도리(기본값)면 수혜로 셈
        import weekend_day_ui as ui
        names = team(0)
        last = {'1': {'prev': True, 'last': 100}, '2': {'prev': True, 'last': 100}, '3': {'prev': False, 'last': -1},
                '4': {'prev': False, 'last': 90}, '5': {'prev': False, 'last': 95}, '6': {'prev': False, 'last': 99}}
        s, status = generate('2026-10-25', names, 'FM', seconds=30, last_rest=last)
        self.assertIsNotNone(s, status)
        self.assertNotIn(s.grid['1'][9], ('G2', '휴게', STANDBY))
        self.assertNotIn(s.grid['2'][9], ('G2', '휴게', STANDBY))
        g2 = next(p for p, r in s.grid.items() if r[9] == 'G2')
        self.assertEqual(g2, '5')                  # 실제 휴게(3·4번) 다음으로 오래 기다린 사람 (④ 17시 G2 순번)
        flexed =ui._weekend_duty(s, 'x', actual_flex=True)
        plain = ui._weekend_duty(s, 'x', actual_flex=False)
        who = ui._who(names[g2])
        self.assertIn(who, flexed['rest'])                                     # 유도리 운영(기본): 수혜
        self.assertNotIn(who, plain['rest'])                                   # FM으로 함: 수혜 아님
        self.assertIn(who, ui._weekend_duty(s, '이번', now=True)['flex_rest'])  # 이번 표는 🛌(유도리) 표시만


if __name__ == '__main__':
    unittest.main()
