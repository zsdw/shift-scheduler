"""2026-09-28 N2/FM plan using the assumed 27 Sep FM duty balance."""
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path

from night_shift.models import Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, build_context, run_schedule
from run_oct_n4_fm import GENERAL, NAMES, SOURCE_27, totals_for
from run_v26 import render as render_standard, runs
from run_v27 import posture_triples


def context(night_type=NightType.N2):
    staff = tuple(StaffInput(p, NAMES[p], True, True, int(p), False) for p in GENERAL)
    staff += (StaffInput("A", NAMES["A"], True, False, None, True),)
    return build_context(ShiftRequest(date(2026, 9, 28), night_type, Mode.FM, staff))


def report(record, attempts, version="2.10"):
    night_type = record.context.night_type
    text = render_standard(record)
    text = text.replace("2026-09-28 N1", f"2026-09-28 {night_type.value}", 1).replace("v2.6", f"v{version}")
    if night_type == NightType.N2:
        text = text.replace("18시·07시 I1 표기자는 실제 L3 입식근무입니다.",
                            "18시 I1 표기자는 실제 L3 입식이고, 07시 I1 표기자는 실제 I1 좌식근무입니다.")
        text = text.replace("FM 심야 I1은 실제 좌식근무입니다.",
                            "N2이므로 06~07시 남문은 미운영입니다. FM 심야 I1은 실제 좌식근무입니다.")
    elif night_type == NightType.N3:
        text = text.replace("18시 A의 L3 표기는 실제 보안실 대기이며, 18시·07시 I1 표기자는 실제 L3 입식근무입니다.",
                            "N3의 18시 L3와 I1은 각각 표기자가 실제 정위치하며, 07시 I1 표기자는 실제 L3 입식근무입니다.")
        text = text.replace("FM 심야 I1은 실제 좌식근무입니다.",
                            "N3이므로 18~20시 남문은 미운영입니다. FM 심야 I1은 실제 좌식근무입니다.")
        text = text.replace("휴게성 I1과 18시 A의 L3도 표시 횟수에는 포함합니다.",
                            "표기된 포스트 배정은 실제 배정 횟수로 집계합니다.")
        text = text.replace("A의 18시 L3는 실제 입식에 포함하지 않습니다.",
                            "N3의 18시 L3는 실제 입식에 포함합니다.")
    text = text.replace("과거 이력 없음 · 계획표", "9월 27일 FM 가정 피로도 반영 · 계획표")
    lines = ["", "## 9월 27일과 오늘의 피로도 균형", "",
             "| 직원 | 27일 FM 추정 | 오늘 | 출근 1회당 평균 |",
             "|---|---:|---:|---:|"]
    for p in GENERAL:
        prior = SOURCE_27["fatigue_value"][int(p)-1]
        now = totals_for(record,p)["fatigue_value"]
        if p == "6":
            lines.append(f"| {p} {NAMES[p]} | 결근·비교 제외 | {now} | {now:.2f} |")
        else:
            lines.append(f"| {p} {NAMES[p]} | {prior} | {now} | {(prior+now)/2:.2f} |")
    manager_today = totals_for(record,"A")
    lines += [f"| A 통제 A | 12 | {manager_today['fatigue_value']} | 관리자 별도 |", "",
              "27일 FM 운영을 가정하고, 20시 보안실의 4번 광희를 설치자(+1점), 04시 보안실의 A를 철수자(+1점)로 추정했습니다. 광희의 오늘 연속회차 설치를 금지했고, A의 전 회차 철수→오늘 설치는 소프트 회피했습니다.",
              "27일 결근한 준호를 0점 근무로 넣지 않았습니다. 27일 원본 표의 현행 규칙 위반을 오늘 계획표에 복제하지 않았습니다.", "",
              "## 소프트룰 점검", ""]
    if version in ("2.12", "2.13"):
        lines.insert(-3, "27일은 확정된 실제 이력이 아닌 FM 가정표이며, 출근한 일반근무자 5명 모두 순찰했습니다. 따라서 직전 실제 회차 순찰 제외자를 임의로 지정하지 않았습니다.")
    if version == "2.13":
        lines.insert(-3, "v2.13의 하층부 순찰 회전·soft debt는 직전 2회 이상의 확정된 실제 순찰 이력과 누적값이 없어 이번 계획표에는 가정값을 부여하지 않았습니다.")
    fatigue = [totals_for(record,p)["fatigue_value"] for p in GENERAL]
    rest = [totals_for(record,p)["actual_rest_time_value"] for p in GENERAL]
    lines.append(f"- 일반근무자 당일 피로도 격차 {max(fatigue)-min(fatigue)}점, 실휴게 격차 {max(rest)-min(rest)}시간.")
    triples = posture_triples(record)
    if triples:
        lines.append("- H-06 같은 자세 3연속 회피 미충족: " + ", ".join(f'{x["employee"]}번 {x["start_hour"]:02d}시 {x["posture"]}' for x in triples) + ". 하드룰과 관리자 최소부담·일반근무자 균형을 먼저 고정한 해에서 발생했습니다.")
    else:
        lines.append("- H-06 같은 자세 3연속 회피: 발생 0건.")
    long_runs = [(p,runs([r for r in record.assignments if r.employee_id == p],True)[0]) for p in (*GENERAL,"A")]
    four = [(p,n) for p,n in long_runs if n >= 4]
    if four:
        lines.append("- H-08 가급적 3시간 이내 선호 미충족: " + ", ".join(f"{p}번 {n}시간" for p,n in four) + ". 5시간 금지 및 4시간 중 좌식 포함 하드룰은 지켰습니다.")
    else:
        lines.append("- H-08 가급적 3시간 이내 선호: 전원 충족.")
    if version in ("2.12", "2.13"):
        long_rest = [(p, runs([r for r in record.assignments if r.employee_id == p],rest=True)[0]) for p in (*GENERAL,"A")]
        four_rest = [(p,n) for p,n in long_rest if n >= 4]
        lines.append("- H-06-1 실제 휴게성 4시간 이상 연속 회피: " + (", ".join(f"{p}번 {n}시간" for p,n in four_rest) + " 발생(강한 소프트룰 미충족)." if four_rest else "전원 충족."))
        actual_five = [(p,n) for p,n in long_runs if n >= 5]
        by_slot = {(r.employee_id,r.slot.index):r for r in record.assignments}
        barrier_sandwich = [(p,t) for p in (*GENERAL,"A") for t in (2,10) if
                            (by_slot[p,t].barrier_install_flag or by_slot[p,t].barrier_remove_flag) and
                            by_slot[p,t].actual_post_or_work_type.kind == "barrier_only" and
                            by_slot[p,t-1].actual_work_time_value == 1 and by_slot[p,t+1].actual_work_time_value == 1]
        lines.append("- 15-7 차단봉 단독업무의 포스트 사이 끼임: " + (", ".join(f"{p}번 {((18+t)%24):02d}시" for p,t in barrier_sandwich) + " 발생(회피 선호 미충족)." if barrier_sandwich else "발생 0건."))
        lines.append("- 차단봉을 포함한 실제업무 5시간 이상 연속: " + (", ".join(f"{p}번 {n}시간" for p,n in actual_five) + " 발생." if actual_five else "발생 0건."))
    stage = {a["stage"]: a for a in attempts if "stage" in a}
    lines += ["", "최적화 단계: " + ", ".join(f'{k}={v["value"]}({v["status"]})' for k,v in stage.items()) + ".", ""]
    return text + "\n" + "\n".join(lines)


