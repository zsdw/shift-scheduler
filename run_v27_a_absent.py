"""N1/FM, five numbered workers, A absent, worker 1 acts as manager."""
from pathlib import Path
from dataclasses import asdict
from datetime import date
import json

from run_v26 import render
from run_v27 import posture_triples
from night_shift.models import Employee, Attendance, ShiftContext, Mode, NightType, HistoryInput
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


def context():
    employees = tuple(Employee(str(i), "준호" if i == 1 else f"일반 {i}") for i in range(1, 6)) + (Employee("A", "통제 A"),)
    attendance = (
        Attendance("1", True, False, 1, True),
        *(Attendance(str(i), True, True, i, False) for i in range(2, 6)),
        Attendance("A", False, False, None, False),
    )
    return ShiftContext(date(2026, 9, 28), NightType.N1, Mode.FM, Mode.FM, employees, attendance)


def main():
    history = HistoryInput((), ())
    result = solve_first_trial(context(), history, seconds=30, rules_v27=True)
    print(result.status, result.attempts, flush=True)
    if result.record is None:
        raise RuntimeError("No schedule: " + result.status)
    errors = validate_first_trial(result.record, history, rules_v27=True)
    if errors:
        raise RuntimeError(errors)
    triples = posture_triples(result.record)
    out = Path(__file__).parent / "results/2026-09-28-FM-5workers-A-absent-v2.7"
    payload = {"rulebook": "v2.7", "result": asdict(result), "validation_errors": errors, "same_posture_triples": triples}
    Path(str(out) + ".json").write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    report = render(result.record).replace("v2.6", "v2.7")
    report += "\n## v2.7 동일 자세 3시간 연속 점검\n\n"
    report += f'입식 3연속 {sum(x["posture"] == "standing" for x in triples)}건 · 좌식 3연속 {sum(x["posture"] == "seated" for x in triples)}건.\n'
    Path(str(out) + ".md").write_text(report, encoding="utf-8-sig")
    print("VALIDATION: 0 errors; posture triples:", triples)


if __name__ == "__main__":
    main()
