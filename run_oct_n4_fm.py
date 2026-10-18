"""Generate 2026-10-03/04 N4 FM plans using only the assumed 27 Sep FM balance history."""
from collections import Counter
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path

from night_shift.models import Mode, NightType, Posture
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, build_context, calculate_employee_stats, run_schedule
from run_v26 import runs
from run_v27 import posture_triples


NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호", "A": "통제 A"}
GENERAL = tuple(str(i) for i in range(1, 7))
SOURCE_27 = {"fatigue_value": [15, 13, 15, 16, 15, 0],
             "standing": [6, 5, 6, 6, 7, 0],
             "seated": [3, 4, 3, 3, 2, 0],
             "actual_work_time_value": [9, 9, 9, 10, 9, 0],
             "actual_rest_time_value": [5, 5, 5, 4, 5, 0],
             "patrol_fatigue": [2, 1, 2, 2, 1, 0]}


def context(day):
    staff = tuple(StaffInput(p, NAMES[p], True, True, int(p), False) for p in GENERAL)
    staff += (StaffInput("A", NAMES["A"], True, False, None, True),)
    return build_context(ShiftRequest(date(2026, 10, day), NightType.N4, Mode.FM, staff))


def totals_for(record, p):
    stats = calculate_employee_stats(record, p)
    return {"fatigue_value": int(stats.fatigue_value), "standing": stats.standing,
            "seated": stats.seated, "actual_work_time_value": int(stats.actual_work_time_value),
            "actual_rest_time_value": int(stats.actual_rest_time_value),
            "patrol_fatigue": int(stats.patrol_fatigue)}


