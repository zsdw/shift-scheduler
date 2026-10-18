"""Apply three explicit exchanges to the saved plan, then independently validate.

This path needs no OR-Tools and never claims a fresh solver result.
"""
from dataclasses import dataclass, replace
from datetime import date
import json
from pathlib import Path
from night_shift.models import Employee, Attendance, ShiftContext, Mode, NightType, ShiftRecord, RecordKind
from night_shift.profiles import make_record
from revise_trial import render_revision


@dataclass
class EditedResult:
    status: str
    record: ShiftRecord
    attempts: list
    targets_met: bool


def revised_record():
    output = Path(__file__).parent / "results"
    original = json.loads((output / "2026-09-28-FM.json").read_text(encoding="utf-8"))["result"]["record"]
    source = original["context"]
    c = ShiftContext(date.fromisoformat(source["shift_start_date"]), NightType(source["night_type"]),
                     Mode(source["requested_mode"]), Mode(source["effective_mode"]),
                     tuple(Employee(**p) for p in source["employees"]),
                     tuple(Attendance(**a) for a in source["attendance"]))
    rows = {}
    for r in original["assignments"]:
        key = r["employee_id"], r["slot"]["index"]
        rows[key] = make_record(c, *key, r["displayed_assignment"]["label"],
                               install=r["barrier_install_flag"], remove=r["barrier_remove_flag"])
    # Assert the exact original duties before changing; no silent reuse on another plan.
    exchanges = [(6, "A", "보안실 대기", "6", "G1"),
                 (8, "A", "G1", "6", "휴게"),
                 (10, "A", "L3", "3", "I1")]
    for t, a, expected_a, b, expected_b in exchanges:
        if rows[a, t].displayed_assignment.label != expected_a or rows[b, t].displayed_assignment.label != expected_b:
            raise ValueError("Saved original differs from reviewed source; re-evaluate exchanges")
        rows[a, t] = make_record(c, a, t, expected_b)
        rows[b, t] = make_record(c, b, t, expected_a)
    # One displayed standby per slot; all other off-duty people explicitly rest.
    standby = {0: "2", 1: "1", 2: "3", 3: "1", 4: "4", 5: "1", 6: "4",
               7: "1", 8: "3", 9: "2", 10: "2", 11: "6", 12: "3", 13: "5"}
    for (p, t), r in list(rows.items()):
        if r.displayed_assignment.label in ("휴게", "보안실 대기"):
            label = "보안실 대기" if standby[t] == p else "휴게"
            rows[p, t] = make_record(c, p, t, label, install=r.barrier_install_flag, remove=r.barrier_remove_flag)
    record = ShiftRecord("trial-2026-09-28-FM-revised", RecordKind.PLAN, c, tuple(rows.values()))
    # Recomputed objectives, not a claim of solver optimality.
    fatigue = [sum(r.fatigue_value for r in rows.values() if r.employee_id == str(p)) for p in range(1, 7)]
    rest = [sum(r.actual_rest_time_value for r in rows.values() if r.employee_id == str(p)) for p in range(1, 7)]
    result = EditedResult("EDITED_AND_INDEPENDENTLY_VALIDATED", record,
                          [{"method": "three explicit assignment exchanges; no new CP-SAT run"}],
                          max(fatigue) - min(fatigue) <= 1 and max(rest) - min(rest) <= 1)
    return result, original["assignments"]


if __name__ == "__main__":
    render_revision(*revised_record())
