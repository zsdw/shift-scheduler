"""Generate another v2.10 schedule with at least one different duty assignment."""
from dataclasses import asdict
from pathlib import Path
import json

from run_v26 import render
from run_v27 import posture_triples
from run_v210_a_absent import context, soft_report
from night_shift.models import HistoryInput
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


def main():
    root = Path(__file__).parent / "results"
    first_path = root / "2026-09-28-FM-A-absent-overall-absence-1-v2.10.json"
    previous = json.loads(first_path.read_text(encoding="utf-8"))["result"]["record"]["assignments"]
    history = HistoryInput((), ())
    result = solve_first_trial(context(), history, seconds=30, rules_v210=True, exclude_assignments=previous)
    print(result.status, result.attempts, flush=True)
    if result.record is None:
        raise RuntimeError("No distinct schedule: " + result.status)
    errors = validate_first_trial(result.record, history, rules_v210=True)
    if errors:
        raise RuntimeError(errors)
    old = {(r["employee_id"], r["slot"]["index"]): r for r in previous}
    differences = [
        (r.employee_id, r.slot.hour, old[r.employee_id, r.slot.index]["displayed_assignment"]["label"], r.displayed_assignment.label)
        for r in result.record.assignments
        if (r.displayed_assignment.label != old[r.employee_id, r.slot.index]["displayed_assignment"]["label"]
            or r.barrier_install_flag != old[r.employee_id, r.slot.index]["barrier_install_flag"]
            or r.barrier_remove_flag != old[r.employee_id, r.slot.index]["barrier_remove_flag"])
    ]
    if not differences:
        raise RuntimeError("Solver returned the excluded schedule")
    triples = posture_triples(result.record)
    report = render(result.record).replace("v2.6", "v2.10")
    report += "\n전체 결근자 1명(A 결근) 기준을 적용했다. 이는 v2.10 제2-1장의 일반근무자 결원수 표기와 다른 사용자 지정 해석이다.\n"
    report += f'순찰을 입식으로 계산한 H-06 점검: 입식 3연속 {sum(x["posture"] == "standing" for x in triples)}건, 좌식 3연속 {sum(x["posture"] == "seated" for x in triples)}건.\n'
    report += f"이전 표와 비교해 직원·시간별 배정이 {len(differences)}칸 다르다.\n"
    report += soft_report(result.record, result.attempts)
    out = root / "2026-09-28-FM-A-absent-overall-absence-1-v2.10-alt"
    payload = {"rulebook": "v2.10", "staffing_interpretation": "overall absence count, per user", "result": asdict(result), "validation_errors": errors, "same_posture_triples": triples, "different_slots": differences}
    Path(str(out) + ".json").write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    Path(str(out) + ".md").write_text(report, encoding="utf-8-sig")
    print("VALIDATION: 0 errors; changed assignment slots:", len(differences))


if __name__ == "__main__":
    main()
