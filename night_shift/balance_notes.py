"""Plain-language reasons for balance differences, and a monthly direction.

The generator aims at an even spread among general workers. When someone
ends up clearly above or below the others, these notes say why, in the order
the causes actually apply:

1. 관리자 규칙 (통제 우대 / 결원 2명 예외 / 준호 대행 승계)
2. 가용시간 차이 (반차·이탈)
3. 실제 근무 수정 (드래그, 포스트 운영, 피로도 주석)
4. 과거 이력 보정 (직전 2싸이클 6:4 가중 평균)
5. 특수 업무 (차단봉, 2회 순찰)
6. 그 외: 해를 구하는 과정에서 생긴 자연스러운 차이
"""
from __future__ import annotations

from collections import defaultdict


GAP_FATIGUE = 2   # a full-time general worker this far from the others' mean is explained
GAP_WORK = 1


def _name(stats) -> str:
    return f"{stats.display_number} {stats.name}" if stats.display_number is not None else "통제"


def _preference_notes(rows, general, prepared, names, hour) -> list[str]:
    """17-1 근무자 선호가 이 표에서 어떻게 반영됐는지 (표에서 직접 확인)."""
    weights = getattr(prepared, "preference_weights", None) or {}
    avoid = getattr(prepared, "avoid_cells", ()) or ()
    out = []
    if weights:
        long_rest, last_rest = [], []
        for p in general:
            cells = rows.get(p.employee_id, {})
            rest = [cells.get(t) is not None and cells[t].actual_rest_time_value == 1 for t in range(14)]
            if any(rest[t] and rest[t + 1] for t in range(6, 11)):
                long_rest.append(p.name)
            if rest[13]:
                last_rest.append(p.name)
        favored = sorted(((w, names.get(pid, pid)) for pid, w in weights.items() if w > min(weights.values())),
                         reverse=True)
        text = ("근무자 선호(17-1): 00~05시 2시간 이상 연속 휴게 — " + (", ".join(long_rest) or "없음")
                + " · 07시 휴게 — " + (", ".join(last_rest) or "없음"))
        if favored:
            text += " · 최근 3싸이클 실제 피로도가 높았던 사람 우선: " + ", ".join(f"{n}" for _, n in favored)
        out.append(text + ". (밸런스를 다 맞춘 뒤 남는 선택지에서 반영)")
    for employee_id, slot, label in avoid:
        cell = rows.get(employee_id, {}).get(slot)
        got = cell is not None and cell.displayed_assignment.label == label
        who = names.get(employee_id, employee_id)
        out.append(f"{who} {hour(slot)} {label} 회피(개인 선호): "
                   + ("다른 규칙 때문에 피하지 못했습니다." if got else "반영했습니다."))
    return out


