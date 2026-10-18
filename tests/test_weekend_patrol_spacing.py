"""주말 주간 누구든 2연속 순찰 금지: 생성·독립 거부·LOCK 경계 확인."""
import unittest
from dataclasses import replace
from night_shift.weekend_day import generate, validate


class PatrolSpacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.names = {'A': '준호 대행', '1': '만년', '3': '제욱', '4': '광희', '5': '성호'}
        cls.schedule, cls.status = generate('2026-10-31', cls.names, 'FM', seconds=30)

    def test_two_patrols_remain_allowed_but_never_consecutive(self):
        s = self.schedule
        self.assertIsNotNone(s, self.status)
        self.assertEqual(validate(s), [])
        self.assertEqual(s.grid['A'].count('순찰'), 2)
        for row in s.grid.values():
            self.assertFalse(any(row[t:t+2] == ['순찰', '순찰'] for t in range(9)))

    def consecutive(self, pid):
        self.assertIsNotNone(self.schedule, self.status)
        grid = {p: list(row) for p, row in self.schedule.grid.items()}
        for t in (1, 2):
            holder = next(p for p, row in grid.items() if row[t] == '순찰')
            grid[pid][t], grid[holder][t] = grid[holder][t], grid[pid][t]
        return replace(self.schedule, grid=grid)

    def test_validator_rejects_proxy_and_general_consecutive_patrols(self):
        for pid, label in (('A', '1준호'), ('1', '2만년')):
            with self.subTest(pid=pid):
                errors = validate(self.consecutive(pid))
                self.assertIn(f'{label} 9·10시 연속 순찰 금지', errors)

    def test_locked_past_preserved_but_boundary_still_rejected(self):
        bad = self.consecutive('A')
        message = '1준호 9·10시 연속 순찰 금지'
        self.assertNotIn(message, validate(replace(bad, locked_through=2)))
        self.assertIn(message, validate(replace(bad, locked_through=1)))


if __name__ == '__main__':
    unittest.main()
