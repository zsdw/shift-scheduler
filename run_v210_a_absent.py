"""v2.10 trial: N1/FM, A absent, Jun-ho number 1 plus workers 2–6."""
from dataclasses import asdict
from datetime import date
from pathlib import Path
import json

from run_v26 import render, runs
from run_v27 import posture_triples
from night_shift.models import Attendance, Employee, HistoryInput, Mode, NightType, ShiftContext
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


def context():
    employees = tuple(Employee(str(i), "준호" if i == 1 else f"일반 {i}") for i in range(1, 7)) + (Employee("A", "통제 A"),)
    attendance = (
        Attendance("1", True, False, 1, True),
        *(Attendance(str(i), True, True, i, False) for i in range(2, 7)),
        Attendance("A", False, False, None, False),
    )
    return ShiftContext(date(2026, 9, 28), NightType.N1, Mode.FM, Mode.FM, employees, attendance)


def soft_report(record, attempts):
    rows = record.assignments
    stage = {a["stage"]: a for a in attempts if "stage" in a}
    misses = []
    balance = stage.get("general_balance")
    if balance and balance["value"]:
        misses.append(f'- 일반근무자 실제 피로도·휴게시간의 완전 동일 선호: 합산 격차 {balance["value"]}. 관리자 실근무 8시간·피로도 12를 최소로 유지하면서 일반근무자 사이의 차이를 이 값까지 줄였다.')
    triples = posture_triples(record)
    if triples:
        details = ", ".join(f'{x["employee"]}번 {x["start_hour"]:02d}시 시작 ' + ("입식" if x["posture"] == "standing" else "좌식") for x in triples)
        misses.append(f'- H-06 같은 자세 3시간 연속 회피: {details}. 순찰도 입식으로 셌다. 관리자 부담 최소화와 일반근무자 균형을 먼저 고정한 해들에서 이 단계의 최솟값은 {stage["same_posture_triples"]["value"]}건이다.')
    long_runs = []
    for p in sorted({r.employee_id for r in rows}):
        rr = [r for r in rows if r.employee_id == p]
        maximum, _ = runs(rr, True)
        if maximum >= 4:
            long_runs.append(f"{p}번 {maximum}시간")
    if long_runs:
        misses.append('- H-08의 가급적 3시간 이내 연속근무 선호: ' + ", ".join(long_runs) + '. H-08의 5시간 금지와 4시간 중 좌식 포함 하드룰은 지켰다. 더 높은 우선순위의 관리자 부담·일반근무자 균형·같은 자세 3연속 최소값을 유지하면서 줄일 수 없는 4시간 구간이다.')
    general_ids = ("2", "3", "4", "5", "6")
    displayed_counts = {p:sum(r.employee_id == p and r.displayed_assignment.label in ("G1","L3","I1","G2","G3","G2(1)") for r in rows) for p in general_ids}
    if len(set(displayed_counts.values())) > 1:
        counts = ", ".join(f"{p}번 {n}회" for p,n in displayed_counts.items())
        misses.append('- 표시상 포스트 배정횟수의 완전 동일 선호: ' + counts + '. 일반근무자 5명의 합계가 ' + str(sum(displayed_counts.values())) + '회라 5명에게 정수 횟수로 똑같이 나눌 수 없고, 차이는 최대 1회다.')
    for t, title in ((2, "20시"), (10, "04시")):
        for r in rows:
            if r.slot.index == t and r.actual_post_or_work_type.kind == "barrier_only":
                p = r.employee_id
                before = next(x for x in rows if x.employee_id == p and x.slot.index == t-1)
                after = next(x for x in rows if x.employee_id == p and x.slot.index == t+1)
                if before.actual_work_time_value and after.actual_work_time_value:
                    misses.append(f'- 차단봉 단독업무를 앞뒤 실제근무 사이에 넣지 않는 선호: {p}번 {title}. 고정된 상위 최적화 값과 포스트 충원을 지키는 범위에서 이 연결을 피할 수 없었다.')
    manager = "1"
    m04 = next(r for r in rows if r.employee_id == manager and r.slot.index == 10)
    if m04.actual_work_time_value and m04.displayed_assignment.label != "I1":
        misses.append('- 8-6 관리자 04시 I1 우선: 1번 준호가 04시에 ' + m04.displayed_assignment.label + '을 맡았다. 앞선 하드룰 및 관리자 최소근무·피로도와 균형 우선순위를 지킨 결과다.')
    m07 = next(r for r in rows if r.employee_id == manager and r.slot.index == 13)
    if m07.actual_work_time_value:
        misses.append('- 8-3 관리자 07시 휴게 우선: 1번 준호가 07시 ' + m07.displayed_assignment.label + '을 맡았다. 07시 필수 포스트를 채우면서 더 높은 우선순위를 지킨 결과다.')
    if not misses:
        misses.append('- 확인한 적용 대상 소프트룰 중 미충족 항목 없음.')
    return "\n## 소프트룰 미충족과 이유\n\n" + "\n".join(misses) + "\n"


def main():
    history = HistoryInput((), ())
    result = solve_first_trial(context(), history, seconds=30, rules_v210=True)
    print(result.status, result.attempts, flush=True)
    if result.record is None:
        raise RuntimeError("No schedule: " + result.status)
    errors = validate_first_trial(result.record, history, rules_v210=True)
    if errors:
        raise RuntimeError(errors)
    out = Path(__file__).parent / "results/2026-09-28-FM-A-absent-overall-absence-1-v2.10"
    triples = posture_triples(result.record)
    report = render(result.record).replace("v2.6", "v2.10")
    report += "\n전체 결근자 1명(A 결근) 기준을 적용했다. 이는 v2.10 제2-1장의 일반근무자 결원수 표기와 다른 사용자 지정 해석이다.\n"
    report += f'순찰을 입식으로 계산한 H-06 점검: 입식 3연속 {sum(x["posture"] == "standing" for x in triples)}건, 좌식 3연속 {sum(x["posture"] == "seated" for x in triples)}건.\n'
    report += soft_report(result.record, result.attempts)
    payload = {"rulebook": "v2.10", "staffing_interpretation": "overall absence count, per user", "result": asdict(result), "validation_errors": errors, "same_posture_triples": triples}
    Path(str(out) + ".json").write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    Path(str(out) + ".md").write_text(report, encoding="utf-8-sig")
    print("VALIDATION: 0 errors; posture triples:", triples)


if __name__ == "__main__":
    main()
