"""2026-10-20 사용자 확정: 하층 순번(14-7)·하층 3회 연속 금지(14-9)·상중층 횟수(14-8)는
야간 + 공휴일 주간 순찰을 같은 그룹으로 센다. 야간·주말 엔진 모두."""
import unittest
from datetime import date

from tests.test_manager_late_half import NAMES, staff
from night_shift import history_import as imp
from night_shift.models import AssignmentKind, HistoryInput, Mode
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, mixed_zone_rates, run_schedule
from night_shift.validator import validate_first_trial
from night_shift.weekend_day import LOWER_PATROL, generate, validate

DAY = date(2026, 10, 27)
OPTIONS = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)


def event(day, name, *zones, shift=1):
    return {"date": day, "shift": shift, "name": name, "excluded": False, "patrol": bool(zones), "zones": tuple(zones)}


def lower_people(record):
    return {r.employee_id for r in record.assignments
            if r.actual_post_or_work_type.kind == AssignmentKind.PATROL and r.actual_post_or_work_type.label == "lower"}


class MixedZoneRateTests(unittest.TestCase):
    def test_rates_use_last_six_shifts_of_night_and_holiday_day(self):
        events = [event(f"2026-10-0{i}", "만년", "upper", shift=i % 2) for i in range(1, 8)]
        events += [event("2026-10-07", "광희", "middle")]
        rates = mixed_zone_rates({}, events, {"1": "만년", "4": "광희"}, ("1", "4"))
        self.assertEqual(rates["upper"]["1"], 100)
        self.assertEqual(rates["middle"]["4"], 100)
        self.assertEqual(mixed_zone_rates({"x": 1}, [{"date": "d", "shift": 1, "name": "만년"}], {}, ()), {"x": 1})


class NightMixedLowerStreakTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = run_schedule(ShiftRequest(DAY, imp.night_type_for(DAY), Mode.FM, staff()), HistorySelection(), OPTIONS)

    def test_weekend_lower_counts_toward_night_three_in_a_row(self):
        self.assertTrue(self.base.valid, self.base.validation_errors)
        pid = sorted(lower_people(self.base.record))[0]
        name = NAMES[pid]
        events = [event("2026-10-24", name, "lower", shift=0), event("2026-10-25", name, "lower", shift=0)]
        errors = validate_first_trial(self.base.record, HistoryInput((), ()), rules_v220=True, patrol_events=events)
        self.assertIn("14-9", {e["rule"] for e in errors})
        out = run_schedule(ShiftRequest(DAY, imp.night_type_for(DAY), Mode.FM, staff()),
                           HistorySelection(patrol_events=tuple(events)), OPTIONS)
        self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
        self.assertNotIn(pid, lower_people(out.record))


class WeekendMixedPatrolTests(unittest.TestCase):
    names = {'A': '통제', '1': '만년', '2': '원종', '3': '제욱', '4': '광희', '5': '성호', '6': '준호'}

    @classmethod
    def setUpClass(cls):
        cls.plain, cls.plain_status = generate('2026-10-31', cls.names, 'FM', seconds=30)

    def lower_holders(self, schedule):
        return {p for p, row in schedule.grid.items() if p != 'A' and any(row[t] == '순찰' for t in LOWER_PATROL)}

    def test_night_lower_streak_blocks_weekend_lower(self):
        self.assertIsNotNone(self.plain, self.plain_status)
        pid = sorted(self.lower_holders(self.plain))[0]
        name = self.names[pid]
        events = (event("2026-10-27", name, "lower"), event("2026-10-28", name, "lower"))
        self.plain.patrol_events = events
        self.assertTrue(any('하층 순찰 3회 연속 금지' in e for e in validate(self.plain)))
        self.plain.patrol_events = ()
        out, status = generate('2026-10-31', self.names, 'FM', seconds=30, patrol_events=events)
        self.assertIsNotNone(out, status)
        self.assertNotIn(pid, self.lower_holders(out))
        self.assertEqual(validate(out), [])

    def test_lower_turn_candidate_gets_lower(self):
        target = '광희'
        events = []
        for i, day in enumerate(("2026-10-20", "2026-10-21", "2026-10-24", "2026-10-27")):
            for n in self.names.values():
                if n == '통제':
                    continue
                if n == target:
                    events.append(event(day, n, "upper" if i % 2 else "middle", shift=0 if i == 2 else 1))
                else:
                    events.append(event(day, n, "lower" if i == 3 else "upper", shift=0 if i == 2 else 1))
        out, status = generate('2026-10-31', self.names, 'FM', seconds=30, patrol_events=tuple(events))
        self.assertIsNotNone(out, status)
        pid = next(p for p, n in self.names.items() if n == target)
        self.assertIn(pid, self.lower_holders(out))


if __name__ == "__main__":
    unittest.main()
