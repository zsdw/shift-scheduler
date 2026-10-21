import unittest
from dataclasses import replace
from datetime import date

from night_shift.day_shift import (DayPerson,DEFAULT_ROSTER,REST,STANDBY,PATROL,POSTS,
    early_worker_name,solve_day,validate_day,number_people,day_findings)


class EarlyRotationTests(unittest.TestCase):
    def test_week_boundaries_month_and_year_do_not_reset(self):
        for text,name in [('2026-09-28','성욱'),('2026-10-04','성욱'),('2026-10-05','용주'),
                ('2026-10-11','용주'),('2026-10-12','성욱'),('2026-10-19','용주'),
                ('2026-10-26','성욱'),('2026-11-02','용주'),('2027-01-04','성욱')]:
            self.assertEqual(early_worker_name(date.fromisoformat(text)),name)

    def staff(self,size=10,statuses=None):
        names=['준호','성욱','용주']+[n for n in DEFAULT_ROSTER if n not in ('준호','성욱','용주')]
        names+=(['추가직원'] if size==11 else [])
        return number_people([DayPerson(n,n,(statuses or {}).get(n,'출근')) for n in names[:size]])

    def test_all_fixed_templates_and_seeds_keep_both_senior_and_early_off_posts(self):
        for size in (8,9,10,11):
            for day,who in [(date(2026,10,22),'용주'),(date(2026,10,26),'성욱')]:
                for seed in range(4):
                    with self.subTest(size=size,day=day,seed=seed):
                        s,status=solve_day(day,self.staff(size),seconds=5,seed=seed)
                        self.assertIsNotNone(s,status)
                        self.assertIn(s.grid[who][0],(REST,STANDBY,PATROL))
                        self.assertIn(s.grid['준호'][0],(REST,STANDBY,PATROL))
                        self.assertEqual(validate_day(s),[])

    def test_non_template_solver_also_enforces_early_worker(self):
        day=date(2026,10,22)
        s,status=solve_day(day,self.staff(statuses={'원종':'오후반차'}),seconds=15)
        self.assertIsNotNone(s,status)
        self.assertIsNone(s.fixed_template)
        self.assertIn(s.grid['용주'][0],(REST,STANDBY,PATROL))
        self.assertEqual(validate_day(s),[])

    def test_independent_validator_rejects_early_post_assignment(self):
        s,status=solve_day(date(2026,10,22),self.staff(),seconds=5)
        grid={p:list(row) for p,row in s.grid.items()}; grid['용주'][0]='G1'
        errors=validate_day(replace(s,grid=grid))
        self.assertTrue(any(e['rule']=='주간-29' for e in errors),errors)
        # 이미 진행된 08시는 긴급 재편성에서 수정하거나 새 규칙으로 거부하지 않는다.
        errors=validate_day(replace(s,grid=grid,emergency={'start':1},locked_through=0))
        self.assertFalse(any(e['rule']=='주간-29' for e in errors),errors)

    def test_absence_does_not_change_weekly_person(self):
        day=date(2026,10,22)
        s,status=solve_day(day,self.staff(statuses={'용주':'연차'}),seconds=5)
        self.assertIsNotNone(s,status)
        self.assertEqual(s.grid['용주'],[None]*10)
        self.assertEqual(validate_day(s),[])
        self.assertTrue(any('용주' in note and '다른 사람으로 대체하지 않음' in note for note in day_findings(s)))
