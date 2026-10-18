from pathlib import Path
from dataclasses import asdict
from datetime import date
from collections import Counter
import json
from night_shift.models import Mode, NightType
from night_shift.service import ShiftRequest, SolveOptions, StaffInput, build_context, calculate_employee_stats, consecutive_runs, run_schedule

def context():
    staff=tuple(StaffInput(str(i),f"일반 {i}",True,True,i,False) for i in range(1,6))
    staff+=(StaffInput("A","통제 A",True,False,None,True),)
    return build_context(ShiftRequest(date(2026,9,28),NightType.N1,Mode.FM,staff))

def runs(rows,rule=False,rest=False):
    blocks=consecutive_runs(rows,rule=rule,rest=rest)
    maximum=max(map(len,blocks),default=0)
    return maximum,[r for r in blocks if len(r)==maximum]

def render(record):
    rows=record.assignments
    attendance={a.employee_id:a for a in record.context.attendance}
    people=sorted(dict.fromkeys(r.employee_id for r in rows), key=lambda p:(attendance[p].display_number is None, attendance[p].display_number or 99, p))
    flexible = record.context.effective_mode == Mode.FLEXIBLE
    manager=next(a.employee_id for a in record.context.attendance if a.present and a.acts_as_manager)
    a_present=any(a.employee_id=="A" and a.present for a in record.context.attendance)
    numbered=sum(a.present and a.display_number is not None for a in record.context.attendance)
    staffing=f"{numbered}명+A" if a_present else f"{numbered}명 · A 부재({manager}번 관리자대행)"
    names={"upper":"상층","middle":"중층","lower":"하층"}
    headers=["G1","L3","I1","G3","G2","G2(1)","순찰","보안실","휴게"]
    employee_names={employee.employee_id:employee.name for employee in record.context.employees}
    roster=" · ".join(f"{p} {employee_names[p]}" for p in people)
    lines=[f"# {record.context.shift_start_date} N1 · {staffing} {'유도리' if flexible else 'FM'} 근무표 (v2.6)","",
           "OR-Tools 생성 · 독립 검증 오류 0건 · 과거 이력 없음 · 계획표","",
           f"**번호별 직원: {roster}**","",
           "| 시간 | "+" | ".join(headers)+" |","|---|"+"---|"*len(headers)]
    for t in range(14):
        cells={h:[] for h in headers}
        for r in rows:
            if r.slot.index!=t: continue
            label=r.displayed_assignment.label
            suffix="(설치)" if r.barrier_install_flag else "(철수)" if r.barrier_remove_flag else ""
            if label in names:cells["순찰"].append(r.employee_id+"("+names[label]+")")
            else:cells["보안실" if label=="보안실 대기" else label].append(r.employee_id+suffix)
        lines.append(f"| {(18+t)%24:02d}시 | "+" | ".join(", ".join(cells[h]) or "—" for h in headers)+" |")
    manager_label="A" if a_present else f"{manager}번 관리자대행"
    lines += ["",f"00~07시는 9월 29일입니다. 18시 {manager_label}의 L3 표기는 실제 보안실 대기이며, 18시·07시 I1 표기자는 실제 L3 입식근무입니다.",
              (("FM 4명 요청은 룰북 0-4에 따라 유도리로 자동 전환했습니다. 00~03시 I1은 실제 휴게성, 04시 I1은 차단봉 철수 실근무입니다. 순찰 후 다음 두 슬롯 중 최소 한 슬롯의 실제 휴게를 보장합니다.") if flexible else ("FM 심야 I1은 실제 좌식근무입니다. A 부재와 추가 결원 조건이므로 순찰 후 다음 두 슬롯 중 최소 한 슬롯의 완전휴게를 보장합니다." if not a_present and numbered < 6 else "FM 심야 I1은 실제 좌식근무입니다. 순찰 후 두 슬롯은 휴게로 배정했습니다.")),"",
              "## 직원별 실제 근무 요약","",
              "| 직원 | 피로도 | 입식 | 좌식 | 실근무 | 실휴게 | 순찰 | 최대 실제업무 연속 | 룰 판정상 최대연속 | 최대 연속 실휴게 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for p in people:
        rr=[r for r in rows if r.employee_id==p]
        stats=calculate_employee_stats(record,p)
        vals=[stats.fatigue_value,stats.standing,stats.seated,stats.actual_work_time_value,stats.actual_rest_time_value,stats.patrol_count,stats.max_actual_work_run,stats.max_rule_work_run,stats.max_rest_run]
        lines.append("| "+p+" | "+" | ".join(str(x) for x in vals)+" |")
    excluded="차단봉 단독업무와 유도리 04시 I1 철수" if flexible else "차단봉 단독업무"
    lines += ["",f"시간 단위: 1시간. 실제업무 연속에는 순찰·차단봉이 포함됩니다. 룰 판정에서는 순찰은 포함하고 {excluded}는 제외합니다.",
              f"순찰은 입식에 포함합니다. 입식·좌식 합계에는 자세를 지정하지 않은 {excluded}가 포함되지 않습니다.","",
              "## 직원별 포스트 배정 횟수","",
              "| 직원 | 표기상 포스트 총횟수 | G1 입식/좌식 | L3 | I1 입식/좌식/휴게성/철수 | G2 | 상층 | 중층 | 하층 | 보안실 | 휴게 |",
              "|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for p in people:
        rr=[r for r in rows if r.employee_id==p]; stats=calculate_employee_stats(record,p); c=Counter(stats.displayed_counts)
        def posture(label):return "/".join(str(stats.posture_by_post[label][po]) for po in ("standing","seated"))
        i1 = posture("I1") + "/" + str(sum(r.displayed_assignment.label=="I1" and r.actual_rest_time_value==1 for r in rr)) + "/" + str(sum(r.displayed_assignment.label=="I1" and r.barrier_remove_flag for r in rr))
        south_total=sum(c[k] for k in ("G2","G3","G2(1)"))
        displayed_post_total=stats.displayed_post_total
        vals=[displayed_post_total,posture("G1"),c["L3"],i1,south_total,c["upper"],c["middle"],c["lower"],c["보안실 대기"],c["휴게"]]
        assert sum(c.values())==14
        lines.append("| "+p+" | "+" | ".join(map(str,vals))+" |")
    lines += ["",f"표기상 포스트 총횟수는 G1·L3·I1·G2·G3·G2(1)의 표시 횟수 합계입니다. 휴게성 I1과 18시 {manager_label}의 L3도 표시 횟수에는 포함합니다.",
              f"G2는 G2·G3·G2(1) 합계입니다. L3·보안실·휴게는 표시 횟수이며, {manager_label}의 18시 L3는 실제 입식에 포함하지 않습니다.","",
              "## 최대 연속 실제업무 구간과 자세 순서","",
              "| 직원 | 최대연속 | 해당 구간(시작~종료) · 업무 순서 |","|---|---:|---|"]
    for p in people:
        rr=[r for r in rows if r.employee_id==p]; maximum,rruns=runs(rr)
        descriptions=[]
        for run in rruns:
            seq=[]
            for r in run:
                label=r.displayed_assignment.label
                if r.actual_post_or_work_type.kind=="patrol":value=names[label]+"순찰"
                elif r.actual_post_or_work_type.kind=="barrier_only" or r.barrier_remove_flag:value="차단봉 설치" if r.barrier_install_flag else "차단봉 철수"
                else:value=label+"("+("입식" if r.posture_or_mode=="standing" else "좌식")+")"
                seq.append(value)
            descriptions.append(f"{run[0].slot.hour:02d}:00~{(run[-1].slot.hour+1)%24:02d}:00 "+" → ".join(seq))
        lines.append("| "+p+" | "+str(maximum)+"시간 | "+"<br>".join(descriptions)+" |")
    lines += ["", "## 최대 연속 실휴게 구간", "",
              "| 직원 | 최대 연속 실휴게 | 해당 구간(시작~종료) · 표시 순서 |", "|---|---:|---|"]
    for p in people:
        rr=[r for r in rows if r.employee_id==p]
        maximum, rest_runs=runs(rr,rest=True)
        descriptions=[]
        for run in rest_runs:
            seq=" → ".join(r.displayed_assignment.label for r in run)
            descriptions.append(f"{run[0].slot.hour:02d}:00~{(run[-1].slot.hour+1)%24:02d}:00 {seq}")
        lines.append("| "+p+" | "+str(maximum)+"시간 | "+"<br>".join(descriptions)+" |")
    lines += ["", "실휴게는 실제 근무시간 0시간으로 계산된 휴게·보안실 대기만 포함하며, 차단봉 설치·철수 시간은 제외합니다."]
    return "\n".join(lines)+"\n"

def main():
    outcome=run_schedule(context(),options=SolveOptions(rules_version="2.6",seconds=15))
    result=outcome.solve_result
    print(result.status,result.attempts,flush=True)
    if result.record is None:raise RuntimeError("No schedule")
    errors=list(outcome.validation_errors)
    if errors:raise RuntimeError(errors)
    out=Path(__file__).parent/"results/2026-09-28-FM-5workers-v2.6"
    Path(str(out)+".json").write_text(json.dumps({"rulebook":"v2.6","result":asdict(result),"validation_errors":errors},ensure_ascii=False,default=str,indent=2),encoding="utf-8")
    Path(str(out)+".md").write_text(render(result.record),encoding="utf-8-sig")
    print("VALIDATION: 0 errors; saved",out)
if __name__=="__main__":main()