def balance_reasons(record, stats: dict, prepared=None, plan_stats: dict | None = None,
                    notes: dict | None = None, emergency: dict | None = None,
                    manual: bool = False) -> list[str]:
    """특이사항·비고 for one schedule. Routine rules (e.g. 통제 우대) are not repeated.

    ``emergency``: {"employee": id or None, "from": slot or None, "reason": str, "locked_through": slot}
    """
    context = record.context
    names = {e.employee_id: e.name for e in context.employees}
    rows = defaultdict(dict)
    for r in record.assignments:
        rows[r.employee_id][r.slot.index] = r
    out = []
    hour = lambda t: f"{(18 + t) % 24:02d}시"  # noqa: E731

    manager = next((p for p in stats.values() if p.is_manager), None)
    general = [p for p in stats.values() if not p.is_manager]
    full = [p for p in general if p.available_time == 14]

    emergency_id = (emergency or {}).get("employee")
    if emergency:
        who = "통제" if emergency_id == "A" else names.get(emergency_id)
        lock = emergency.get("locked_through")
        text = "긴급 재편성"
        if who:
            start = emergency.get("from")
            text += f": 긴급반차·이탈자 {who}" + (f" ({hour(start)}부터 근무불가)" if start is not None else "")
        if emergency.get("reason"):
            text += f" · {emergency['reason']}"
        if lock is not None and lock >= 0:
            text += f" · 18시~{hour(lock)} LOCK"
        out.append(text + ".")

    leave = [names.get(a.employee_id, a.employee_id) for a in context.attendance
             if not a.present and not (a.acts_as_manager and a.display_number is None)]
    if any(not a.present and a.acts_as_manager and a.display_number is None for a in context.attendance):
        out.append("통제 결근: 준호가 관리자 대행을 맡았습니다.")
    if leave:
        out.append("연차: " + ", ".join(leave) + ".")

    if manager is not None:
        absences = 7 - sum(a.present for a in context.attendance)
        if context.manager_handover:
            k, proxy = context.manager_handover
            out.append(f"통제가 {hour(k)}에 빠져 그 뒤로는 {names.get(proxy, '준호')}가 관리자 대행을 이어받았습니다(0-4-3).")
        elif context.partial_vacancy_profile or context.flexible_from_slot is not None or absences >= 2:
            out.append("결원 2명 회차라 관리자 우대(최소 실근무·피로도 격차)를 적용하지 않았습니다(8-7).")
        if context.flexible_from_slot is not None:
            out.append(f"{hour(context.flexible_from_slot)}부터 유도리·결원 2명 규칙으로 전환했습니다(0-4-2).")
    if getattr(context, "post_operations", None) is not None:     # 유도리 포스트별 운영 (사용자 지정)
        parts = [f"{post} {hour(lo)}~{hour(hi)} {'휴게성' if state == 'rest' else '좌식'}"
                 for post, lo, hi, state in context.post_operations]
        out.append("유도리 포스트별 운영(지정): " + (", ".join(parts) if parts else "휴게성·좌식 전환 없음")
                   + " — 이 기준으로 피로도·실근무를 계산해 밸런스를 맞췄습니다.")

    for p in general:
        if p.available_time < 14 and p.employee_id != emergency_id:
            out.append(f"{_name(p)}: 반차로 근무 가능 시간이 {p.available_time}시간이라 합계가 적습니다 "
                       f"(근무부담률 {p.workload_rate * 100:.0f}%).")
    out.extend(_preference_notes(rows, general, prepared, names, hour))

    if not full:
        return out or ["특이사항 없음."]
    mean_f = sum(p.fatigue_value for p in full) / len(full)
    mean_w = sum(p.actual_work_time_value for p in full) / len(full)
    low_f, high_f = min(p.fatigue_value for p in full), max(p.fatigue_value for p in full)
    low_w, high_w = min(p.actual_work_time_value for p in full), max(p.actual_work_time_value for p in full)
    flagged = [p for p in full if abs(p.fatigue_value - mean_f) >= GAP_FATIGUE / 2 + 0.5
               or abs(p.actual_work_time_value - mean_w) >= GAP_WORK]
    if high_f - low_f < GAP_FATIGUE and high_w - low_w <= GAP_WORK:
        flagged = []
    else:
        out.append(f"온전 출근 일반근무자 {len(full)}명 사이 차이: 피로도 {low_f:g}~{high_f:g} (평균 {mean_f:.1f}), "
                   f"실근무 {low_w:g}~{high_w:g}시간 (평균 {mean_w:.1f}).")

    history = {}
    if prepared is not None and prepared.historical_totals and prepared.historical_nights:
        totals = prepared.historical_totals.get("fatigue_value", {})
        for p, total in totals.items():
            nights = prepared.historical_nights.get(p, 0)
            if nights:
                history[p] = total / nights
    hist_mean = (sum(history.values()) / len(history)) if history else None

    for p in flagged:
        side = "많" if p.fatigue_value > mean_f or p.actual_work_time_value > mean_w else "적"
        what = f"피로도 {p.fatigue_value:g}, 실근무 {p.actual_work_time_value:g}시간으로 평균보다 {side}습니다"
        reasons = []
        if plan_stats and p.employee_id in plan_stats:
            before = plan_stats[p.employee_id]
            df = p.fatigue_value - before.fatigue_value
            dw = p.actual_work_time_value - before.actual_work_time_value
            if df or dw:
                reasons.append(f"실제 근무 수정으로 계획 대비 피로도 {df:+g}, 실근무 {dw:+g}시간이 바뀌었습니다")
        for (person, slot), item in (notes or {}).items():
            if person == p.employee_id:
                memo = f" ({item['note']})" if item.get("note") else ""
                reasons.append(f"{(18 + slot) % 24:02d}시 피로도를 {item['value']}로 기록했습니다{memo}")
        if hist_mean is not None and p.employee_id in history:
            past = history[p.employee_id] - hist_mean
            if side == "적" and past >= 0.5:
                reasons.append(f"최근 2싸이클 실제 기록에서 밤당 피로도가 평균보다 {past:+.1f} 높았" +
                               ("고, 이번에는 결과적으로 덜 맡았습니다" if manual else "어서 이번에는 덜 부담되게 보정했습니다"))
            elif side == "많" and past <= -0.5:
                reasons.append(f"최근 2싸이클 실제 기록에서 밤당 피로도가 평균보다 {past:+.1f} 낮았" +
                               ("고, 이번에는 결과적으로 더 맡았습니다" if manual else "어서 이번에 조금 더 맡았습니다"))
        if prepared is not None:
            if side == "적" and p.employee_id in prepared.forbid_install_ids:
                reasons.append("직전 근무에서 차단봉을 설치해 이번 설치에서 빠졌습니다")
        person_rows = rows[p.employee_id].values()
        if side == "많":
            if any(r.barrier_install_flag or r.barrier_remove_flag for r in person_rows):
                reasons.append("차단봉 설치·철수를 맡았습니다")
            if p.patrol_count >= 2:
                reasons.append("순찰을 2회 맡았습니다")
        if not reasons:
            reasons.append("수기 편성에서 생긴 차이입니다 (프로그램이 짠 표가 아님)" if manual else
                           "특별한 사정 없이 해를 구하는 과정에서 자연스럽게 생긴 차이입니다 "
                           "(시간·포스트 수가 정수라 모두 똑같이 나눌 수 없음)")
        out.append(f"{_name(p)}: {what}. " + "; ".join(reasons) + ".")
    return out or ["특이사항 없음."]


