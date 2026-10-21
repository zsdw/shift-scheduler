"""H-21 [하드, 2026-10-22 사용자 확정]: 누구든(통제A·준호 포함) 연속 4시간 안에 같은 포스트(표시 기준) 최대 2번.
FM·유도리·결원 무관, 유도리 휴게성 I1도 I1, 순찰·대기·휴게는 포스트 아님, LOCK 칸만으로 이미 3번인 구간은 보존."""
import unittest
from dataclasses import replace

from night_shift.models import AssignmentKind as K, HistoryInput, Mode, NightType
from night_shift.profiles import make_record
from night_shift.service import HistorySelection, ShiftRequest, run_schedule
from night_shift.validator import validate_first_trial
from tests.test_proxy_lowest import DAY, OPTIONS, staff


def violations(record):
    family = {(r.employee_id, r.slot.index): r.displayed_assignment.label.partition("(")[0]
              for r in record.assignments if r.displayed_assignment.kind == K.POST
              and not (r.slot.index == 0 and r.employee_id == "A")}
    out = []
    for p in {key[0] for key in family}:
        for start in range(11):
            labels = [family.get((p, t)) for t in range(start, start + 4)]
            out += [(p, start, post) for post in set(labels) - {None} if labels.count(post) >= 3]
    return out


class SamePostWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fm = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, staff()), HistorySelection(), OPTIONS)
        cls.flex = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FLEXIBLE, staff(a_present=False)),
                                HistorySelection(), OPTIONS)

    def test_generated_tables_have_no_same_post_three_in_four_hours(self):
        for result in (self.fm, self.flex):
            self.assertTrue(result.valid, result.validation_errors)
            self.assertEqual(violations(result.record), [])

    def bad(self):
        rec = self.fm.record
        rows = list(rec.assignments)
        cells = {3: "휴게", 4: "휴게", 5: "휴게", 6: "L3", 7: "L3", 8: "휴게", 9: "L3", 10: "휴게", 11: "휴게", 12: "휴게"}
        for i, r in enumerate(rows):            # 앞뒤는 휴게로 고정해 6·7·9시 L3 세 칸만 겹치게
            if r.employee_id == "1" and r.slot.index in cells:
                rows[i] = make_record(rec.context, "1", r.slot.index, cells[r.slot.index])
        return replace(rec, assignments=tuple(rows))

    def test_validator_rejects_three_in_four_hours(self):
        errors = validate_first_trial(self.bad(), HistoryInput((), ()), rules_v220=True)
        self.assertTrue(any(e["rule"] == "H-21" for e in errors))

    def test_locked_past_is_kept(self):
        errors = validate_first_trial(self.bad(), HistoryInput((), ()), rules_v220=True,
                                      locked_cells=(("1", 6), ("1", 7), ("1", 9)))
        self.assertFalse(any(e["rule"] == "H-21" for e in errors))


if __name__ == "__main__":
    unittest.main()