def main(night_type=NightType.N2, version="2.10", *, actual_records=(), soft_debt=None):
    prior = {attr:dict(zip(GENERAL,values)) for attr,values in SOURCE_27.items()}
    nights = {p:int(p != "6") for p in GENERAL}
    selection = HistorySelection(actual_records=tuple(actual_records), assumed_totals=prior,
                                 assumed_nights=nights, soft_debt=soft_debt,
                                 previous_install_ids=("4",), previous_remove_ids=("A",),
                                 forbid_install_ids=("4",))
    outcome = run_schedule(context(night_type), selection,
                           SolveOptions(rules_version=version, seconds=45,
                                        prioritize_history_within_daily_targets=(night_type == NightType.N3)))
    result = outcome.solve_result
    rotation_due = outcome.prepared_inputs.patrol_rotation_priority_ids
    print(result.status,result.attempts,flush=True)
    if result.record is None:
        raise RuntimeError("No validated N2 plan: " + result.status)
    errors = list(outcome.validation_errors)
    if errors:
        raise RuntimeError("Independent validation failed: " + str(errors))
    if any(r.employee_id == "4" and r.barrier_install_flag for r in result.record.assignments):
        raise RuntimeError("27 Sep installer repeated on the next shift")
    root = Path(__file__).parent / f"results/2026-09-28-{night_type.value}-FM-A-plus-6-v{version}-history27"
    payload = {"rulebook":f"v{version}", "27_sep":"Assumed FM, A manager, 5 general workers; 20 security #4 installs and 04 security A removes", "numbering":NAMES,
               "confirmed_actual_records": len(actual_records), "patrol_rotation_due": sorted(rotation_due), "soft_debt_input": soft_debt or {},
               "historical_totals":prior,"historical_nights":nights,"result":asdict(result),"validation_errors":errors}
    Path(str(root)+".json").write_text(json.dumps(payload,ensure_ascii=False,default=str,indent=2),encoding="utf-8")
    Path(str(root)+".md").write_text(report(result.record,result.attempts,version),encoding="utf-8-sig")
    print("VALIDATED",root,flush=True)


if __name__ == "__main__":
    main()
