"""주말 주간 (2026-10-12 사용자 확정): 통제A 16시 G1 금지(하드), 완벽 n빵이 안 될 때 최근 주말 주간
4회 이력에서 피로도 손해 본 사람에게 남는 차이를 유리하게 (n빵·2연속 다음 순위)."""
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from night_shift.weekend_day import generate, history_debt, stats, validate

NAMES = {'A': '통제A', '1': '만년', '2': '원종', '3': '제욱', '4': '광희', '5': '성호', '6': '준호'}


def fatigue(s):
    return {r['직원'].split(' · ')[1]: r['피로도'] for r in stats(s, 'FM')}


class WeekendHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base, cls.status = generate('2026-10-25', NAMES, 'FM', seconds=30)

    def test_control_a_16_rest_preferred(self):
        # 2026-10-16 사용자 확정: 통제A 16시 휴게 강한 권장(안 되면 G2), 종전 'G2만' 하드 폐지, 17시 휴게 하드 유지
        self.assertEqual(self.base.grid['A'][8:], ['휴게', '휴게'])
        f = fatigue(self.base)                       # 10/16 강한 권장: 통제A는 일반근무자보다 피로도 덜(1~2점 목표)
        self.assertLessEqual(f['통제A'], min(v for k, v in f.items() if k != '통제A'))
        grid = {p: list(r) for p, r in self.base.grid.items()}
        holder = next(p for p, r in grid.items() if r[8] == 'G2')
        grid['A'][8], grid[holder][8] = 'G2', grid['A'][8]
        self.assertNotIn('통제A 16시 G2 아님', validate(replace(self.base, grid=grid)))   # 권장이라 검증 오류 아님
        grid = {p: list(r) for p, r in self.base.grid.items()}
        holder = next(p for p, r in grid.items() if r[9] != '휴게' and p != 'A')
        grid['A'][9], grid[holder][9] = grid[holder][9], '휴게'
        self.assertIn('통제A 17시 휴게 아님', validate(replace(self.base, grid=grid)))

    def test_control_a_08_rest_or_g2(self):
        # 2026-10-16 사용자 확정(하드): 통제A 08시(첫 시간)는 휴게·G2만, LOCK된 칸은 보존
        self.assertIn(self.base.grid['A'][0], ('휴게', 'G2'))
        grid = {p: list(r) for p, r in self.base.grid.items()}
        holder = next(p for p, r in grid.items() if r[0] == 'I1')
        grid['A'][0], grid[holder][0] = 'I1', grid['A'][0]
        self.assertIn('통제A 08시 휴게·G2 아님', validate(replace(self.base, grid=grid)))
        self.assertNotIn('통제A 08시 휴게·G2 아님', validate(replace(self.base, grid=grid, locked_through=0)))

    def test_two_absent_16_any_but_g1_and_notes(self):
        from weekend_day_ui import weekend_notes
        s, status = generate('2026-10-25', {k: v for k, v in NAMES.items() if k in 'A1234'}, 'FM', seconds=20)
        self.assertIsNotNone(s, status)
        # 결원 2명: 16시 휴게는 다른 하드룰로 불가능(INFEASIBLE 확인, 10/16) → G1만 빼고 다른 업무
        self.assertIn(s.grid['A'][8], ('휴게', 'I1', 'L1', '순찰'))
        self.assertEqual(validate(s), [])
        grid = {p: list(r) for p, r in s.grid.items()}
        holder = next(p for p, r in grid.items() if r[8] == 'G1')
        grid['A'][8], grid[holder][8] = 'G1', grid['A'][8]
        self.assertIn('통제A 16시 G1', validate(replace(s, grid=grid)))
        notes = weekend_notes(s)
        self.assertTrue(any(n.startswith('통제A: 09시 순찰') for n in notes))
        self.assertTrue(any(n.startswith('순찰: 9시 상층 통제A') for n in notes))
        self.assertIn('결원 2명: G2 미운영 (FM·유도리 같음)', notes)

    def test_control_a_first_patrol_and_every_post(self):
        a = self.base.grid['A']
        self.assertEqual(a[1], '순찰')                                    # 09시 첫 순찰 = 통제A
        for post in ('G1', 'G2', 'I1', 'L1'):
            self.assertIn(post, a)
        grid = {p: list(r) for p, r in self.base.grid.items()}
        swap = next(p for p, r in grid.items() if p != 'A' and r[1] != '순찰')
        grid['A'][1], grid[swap][1] = grid[swap][1], '순찰'
        self.assertIn('통제A 9시 첫 순찰 아님', validate(replace(self.base, grid=grid)))
        no_i1 = {p: list(r) for p, r in self.base.grid.items()}
        t = no_i1['A'].index('I1')
        holder = next(p for p, r in no_i1.items() if p != 'A' and r[t] == '휴게')
        no_i1['A'][t], no_i1[holder][t] = '휴게', 'I1'
        self.assertTrue(any('통제A 포스트 미배정: I1' in e for e in validate(replace(self.base, grid=no_i1))))

    def test_no_four_run_when_not_needed_and_text(self):
        from weekend_day_ui import long_run_text
        self.assertEqual(long_run_text(self.base), '')                   # 결원 0명: 4연속 없음
        grid = {p: list(r) for p, r in self.base.grid.items()}
        grid['1'][:4] = ['G1', 'I1', 'L1', 'I1']
        text = long_run_text(replace(self.base, grid=grid))
        self.assertIn('FM 1만년 8~12시', text)
        self.assertIn('유도리 1만년 8~12시', text)                       # FM·유도리 기준 각각

    def test_emergency_gap_by_lock_time(self):
        from night_shift.weekend_day import emergency_gap
        self.assertEqual([emergency_gap(t) for t in (None, 0, 1, 2, 3, 8)], [1, 1, 1, 1, 2, 2])

    def test_history_debt_from_recent_four_weekend_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i, day in enumerate(('2026-10-03', '2026-10-04', '2026-10-10', '2026-10-11', '2026-10-17')):
                Path(tmp, f'{day}.json').write_text(json.dumps(asdict(replace(self.base, day=day))), encoding='utf-8')
            debt, days = history_debt(tmp, '2026-10-18')
            self.assertEqual(days, ['2026-10-17', '2026-10-11', '2026-10-10', '2026-10-04'])
            f = fatigue(self.base)
            avg = sum(v for k, v in f.items() if k != '통제A') / 6
            self.assertAlmostEqual(debt['만년'], 4 * (f['만년'] - avg))
            self.assertNotIn('통제A', debt)

    def test_loser_gets_less_fatigue_when_no_perfect_split(self):
        self.assertEqual(self.status, 'NO_PERFECT')         # 6명 결원 0: 완벽 n빵 불가능
        lost, _ = generate('2026-10-25', NAMES, 'FM', seconds=30, history={'만년': 5.0})
        won, _ = generate('2026-10-25', NAMES, 'FM', seconds=30, history={'만년': -5.0})
        for s in (lost, won):
            self.assertEqual(validate(s), [])
        a, b = fatigue(lost), fatigue(won)
        others = [k for k in a if k not in ('통제A', '만년')]
        self.assertLessEqual(a['만년'], min(a[k] for k in others))
        self.assertGreaterEqual(b['만년'], max(b[k] for k in others))


if __name__ == '__main__':
    unittest.main()
