"""주말 주간 통제A 미리 정한 반차 (2026-10-18 사용자 확정): 준호가 통제A 역할 계승.
오전반차: 08~12시 준호가 통제A 패턴(08시 휴게·G2, 09시 G1 제외), 13시부터 통제A 본인 규칙.
오후반차: 통제A 08~12시 본인 규칙, 준호가 마지막 2시간 규칙(16시 휴게 권장·17시 휴게 하드) 계승.
통제A가 빠진 시간은 결원 1명 더로 센다(G2 미운영·4연속 허용 등 평소 결원 규칙)."""
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from night_shift.weekend_day import OFF, generate, load, validate

NAMES = {'A': '통제A', '1': '만년', '2': '원종', '3': '제욱', '4': '광희', '5': '성호', '6': '준호'}


class ControlHalfDayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.am, cls.am_status = generate('2026-10-25', NAMES, 'FM', seconds=30, a_half='오전반차', proxy='6')
        cls.pm, cls.pm_status = generate('2026-10-25', NAMES, 'FM', seconds=30, a_half='오후반차', proxy='6')

    def test_morning_half_proxy_follows_control_pattern(self):
        s = self.am
        self.assertIsNotNone(s, self.am_status)
        self.assertEqual(s.grid['A'][:5], [OFF] * 5)
        self.assertIn(s.grid['6'][0], ('휴게', 'G2'))                 # 08시 휴게·G2
        self.assertNotEqual(s.grid['6'][1], 'G1')                     # 09시 G1 제외
        self.assertEqual(s.grid['A'][9], '휴게')                      # 13시부터 통제A 본인 규칙
        self.assertEqual(validate(s), [])
        bad = {p: list(r) for p, r in s.grid.items()}
        holder = next(p for p, r in bad.items() if r[1] == 'G1')
        bad['6'][1], bad[holder][1] = 'G1', bad['6'][1]
        self.assertIn('대행 6 9시 G1', validate(replace(s, grid=bad)))

    def test_afternoon_half_proxy_inherits_last_two_hours(self):
        s = self.pm
        self.assertIsNotNone(s, self.pm_status)
        self.assertEqual(s.grid['A'][5:], [OFF] * 5)
        self.assertEqual(s.grid['6'][9], '휴게')                      # 17시 휴게 계승(하드)
        self.assertEqual(validate(s), [])
        bad = {p: list(r) for p, r in s.grid.items()}
        holder = next(p for p, r in bad.items() if r[9] in ('I1', 'L1', 'G1') and p != '6')
        bad['6'][9], bad[holder][9] = bad[holder][9], '휴게'
        self.assertIn('대행 6 17시 휴게 아님', validate(replace(s, grid=bad)))

    def test_saved_and_loaded_keeps_half_and_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, '2026-10-25.json').write_text(json.dumps(asdict(self.pm), ensure_ascii=False), encoding='utf-8')
            again = load(tmp, '2026-10-25')
        self.assertEqual((again.a_half, again.proxy), ('오후반차', '6'))
        self.assertEqual(validate(again), [])

    def test_proxy_must_work_full_day(self):
        s, status = generate('2026-10-25', NAMES, 'FM', seconds=5, a_half='오전반차', proxy='6',
                             half_days={'6': '오후반차'})
        self.assertIsNone(s)
        self.assertEqual(status, 'UNSUPPORTED')


if __name__ == '__main__':
    unittest.main()
