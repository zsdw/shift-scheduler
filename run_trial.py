"""Generate unconfirmed first-trial plans and a readable FM result."""
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
from night_shift.models import Employee, Attendance, ShiftContext, Mode, NightType, HistoryInput
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


def context(mode):
    employees = tuple(Employee(str(i), f"일반 {i}") for i in range(1, 7)) + (Employee("A", "통제 A"),)
    attendance = tuple(Attendance(str(i), True, True, i, False) for i in range(1, 7)) + (Attendance("A", True, False, None, True),)
    return ShiftContext(date(2026, 9, 28), NightType.N1, mode, mode, employees, attendance)


def main():
    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    history = HistoryInput((), ())
    for mode in (Mode.FLEXIBLE, Mode.FM):
        result = solve_first_trial(context(mode), history)
        if result.record is None:
            print(mode.value, result.status, result.attempts, flush=True)
            (out / f"{mode.value}-status.json").write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
            continue
        errors = validate_first_trial(result.record, history)
        print(mode.value, result.status, "validator errors", len(errors), result.attempts, flush=True)
        if errors:
            raise RuntimeError(errors)
        payload = {"result": asdict(result), "independent_validation": {"errors": errors, "scope": "N1/6/A/first-trial"}}
        (out / f"2026-09-28-{mode.value}.json").write_text(json.dumps(payload, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
        if mode != Mode.FM:
            continue
        rows = result.record.assignments
        headers = ["G1", "L3", "I1", "G3", "G2", "G2(1)", "순찰", "보안실", "휴게"]
        lines = ["# 2026년 9월 28일 FM 야간 시험 근무표", "", "N1 · 일반근무자 6명 + A · 과거 이력 없음 · 사용자 확인 전 시험안", "",
                 "번호 1~6은 이번 시험용 식별자이며 실제 직원 누적 이력이 아닙니다.", "",
                 "| 시간 | " + " | ".join(headers) + " |", "|---|" + "---|" * len(headers)]
        for t in range(14):
            cells = {h: [] for h in headers}
            for r in rows:
                if r.slot.index != t:
                    continue
                label = r.displayed_assignment.label
                if label in ("upper", "middle", "lower"):
                    cells["순찰"].append(r.employee_id + "(" + {"upper": "상층", "middle": "중층", "lower": "하층"}[label] + ")")
                else:
                    dest = "보안실" if label == "보안실 대기" else label
                    extra = "(설치)" if r.barrier_install_flag else "(철수)" if r.barrier_remove_flag else ""
                    cells[dest].append(r.employee_id + extra)
            lines.append(f"| {(18+t)%24:02d}:00 | " + " | ".join(", ".join(cells[h]) or "—" for h in headers) + " |")
        lines += ["", "00~07시는 9월 29일입니다. 18시 A는 L3 표기/실제 보안실 대기이고 I1 표기자가 실제 L3를 수행합니다. 07시 L3·I1 표기자는 모두 실제 L3 입식근무입니다.", "",
                  "| 직원 | 피로도 | 입식시간 | 좌식시간 | 실근무 | 실휴게 | 순찰횟수 |", "|---|---:|---:|---:|---:|---:|---:|"]
        fatigue, rest = [], []
        for p in [str(i) for i in range(1, 7)] + ["A"]:
            rr = [r for r in rows if r.employee_id == p]
            values = [sum(r.fatigue_value for r in rr), sum(r.posture_or_mode == "standing" for r in rr), sum(r.posture_or_mode == "seated" for r in rr), sum(r.actual_work_time_value for r in rr), sum(r.actual_rest_time_value for r in rr), sum(r.actual_post_or_work_type.kind == "patrol" for r in rr)]
            lines.append("| " + p + " | " + " | ".join(map(str, values)) + " |")
            if p != "A":
                fatigue.append(values[0]); rest.append(values[4])
        lines += ["", f"일반근무자 피로도 차이: {max(fatigue)-min(fatigue)}점. 실휴게 차이: {max(rest)-min(rest)}시간.",
                  "입식·좌식은 실제 포스트 자세 기준입니다. 순찰·차단봉 단독업무는 실근무에 포함하되 자세는 추정하지 않습니다.", "",
                  "독립 검증기: 오류 0건 (N1·6명·A·무이력 및 기본 운영 범위). A 07시 휴게와 차단봉 단독업무가 앞뒤 포스트 사이에 끼지 않는 선호도 함께 시험했습니다.",
                  "피로도 차이 ≤1·실휴게 차이 ≤1 목표를 만족하는 해를 찾은 것이며, 모든 밸런스 항목의 전역 최적해를 증명한 것은 아닙니다." if result.targets_met else "소프트 목표 동시 충족은 확인하지 못했습니다. solver 실행 기록에서 목표 탐색과 하드룰 탐색 결과를 구분합니다.",
                  "계획표를 실제 이력으로 저장하거나 사용자 승인 없이 확정하지 않았습니다."]
        (out / "2026-09-28-FM.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