def monthly_direction(rows: list[dict]) -> list[str]:
    """rows: [{'id','직원','온전 출근일','평균 피로도','is_manager'}] -> guidance sentences."""
    general = [r for r in rows if not r.get("is_manager") and r.get("평균 피로도") is not None]
    if len(general) < 2:
        return ["월간 기록이 아직 적어 방향을 말하기 어렵습니다. 근무표를 몇 번 더 저장하면 여기에 정리됩니다."]
    mean = sum(r["평균 피로도"] for r in general) / len(general)
    high = sorted((r for r in general if r["평균 피로도"] - mean >= 0.5), key=lambda r: -r["평균 피로도"])
    low = sorted((r for r in general if mean - r["평균 피로도"] >= 0.5), key=lambda r: r["평균 피로도"])
    out = [f"이번 달 일반근무자 평균 피로도는 밤당 {mean:.1f}입니다."]
    if high:
        out.append("평균보다 높은 사람: " + ", ".join(f"{r['직원']}({r['평균 피로도']:.1f})" for r in high)
                   + " → 앞으로는 이 사람들의 피로도를 조금 낮게 편성하는 쪽으로 갑니다.")
    if low:
        out.append("평균보다 낮은 사람: " + ", ".join(f"{r['직원']}({r['평균 피로도']:.1f})" for r in low)
                   + " → 앞으로 부담을 조금 더 나누어 맡기는 쪽으로 갑니다.")
    if not high and not low:
        out.append("모두 평균과 0.5 이내라 지금처럼 균형 편성을 유지합니다.")
    out.append("참고: 생성기는 월 전체가 아니라 직전 2싸이클(최근 4근무) 실제 기록을 6:4로 반영합니다. "
               "그래서 월간 차이는 다음 몇 번의 근무에서 조금씩 줄어드는 방식으로 맞춰집니다.")
    return out
