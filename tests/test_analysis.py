import unittest
from types import SimpleNamespace

from night_shift.analysis import analyze_soft_rules, validation_rows
from night_shift.models import (
    Assignment, AssignmentKind as K, AssignmentRecord, Mode, Posture, SLOTS,
)
from night_shift.presentation import night_type_label


def row(index, *, work=False, rest=False, posture=Posture.REST_LIKE, barrier=False):
    display = Assignment(K.REST, "휴게")
    actual = Assignment(K.BARRIER_ONLY, "차단봉") if barrier else (
        Assignment(K.POST, "G1") if work else display)
    return AssignmentRecord(
        "1", SLOTS[index], display if not work else Assignment(K.POST, "G1"), actual,
        1 if work else 0, 1 if work else 0, 1 if rest else 0, posture,
        False, work and not barrier, rest, rest, barrier, False, Mode.FM, (),
    )


class AnalysisTests(unittest.TestCase):
    def test_observable_soft_findings_are_deterministic(self):
        rows = []
        for index in range(14):
            if index < 4:
                rows.append(row(index, work=True, posture=Posture.STANDING))
            elif 4 <= index <= 8 or index >= 12:
                rows.append(row(index, rest=True))
            elif index == 10:
                rows.append(row(index, work=True, posture=Posture.SEATED, barrier=True))
            else:
                rows.append(row(index, work=True, posture=Posture.SEATED))
        person = SimpleNamespace(name="시험", display_number=1)
        result = SimpleNamespace(
            record=SimpleNamespace(assignments=tuple(rows)),
            employee_stats={"1": person},
            context=SimpleNamespace(attendance=(SimpleNamespace(
                employee_id="1", present=True, acts_as_manager=False),)),
            prepared_inputs=SimpleNamespace(
                previous_install_ids=(), previous_remove_ids=(),
                patrol_rotation_priority_ids=()),
        )
        findings = analyze_soft_rules(result)
        rules = {finding.rule_id for finding in findings}
        self.assertTrue({"H-06", "H-06-1", "H-08", "15-7"}.issubset(rules))
        self.assertTrue(all(finding.detail for finding in findings))

    def test_labels_and_validator_normalization(self):
        self.assertEqual(night_type_label("N4"), "N4 (공휴일 → 공휴일)")
        result = SimpleNamespace(validation_errors=(
            {"rule": "H-X", "employee_id": "3", "slot": "04시", "detail": "시험 위반"},
        ))
        self.assertEqual(validation_rows(result)[0], {
            "규칙": "H-X", "대상 직원": "3", "시간대": "04시", "실제 위반내용": "시험 위반",
        })


if __name__ == "__main__":
    unittest.main()