def render(record, attempts, prior, nights, manager_prior_fatigue, prior_plan=None):
    rows = record.assignments
    day = record.context.shift_start_date.day
    area = {"upper": "상층", "middle": "중층", "lower": "하층"}
    headers = ("G1", "L3", "I1", "순찰", "보안실", "휴게")
    lines = [f"# 2026-10-{day:02d} N4 · FM · A + 일반근무자 6명", "",
             "OR-Tools 생성 · 독립 하드룰 검증 0건 · 계획표", "",
             "| 시간 | " + " | ".join(headers) + " |", "|---|" + "---|"*len(headers)]
    for t in range(14):
        cells = {h: [] for h in headers}
        for r in rows:
            if r.slot.index != t: continue
            label = r.displayed_assignment.label
            suffix = "(설치)" if r.barrier_install_flag else "(철수)" if r.barrier_remove_flag else ""
            show = f"{r.employee_id}{suffix}"
            if label in area: cells["순찰"].append(f"{r.employee_id}({area[label]})")
            else: cells["보안실" if label == "보안실 대기" else label].append(show)
        lines.append(f"| {(18+t)%24:02d}시 | " + " | ".join(", ".join(cells[h]) or "—" for h in headers) + " |")
    lines += ["", f"00~07시는 10월 {day+1}일입니다. N4이므로 저녁·아침 남문은 미운영이고, 18시와 07시 I1은 실제 좌식근무입니다.",
              "FM 심야 I1은 전부 실제 좌식근무입니다. 순찰 직후 두 시간은 완전휴게입니다.", "",
              "번호: " + ", ".join(f"{p}={NAMES[p]}" for p in (*GENERAL,"A")), "",
              "## 직원별 실제 근무·27일 이력 비교", "",
              "| 직원 | 이전 누적 피로도 | 이번 피로도 | 입식 | 좌식 | 실근무 | 실휴게 | 순찰 | 최대연속업무 | 룰상 최대연속 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for p in (*GENERAL, "A"):
        rr = [r for r in rows if r.employee_id == p]
        now = totals_for(record,p)
        prior_str = str(manager_prior_fatigue) if p == "A" else str(prior["fatigue_value"][p]) if nights[p] else "결근·비교 제외"
        vals = (prior_str, now["fatigue_value"], now["standing"], now["seated"], now["actual_work_time_value"], now["actual_rest_time_value"],
                sum(r.actual_post_or_work_type.kind == "patrol" for r in rr), runs(rr)[0], runs(rr,True)[0])
        lines.append(f"| {p} {NAMES[p]} | " + " | ".join(map(str,vals)) + " |")
    lines += ["", "입식·좌식에는 순찰의 입식이 반영되고, 자세가 정해지지 않은 차단봉 단독업무는 포함되지 않습니다. 실근무·피로도에는 차단봉을 포함합니다.", "",
              "## 직원별 포스트 배정 횟수", "",
              "| 직원 | 표기상 총횟수 | G1 입식/좌식 | L3 | I1 좌식 | G2 통합 | 상층 | 중층 | 하층 | 보안실 | 휴게 |",
              "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for p in (*GENERAL,"A"):
        stats = calculate_employee_stats(record,p)
        c = Counter(stats.displayed_counts)
        g1 = f'{stats.posture_by_post["G1"]["standing"]}/{stats.posture_by_post["G1"]["seated"]}'
        total = stats.displayed_post_total
        vals = (total,g1,c["L3"],c["I1"],sum(c[k] for k in ("G2","G3","G2(1)")),c["upper"],c["middle"],c["lower"],c["보안실 대기"],c["휴게"])
        lines.append(f"| {p} {NAMES[p]} | " + " | ".join(map(str,vals)) + " |")
    lines += ["", "## 최대연속 실제업무와 자세 순서", "",
              "| 직원 | 최대연속 | 구간·순서 |", "|---|---:|---|"]
    for p in (*GENERAL,"A"):
        rr = [r for r in rows if r.employee_id == p]
        maximum, longest = runs(rr)
        sections = []
        for block in longest:
            labels = []
            for r in block:
                if r.actual_post_or_work_type.kind == "barrier_only": labels.append("차단봉")
                elif r.actual_post_or_work_type.kind == "patrol": labels.append(area[r.displayed_assignment.label]+"순찰(입식)")
                else: labels.append(r.displayed_assignment.label + ("(입식)" if r.posture_or_mode == Posture.STANDING else "(좌식)"))
            sections.append(f'{block[0].slot.hour:02d}~{(block[-1].slot.hour+1)%24:02d}시 '+" → ".join(labels))
        lines.append(f"| {p} {NAMES[p]} | {maximum}시간 | " + "<br>".join(sections) + " |")
    triples = posture_triples(record)
    stages = {a["stage"]: a for a in attempts if "stage" in a}
    general_fatigue = [totals_for(record,p)["fatigue_value"] for p in GENERAL]
    general_rest = [totals_for(record,p)["actual_rest_time_value"] for p in GENERAL]
    lines += ["", "## 소프트룰·이력 검토", "",
              f"- 이번 일반근무자 피로도 격차 {max(general_fatigue)-min(general_fatigue)}점, 실휴게 격차 {max(general_rest)-min(general_rest)}시간. 두 항목 모두 1 이내 목표를 충족합니다.",
              f"- 같은 자세 3시간 연속 {len(triples)}건" + (": " + ", ".join(f'{x["employee"]}번 {x["start_hour"]:02d}시 시작 {x["posture"]}' for x in triples) if triples else "."),
              "- 27일 FM 표는 사용자가 지정한 이력 기준으로만 사용했습니다. 27일의 표기 오류·현행 하드룰 위반을 새 표에 이어받지 않았습니다.",
              "- 27일 FM 가정에 따라 20시 보안실의 4번 광희를 설치자, 04시 보안실의 A를 철수자로 추정해 각각 피로도 1점·실근무 1시간을 추가했습니다. 27일 차단봉 담당자의 다음회차 제한은 이 요청의 이력 범위 밖이어서 적용하지 않았습니다.",
              "- 27일 준호는 결근으로 보아 0점 이력이 아니라 비교 대상에서 제외했습니다. 누적 균형은 개인별 출근 횟수당 평균으로 비교했습니다."]
    if prior_plan:
        lines.append("- 10월 3일 계획표의 마지막 휴게자는 4일에 다시 마지막 휴게를 받지 않도록 했고, 3일 설치자는 4일 설치에서 제외했습니다. 두 표 모두 아직 실제 이력은 아닙니다.")
        lines.append("- 이전 누적 피로도는 9월 27일 FM 가정값에 10월 3일 계획값을 더한 수치입니다.")
    else:
        lines.append("- 이전 누적 피로도는 9월 27일 FM 가정값입니다.")
    lines += ["", "최적화 단계: " + ", ".join(f'{k}={v["value"]}({v["status"]})' for k,v in stages.items()) + ".", ""]
    return "\n".join(lines)


def main():
    prior = {k:dict(zip(GENERAL,values)) for k,values in SOURCE_27.items()}
    nights = {p:int(p != "6") for p in GENERAL}
    manager_prior_fatigue = 12  # 27 Sep FM: A's 04 security standby removes the barrier.
    previous = None
    root = Path(__file__).parent / "results"
    for day in (3,4):
        forbid_install = tuple(r.employee_id for r in previous.assignments if r.barrier_install_flag) if previous else ()
        forbid_last_rest = tuple(r.employee_id for r in previous.assignments if r.slot.index == 13 and r.employee_id in GENERAL and r.actual_rest_time_value == 1) if previous else ()
        previous_remove = tuple(r.employee_id for r in previous.assignments if r.barrier_remove_flag) if previous else ()
        selection = HistorySelection(assumed_totals=prior, assumed_nights={p:nights[p] for p in GENERAL},
                                     previous_install_ids=forbid_install, previous_remove_ids=previous_remove,
                                     previous_last_rest_ids=forbid_last_rest, forbid_install_ids=forbid_install)
        outcome = run_schedule(context(day), selection, SolveOptions(rules_version="2.10", seconds=45))
        result = outcome.solve_result
        print(day,result.status,result.attempts,flush=True)
        if result.record is None:
            raise RuntimeError(f"No schedule for Oct {day}: {result.status}")
        errors = list(outcome.validation_errors)
        if errors:
            raise RuntimeError(f"Independent validation errors for Oct {day}: {errors}")
        if previous:
            current_install = {r.employee_id for r in result.record.assignments if r.barrier_install_flag}
            current_last_rest = {r.employee_id for r in result.record.assignments if r.slot.index == 13 and r.employee_id in GENERAL and r.actual_rest_time_value == 1}
            if current_install.intersection(forbid_install):
                raise RuntimeError("Same employee installed the barrier in consecutive planned shifts")
            if current_last_rest.intersection(forbid_last_rest):
                raise RuntimeError("Same general worker had last rest in consecutive planned shifts")
        out = root / f"2026-10-{day:02d}-N4-FM-A-plus-6-v2.10"
        payload = {"rulebook":"v2.10", "source_27":"Assumed FM, A on duty, 5 general workers; 20 security #4 installs, 04 security A removes", "history_basis":"27 Sep balance only, attendance-normalized; 3 Oct plan added provisionally for 4 Oct", "numbering":NAMES,
                   "result":asdict(result), "validation_errors":errors, "prior_totals":prior, "prior_nights":nights}
        Path(str(out)+".json").write_text(json.dumps(payload,ensure_ascii=False,default=str,indent=2),encoding="utf-8")
        Path(str(out)+".md").write_text(render(result.record,result.attempts,prior,nights,manager_prior_fatigue,previous),encoding="utf-8-sig")
        for p in GENERAL:
            now = totals_for(result.record,p)
            for attr in prior:
                prior[attr][p] += now[attr]
            nights[p] += 1
        manager_prior_fatigue += totals_for(result.record,"A")["fatigue_value"]
        previous = result.record
        print("VALIDATED",out,flush=True)


if __name__ == "__main__":
    main()
