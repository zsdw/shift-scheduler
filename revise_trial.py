"""Preserve the original trial, minimally revise it, validate and export text/JSON."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from night_shift.models import HistoryInput, Mode
from night_shift.validator import validate_first_trial


def main():
    from run_trial import context
    from night_shift.solver import solve_first_trial
    output = Path(__file__).parent / "results"
    original = json.loads((output / "2026-09-28-FM.json").read_text(encoding="utf-8"))
    baseline = original["result"]["record"]["assignments"]
    history = HistoryInput((), ())
    result = solve_first_trial(context(Mode.FM), history, refinement=True, baseline_assignments=baseline)
    if result.record is None:
        raise RuntimeError((result.status, result.attempts))
    result.record = replace(result.record, record_id="trial-2026-09-28-FM-revised")
    render_revision(result, baseline)


def render_revision(result, baseline):
    output = Path(__file__).parent / "results"
    history = HistoryInput((), ())
    errors = validate_first_trial(result.record, history, refinement=True)
    if errors:
        raise RuntimeError(errors)
    rows = result.record.assignments
    payload = {"result": asdict(result), "revision_rules": "spec/revision-2026-09-28.md",
               "independent_validation": {"errors": errors, "scope": "N1/6/A/no-history/refinement"}}
    (output / "2026-09-28-FM-revised.json").write_text(json.dumps(payload, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    headers = ["G1", "L3", "I1", "G3", "G2", "G2(1)", "순찰", "보안실", "휴게"]
    lines = ["# 2026년 9월 28일 FM 야간 근무표 — 수정안", "",
             "N1 · 일반 6명 + A · 모든 과거 이력 없음 · 사용자 확인 전 시험안", "",
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
    lines += ["", "00~07시는 9월 29일입니다. 보안실 열은 매시간 1명이며, 순찰 후 2시간은 휴게로 표시했습니다.",
              "18시 A는 L3 표기/실제 보안실 대기이므로 보안실 열에는 중복으로 넣지 않았습니다. 18시 I1 표기자는 실제 L3, 07시 L3·I1 표기자는 둘 다 실제 L3 입식근무입니다.", "",
              "## A의 00~05시 배정", ""]
    manager = sorted((r for r in rows if r.employee_id == "A" and 6 <= r.slot.index <= 11), key=lambda r: r.slot.index)
    lines += [" → ".join(f"{r.slot.hour:02d}시 {r.displayed_assignment.label}" for r in manager), "",
              "연속 실제근무 최대 2시간을 적용했습니다. 04시는 근무 시 I1 우선이며, 근무 자체를 강제하지 않습니다.", "",
              "## 직원별 실제 집계", "", "| 직원 | 피로도 | 입식 | 좌식 | 실근무 | 실휴게 | 순찰 |", "|---|---:|---:|---:|---:|---:|---:|"]
    fatigue, rest = [], []
    for p in [str(i) for i in range(1, 7)] + ["A"]:
        rr = [r for r in rows if r.employee_id == p]
        values = [sum(r.fatigue_value for r in rr), sum(r.posture_or_mode == "standing" for r in rr), sum(r.posture_or_mode == "seated" for r in rr), sum(r.actual_work_time_value for r in rr), sum(r.actual_rest_time_value for r in rr), sum(r.actual_post_or_work_type.kind == "patrol" for r in rr)]
        lines.append("| " + p + " | " + " | ".join(map(str, values)) + " |")
        if p != "A":
            fatigue.append(values[0]); rest.append(values[4])
    lines += ["", f"일반근무자 피로도 차이 {max(fatigue)-min(fatigue)}점, 실휴게 차이 {max(rest)-min(rest)}시간.",
              "순찰·차단봉 단독업무는 실근무에 포함하며, 자세가 명시되지 않은 업무는 입식/좌식으로 임의 집계하지 않습니다.", "",
              "## 기존 시험표 대비 업무 변경", ""]
    old_rows = {(r["employee_id"], r["slot"]["index"]): r for r in baseline}
    changes = []
    for r in rows:
        old = old_rows[r.employee_id, r.slot.index]
        old_label, label = old["displayed_assignment"]["label"], r.displayed_assignment.label
        off = {"휴게", "보안실 대기"}
        label_changed = old_label != label and not (old_label in off and label in off)
        if label_changed or old["barrier_install_flag"] != r.barrier_install_flag or old["barrier_remove_flag"] != r.barrier_remove_flag:
            changes.append(f"- {r.slot.hour:02d}시 {r.employee_id}: {old_label} → {label}")
    lines += changes or ["업무 배정 변경 없음."]
    lines += ["", "휴게/보안실 단순 표기 교체는 위 업무 변경 목록에서 제외했습니다.", "",
              "독립 검증 오류 0건. 기존 하드룰과 추가 보안실 표기·A 연속근무 제한을 재검증했습니다. 기존 업무를 가능한 한 유지하여 수정했으며, 최소 변경 또는 전체 밸런스의 전역 최적해를 증명한 것은 아닙니다.",
              "원본 시험표는 보존했고, 실제 이력 확정은 하지 않았습니다."]
    (output / "2026-09-28-FM-revised.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": result.status, "errors": errors, "attempts": result.attempts,
                      "A": [(r.slot.hour, r.displayed_assignment.label) for r in manager],
                      "changes": changes}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
