"""Current N1/6/A first-trial generation under v2.2; legacy runners preserve old versions."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from run_trial import context
from night_shift.models import HistoryInput, Mode
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


def main():
    history = HistoryInput((), ())
    result = solve_first_trial(context(Mode.FM), history, refinement=True, minimize_a=True, rules_v22=True)
    print(result.status, result.attempts, flush=True)
    if result.record is None:
        raise RuntimeError("No validated schedule; see solver status")
    result.record = replace(result.record, record_id="trial-2026-09-28-FM-v2.2")
    errors = validate_first_trial(result.record, history, refinement=True, rules_v22=True)
    if errors:
        raise RuntimeError(errors)
    out = Path(__file__).parent / "results"
    (out / "2026-09-28-FM-v2.2.json").write_text(json.dumps({"rulebook": "v2.2", "result": asdict(result), "validation_errors": errors}, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = result.record.assignments
    headers = ["G1", "L3", "I1", "G3", "G2", "G2(1)", "순찰", "보안실", "휴게"]
    lines = ["# 2026-09-28 FM 야간 시험표 — v2.2", "", "N1 · 일반 6명+A · 최초 무이력 · OR-Tools 생성 · 독립 검증 오류 0건 · 사용자 확인 전 계획", "",
             "| 시간 | " + " | ".join(headers) + " |", "|---|" + "---|"*len(headers)]
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
                cells[dest].append(r.employee_id + ("(설치)" if r.barrier_install_flag else "(철수)" if r.barrier_remove_flag else ""))
        lines.append(f"| {(18+t)%24:02d}:00 | " + " | ".join(", ".join(cells[h]) or "—" for h in headers) + " |")
    lines += ["", "00~07시는 9월 29일입니다. 18시 A는 L3 표기/실제 보안실 대기, I1 표기자는 실제 L3입니다. 07시 L3·I1 표기자는 실제로 함께 L3 근무합니다.", "",
              "| 직원 | 실근무 | 실휴게 | 피로도 | 입식 | 좌식 |", "|---|---:|---:|---:|---:|---:|"]
    for p in [str(i) for i in range(1,7)] + ["A"]:
        rr = [r for r in rows if r.employee_id == p]
        values = [sum(r.actual_work_time_value for r in rr), sum(r.actual_rest_time_value for r in rr), sum(r.fatigue_value for r in rr), sum(r.posture_or_mode == "standing" for r in rr), sum(r.posture_or_mode == "seated" for r in rr)]
        lines.append("| " + p + " | " + " | ".join(map(str, values)) + " |")
        print(p, values)
    lines += ["", "- A와 각 일반근무자의 실근무시간 차이: 최대 2시간 제한 적용.",
              "- 18~20시 G2·G3 합산 개인당 최대 1회, A 배정 금지 적용.",
              "- 매시간 보안실 1명 필수, 순찰 후 휴게 및 A 00~05시 3연속 금지 유지.",
              "- 일반근무자 피로도 차이 1점·휴게 차이 1시간 이내 목표 충족 여부: " + str(result.targets_met),
              "- 위 목표와 추가 선호를 만족하는 범위에서 A 실근무시간을 먼저 최소화하고, 그중 피로도를 최소화했습니다. 전체 조합 또는 모든 밸런스 항목의 최적화 증명은 아닙니다.",
              "- 순찰과 차단봉 단독업무는 실근무에 포함하며, 자세 미확정 업무는 입식/좌식으로 임의 분류하지 않습니다.",
              "- 이전 시험표는 별도 보존하며, 이번 결과도 실제 이력으로 확정하지 않았습니다."]
    (out / "2026-09-28-FM-v2.2.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
