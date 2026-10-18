"""Plain-language reasons for balance differences, and a monthly direction.

The generator aims at an even spread among general workers. When someone
ends up clearly above or below the others, these notes say why, in the order
the causes actually apply:

1. 관리자 규칙 (통제 우대 / 결원 2명 예외 / 준호 대행 승계)
2. 가용시간 차이 (반차·이탈)
3. 실제 근무 수정 (드래그, 포스트 운영, 피로도 주석)
4. 과거 이력 보정 (직전 2싸이클 최근 4근무 평균, 5:5)
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
                   + ("하드룰 또는 상위 우선순위 때문에 피하지 못했습니다." if got else "반영했습니다."))
    return out


COVERAGE_POSTS = ("G1", "L3", "I1")


def _stage(attempts, name):
    """Solver 단계 기록에서 마지막 해당 단계의 상태 (OPTIMAL/FEASIBLE/...)."""
    found = [a for a in (attempts or ()) if a.get("stage") == name]
    return found[-1].get("status") if found else None


def balance_verdict(record, stats: dict, attempts=None, manual: bool = False, edited: bool = False) -> list[str]:
    """밸런스 판정 (2026-10-04 사용자 요청: 생성 때마다 완벽한 n빵이 아니면 이유를 꼭 알린다).

    완성된 표만 보고 계산한다 (Solver 제약을 다시 쓰지 않음). 순서: 판정 → 정수 나눗셈 한계 →
    상위 규칙 → 계산 시간. 17-2 포스트 고루 배정(G1·L3·I1 최소 1번, 횟수 차이)도 함께 알린다."""
    context = record.context
    general = [p for p in stats.values() if not p.is_manager]
    full = [p for p in general if p.available_time == 14]
    out = []
    if len(full) < 2:
        return out
    n = len(full)
    lines, uneven = [], []
    for label, attr, unit in (("피로도", "fatigue_value", "점"), ("실휴게", "actual_rest_time_value", "시간")):
        values = [getattr(p, attr) for p in full]
        lo, hi, total = min(values), max(values), sum(values)
        gap = hi - lo
        lines.append(f"{label} {lo:g}~{hi:g}{unit}(차이 {gap:g})")
        if gap:
            integral = all(float(v).is_integer() for v in values)
            remainder = total % n if integral else None
            floor_gap = 0 if remainder == 0 else 1
            uneven.append((label, gap, total, remainder, floor_gap, unit))
    head = f"밸런스 판정 — 온전 출근 일반근무자 {n}명: " + ", ".join(lines)
    if not uneven:
        out.append(head + " → 완전 n빵입니다.")
    else:
        out.append(head + ".")
        status = _stage(attempts, "general_balance")
        for label, gap, total, remainder, floor_gap, unit in uneven:
            if remainder and gap <= floor_gap:
                out.append(f"· {label}: 합계 {total:g}{unit}을 {n}명이 나누면 {remainder:g}{unit}이 남아 "
                           f"똑같이 나눌 수 없습니다. 차이 {gap:g}{unit}이 가능한 최소입니다.")
                continue
            if manual:
                out.append(f"· {label}: 업로드한 실제 기록(수기 편성)이라 프로그램이 나눈 결과가 아닙니다.")
                continue
            if edited:
                out.append(f"· {label}: 끌어서 수정한 표라 생성 직후와 다릅니다.")
            if status == "OPTIMAL":
                out.append(f"· {label}: 아래 상위 규칙을 지키면서 계산해 보니 피로도·실휴게 차이 합을 이보다 줄일 수 "
                           f"없었습니다(계산상 최소 확인).")
            elif status:
                out.append(f"· {label}: 계산 제한시간 안에 더 줄일 수 있는지 끝까지 확인하지 못했습니다({status}). "
                           f"'생성 상세 설정'에서 제한시간을 늘려 다시 만들면 줄어들 수 있습니다.")
            else:
                out.append(f"· {label}: 저장된 표라 계산 기록이 없습니다. 아래 상위 규칙이 영향을 줬을 수 있습니다.")
        if not manual and any(not (rem and gap <= fl) for _, gap, _, rem, fl, _ in uneven):
            out.append("· 밸런스보다 먼저 지키는 규칙(이 표에 해당하는 것): " + _upper_rules(record, stats) + ".")
    out.extend(_coverage_lines(record, stats, full, attempts, manual))
    return out


ZONE_NAMES = {"upper": "상층", "middle": "중층", "lower": "하층"}


def history_influence_lines(record, stats, prepared=None, manual: bool = False) -> list[str]:
    """과거 싸이클 기록 때문에 오늘 표에서 누군가에게 영향이 간 경우 반드시 주석 (2026-10-05 사용자 요청).
    Solver가 실제로 쓴 이력 입력(prepared)과 완성된 표를 대조해, 오늘 해당되는 사람만 적는다."""
    if prepared is None or manual:
        return []
    names = {p.employee_id: _name(p) for p in stats.values()}
    present = {a.employee_id for a in record.context.attendance if a.present}
    rows = defaultdict(dict)
    for r in record.assignments:
        rows[r.employee_id][r.slot.index] = r
    general = {p.employee_id for p in stats.values() if not p.is_manager}
    out = []
    averages = getattr(prepared, "history_fatigue_averages", None) or {}
    eligible = {p.employee_id: averages[p.employee_id] for p in stats.values()
                if not p.is_manager and p.available_time == 14 and p.employee_id in averages}
    if len(eligible) >= 2:
        high = max(eligible, key=lambda p: (eligible[p], p))
        low = min(eligible, key=lambda p: (eligible[p], p))
        gap = eligible[high] - eligible[low]
        if gap >= 1 - 1e-9:
            today_gap = stats[low].fatigue_value - stats[high].fatigue_value
            spread = max(p.fatigue_value for p in stats.values() if not p.is_manager and p.available_time == 14) - min(p.fatigue_value for p in stats.values() if not p.is_manager and p.available_time == 14)
            applied = today_gap == 1 and spread <= 1
            out.append(f"최근 2싸이클 평균 차이 {gap:.2f}점 — {names[high]} 손해 보상: "
                       + (f"오늘 {stats[high].fatigue_value:g}점, {names[low]} {stats[low].fatigue_value:g}점으로 1점 낮게 편성했습니다."
                          if applied else "1점 보상 목표를 적용했으나 상위 규칙·계산 결과상 충족하지 못했습니다.")
                       + " 다음 편성도 평균 차이가 1점 이상이면 다시 보상하고, 미만이면 전원 균형을 우선합니다.")
    for pid in getattr(prepared, "forbid_install_ids", ()) or ():
        if pid in present:
            out.append(f"{names.get(pid, pid)}: 직전 근무에서 차단봉을 (대기로) 설치해 오늘 대기 설치에서 뺐습니다(15-3).")
    # 직전 07시 휴게자 연속 금지(16장)는 last_rest_lines가 '마지막 휴게' 줄에서 함께 설명한다
    absences = 7 - len(present)
    for pid in getattr(prepared, "forbid_patrol_exclusion_ids", ()) or ():
        if pid in general and absences == 0:
            out.append(f"{names.get(pid, pid)}: 순찰 제외 후 야간·공휴일 주간 출근 2회 보호 대상이라 오늘 순찰을 맡겼습니다(14-1-2).")
    for pid in getattr(prepared, "previous_install_ids", ()) or ():
        if pid in present and not any(r.barrier_remove_flag for r in rows.get(pid, {}).values()):
            out.append(f"{names.get(pid, pid)}: 직전 근무 차단봉 설치자라 오늘 철수는 피했습니다(15-4).")
    for pid in getattr(prepared, "previous_remove_ids", ()) or ():
        if pid in present and not any(r.barrier_install_flag for r in rows.get(pid, {}).values()):
            out.append(f"{names.get(pid, pid)}: 직전 근무 차단봉 철수자라 오늘 설치는 피했습니다(15-5).")
    for pid in getattr(prepared, "patrol_rotation_priority_ids", ()) or ():
        zones = [ZONE_NAMES.get(r.actual_post_or_work_type.label, r.actual_post_or_work_type.label)
                 for r in rows.get(pid, {}).values() if r.actual_post_or_work_type.kind.value == "patrol"]
        if pid in general and zones:
            out.append(f"{names.get(pid, pid)}: 순찰 구역 돌아가며 맡기(18-9) 차례라 오늘 {'·'.join(zones)} 순찰입니다.")
    rates = getattr(prepared, "duty_rates", None) or {}
    for metric, label in (("barrier", "차단봉"), ("upper", "상층 순찰"), ("middle", "중층 순찰"), ("lower", "하층 순찰")):
        table = rates.get(metric) or {}
        if not table:
            continue
        team = sum(table.values()) / len(table) / 100
        if metric == "barrier":
            today = [pid for pid in general if any(r.barrier_install_flag or r.barrier_remove_flag
                                                   for r in rows.get(pid, {}).values())]
        else:
            today = [pid for pid in general if any(r.actual_post_or_work_type.label == metric
                                                   and r.actual_post_or_work_type.kind.value == "patrol"
                                                   for r in rows.get(pid, {}).values())]
        below = [pid for pid in today if table.get(pid, 0) / 100 < team]
        if below:
            out.append(f"{label}: 최근 3싸이클 밤당 횟수가 팀 평균({team:.2f})보다 적은 "
                       + ", ".join(f"{names.get(pid, pid)}({table.get(pid, 0) / 100:.2f})" for pid in below)
                       + "에게 오늘 맡겼습니다(15-8).")
    totals = (getattr(prepared, "historical_totals", None) or {}).get("fatigue_value", {})
    nights = getattr(prepared, "historical_nights", None) or {}
    past = {p: totals[p] / nights[p] for p in totals if nights.get(p) and p in general}
    full = [p for p in stats.values() if not p.is_manager and p.available_time == 14 and p.employee_id in past]
    if len(full) >= 2:
        past_mean = sum(past[p.employee_id] for p in full) / len(full)
        today_mean = sum(p.fatigue_value for p in full) / len(full)
        for p in full:
            gap = past[p.employee_id] - past_mean
            if gap >= 0.5 and p.fatigue_value < today_mean:
                out.append(f"{_name(p)}: 최근 2싸이클 밤당 피로도가 평균보다 {gap:+.1f} 높아 오늘 피로도 "
                           f"{p.fatigue_value:g}(오늘 평균 {today_mean:.1f})로 덜 맡겼습니다.")
            elif gap <= -0.5 and p.fatigue_value > today_mean:
                out.append(f"{_name(p)}: 최근 2싸이클 밤당 피로도가 평균보다 {gap:+.1f} 낮아 오늘 피로도 "
                           f"{p.fatigue_value:g}(오늘 평균 {today_mean:.1f})로 조금 더 맡겼습니다.")
    # 17-1 선호 가중(최근 3싸이클 피로도 높은 사람 우선)은 _preference_notes가 이미 따로 적는다
    return (["과거 싸이클 영향 —"] + ["· " + line for line in out]) if out else []


def lightest_lines(record, stats, prepared=None, manual: bool = False, edited: bool = False) -> list[str]:
    """이전 호출 호환: 최고·최저만으로 사람별 비고를 표시하지 않는다."""
    return []


def heaviest_lines(record, stats, prepared=None, manual: bool = False, edited: bool = False) -> list[str]:
    """이전 호출 호환: 과거 이력 영향은 history_influence_lines에서 설명한다."""
    return []


def last_rest_lines(record, stats, prepared=None, manual: bool = False) -> list[str]:
    """마지막 휴게(07시 실제 휴게, 16장)를 받은 일반근무자와 그 이유 (2026-10-05 사용자 요청)."""
    general = {p.employee_id: p for p in stats.values() if not p.is_manager}
    resting = [general[r.employee_id] for r in record.assignments
               if r.slot.index == 13 and r.employee_id in general and r.actual_rest_time_value == 1]
    weights = getattr(prepared, "preference_weights", None) or {}
    blocked = [general[pid] for pid in (getattr(prepared, "forbid_last_rest_ids", ()) or ()) if pid in general]
    if not resting:
        return ["마지막 휴게(07시): 받은 사람 없음 — 07시 포스트를 채우고 남는 일반근무자가 없었습니다."
                if not manual else "마지막 휴게(07시): 받은 사람 없음."]
    lines = []
    for p in sorted(resting, key=lambda p: (p.display_number or 0)):
        if manual:
            why = "업로드한 실제 기록(수기 편성)"
        elif prepared is not None and getattr(prepared,'last_rest_records',()):
            received=[r.context.shift_start_date for r in prepared.last_rest_records if any(
                x.employee_id==p.employee_id and x.slot.index==13 and x.actual_rest_time_value==1 for x in r.assignments)]
            previous=max(received).strftime('%m/%d') if received else '저장 이력에 없음'
            why = f"이번 이전 마지막 수혜 {previous}"
        else:
            why = "07시 포스트를 채우고 남는 인원 중 하드룰·밸런스를 지키는 배정"
        lines.append(f"{_name(p)}({why})")
    text = "마지막 휴게(07시): " + ", ".join(lines)
    if blocked and not manual:
        text += " · 직전 근무 07시 휴게자(" + ", ".join(_name(p) for p in blocked) + ")는 새 편성에서 연속 수혜 금지(16장)"
    return [text + "."]


def _upper_rules(record, stats) -> str:
    context = record.context
    items = ["하드룰(필수 포스트·연속근무·순찰 후 휴게·차단봉·근무불가)"]
    manager = next((p for p in stats.values() if p.is_manager), None)
    absences = 7 - sum(a.present for a in context.attendance)
    if manager is not None and not (context.partial_vacancy_profile or context.flexible_from_slot is not None
                                     or absences >= 2):
        items.append("관리자 실근무 최소 우대(8-4)와 관리자 피로도·실근무 격차(8-4-2·H-15)")
    if context.night_type.value in ("N1", "N2"):
        items.append("저녁 남문 1인 1회 제한(5-1-1)")
    rows = defaultdict(list)
    for r in record.assignments:
        rows[r.employee_id].append(r)
    double = [_name(p) for p in stats.values() if not p.is_manager and p.patrol_count >= 2]
    if double:
        items.append("순찰 2회 담당 " + ", ".join(double))
    barrier = [_name(stats[pid]) for pid, rs in rows.items() if pid in stats and not stats[pid].is_manager
               and any(r.barrier_install_flag or r.barrier_remove_flag for r in rs)]
    if barrier:
        items.append("차단봉 설치·철수 담당 " + ", ".join(barrier))
    if context.flexible_from_slot is not None:
        items.append("긴급 재편성 유도리 전환(0-4-2)")
    return " · ".join(items)


def _coverage_lines(record, stats, full, attempts, manual) -> list[str]:
    """17-2: 반차·이탈 없는 날 G1·L3·I1 최소 1번과 포스트별 횟수 차이."""
    if any(not p.is_manager and p.available_time < 14 for p in stats.values()):
        return []
    counts = {p.employee_id: {post: 0 for post in COVERAGE_POSTS} for p in full}
    for r in record.assignments:
        if r.employee_id in counts and r.displayed_assignment.label in COVERAGE_POSTS:
            counts[r.employee_id][r.displayed_assignment.label] += 1
    spread = ", ".join(f"{post} {min(c[post] for c in counts.values())}~{max(c[post] for c in counts.values())}회"
                       for post in COVERAGE_POSTS)
    missing = [f"{_name(stats[pid])} {post}" for pid, c in counts.items() for post in COVERAGE_POSTS if c[post] == 0]
    if not missing:
        return [f"포스트 고루 배정(17-2): 모두 G1·L3·I1을 1번 이상 섰습니다 · 사람별 횟수 {spread}."]
    why = ("업로드한 실제 기록(수기 편성)입니다" if manual else
           "다른 하드룰 때문에 모두 채울 수 없었습니다(계산상 확인)" if _stage(attempts, "post_coverage") == "OPTIMAL" else
           "계산 제한시간 안에 다 채우지 못했을 수 있습니다. 제한시간을 늘려 다시 만들어 보세요")
    return [f"포스트 고루 배정(17-2): 한 번도 안 선 포스트 — {', '.join(missing)}. {why}. 사람별 횟수 {spread}."]


def balance_reasons(record, stats: dict, prepared=None, plan_stats: dict | None = None,
                    notes: dict | None = None, emergency: dict | None = None,
                    manual: bool = False, attempts=None, others: dict | None = None) -> list[str]:
    """특이사항·비고 for one schedule. Routine rules (e.g. 통제 우대) are not repeated.

    ``emergency``: {"employee": id or None, "from": slot or None, "reason": str, "locked_through": slot}
    """
    context = record.context
    names = {e.employee_id: e.name for e in context.employees}
    rows = defaultdict(dict)
    for r in record.assignments:
        rows[r.employee_id][r.slot.index] = r
    # 밸런스 판정은 긴급 재편성 안내 바로 다음에 항상 (완벽한 n빵이 아니면 이유까지)
    verdict = balance_verdict(record, stats, attempts, manual=manual,
                              edited=bool(plan_stats) and any(plan_stats[p].fatigue_value != stats[p].fatigue_value
                                                              for p in stats if p in plan_stats))
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
    out.extend(verdict)
    edited = bool(plan_stats) and any(plan_stats[p].fatigue_value != stats[p].fatigue_value
                                      for p in stats if p in plan_stats)
    out.extend(last_rest_lines(record, stats, prepared, manual=manual))
    out.extend(history_influence_lines(record, stats, prepared, manual=manual))

    others = others or {}                       # '기타'로 빠진 사람 {employee_id: 비고} (연차와 구분)
    leave = [names.get(a.employee_id, a.employee_id) for a in context.attendance
             if not a.present and not (a.acts_as_manager and a.display_number is None) and a.employee_id not in others]
    other = [names.get(a.employee_id, a.employee_id) + (f"({others[a.employee_id]})" if others[a.employee_id] else "")
             for a in context.attendance if not a.present and a.employee_id in others]
    if other:
        out.append("기타(근무 제외): " + ", ".join(other) + ".")
    if any(not a.present and a.acts_as_manager and a.display_number is None for a in context.attendance):
        out.append("통제 결근: 준호가 관리자 대행을 맡았습니다.")
    if leave:
        out.append("연차: " + ", ".join(leave) + ".")

    if manager is not None:
        absences = 7 - sum(a.present for a in context.attendance)
        if context.manager_handover:
            k, proxy = context.manager_handover
            if context.manager_handover_reverse:
                out.append(f"통제 전반부 반차: {hour(k)} 출근 전까지 {names.get(proxy, '준호')}가 관리자 대행, 이후 통제가 관리자 근무를 이어받았습니다.")
            else:
                out.append(f"통제가 {hour(k)}에 빠져 그 뒤로는 {names.get(proxy, '준호')}가 관리자 대행을 이어받았습니다(0-4-3).")
        elif context.partial_vacancy_profile or context.flexible_from_slot is not None or absences >= 2:
            out.append("결원 2명 회차라 관리자 최소 실근무 우대는 적용하지 않고, 일반근무자 밸런스 다음으로 조장과 평균 피로도 차이 4점 이내를 권장합니다(8-7·17-5).")
            if general:
                average = sum(p.fatigue_value for p in general) / len(general)
                gap = abs(manager.fatigue_value - average)
                text = f"조장 피로도 {manager.fatigue_value:g}점 · 일반근무자 평균 {average:.1f}점 · 차이 {gap:.1f}점"
                if gap <= 4:
                    out.append(text + " — 4점 이내 목표 충족.")
                else:
                    stage = _stage(attempts, "vacancy_manager_fatigue_gap")
                    reason = ("4점 이내 권장 목표 초과" if not stage else
                              "필수 규칙과 앞 순위 목표를 지킨 범위에서 4점 이내로 줄일 수 없음"
                              if stage == "OPTIMAL" else "계산 시간 안에 4점 이내 배정을 찾지 못함")
                    out.append(text + " — " + reason + ".")
        if context.flexible_from_slot is not None:
            out.append(f"{hour(context.flexible_from_slot)}부터 유도리·결원 2명 규칙으로 전환했습니다(0-4-2).")
    from .models import default_rest_start
    if (getattr(context, "post_operations", None) is not None       # 유도리 포스트별 운영 (사용자 지정만,
            and default_rest_start(context.post_operations) is None):  # 기본값 명시 저장은 제외 — 2026-10-13)
        parts = [f"{post} {hour(lo)}~{hour(hi)} {'휴게성' if state == 'rest' else '좌식'}"
                 for post, lo, hi, state in context.post_operations]
        out.append("유도리 포스트별 운영(지정): " + (", ".join(parts) if parts else "휴게성·좌식 전환 없음")
                   + " — 이 기준으로 피로도·실근무를 계산해 밸런스를 맞췄습니다.")

    if manager is not None and manager.employee_id == "A" and not manual:
        widened = [p for p in full if p.fatigue_value - manager.fatigue_value == 3]
        if widened and not (context.partial_vacancy_profile or context.flexible_from_slot is not None
                            or 7 - sum(a.present for a in context.attendance) >= 2):
            out.append("통제A 피로도 격차 3점 예외: " + ", ".join(p.name for p in widened)
                       + " — 다른 권장 목표를 먼저 적용하고, 통제A와의 0~2점 차이는 마지막 순위로 맞춥니다.")
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
    # 사람별 부담 설명은 최고·최저 순위가 아니라 과거 이력의 당일 영향으로만 표시한다.
    flagged = []
    if not (high_f - low_f < GAP_FATIGUE and high_w - low_w <= GAP_WORK):
        out.append(f"실근무 {low_w:g}~{high_w:g}시간 (평균 {mean_w:.1f}) · 피로도 평균 {mean_f:.1f}.")

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
    cutoff = next((r.get("집계 기준일") for r in rows if r.get("집계 기준일")), None)
    period = f"{cutoff}까지 저장된 해당 월 실제 근무 기준" if cutoff else "이번 달"
    out = [f"{period}: 일반근무자 평균 피로도는 밤당 {mean:.1f}입니다."]
    if high:
        out.append("평균보다 높은 사람: " + ", ".join(f"{r['직원']}({r['평균 피로도']:.1f})" for r in high)
                   + " → 앞으로는 이 사람들의 피로도를 조금 낮게 편성하는 쪽으로 갑니다.")
    if low:
        out.append("평균보다 낮은 사람: " + ", ".join(f"{r['직원']}({r['평균 피로도']:.1f})" for r in low)
                   + " → 앞으로 부담을 조금 더 나누어 맡기는 쪽으로 갑니다.")
    if not high and not low:
        out.append("모두 평균과 0.5 이내라 지금처럼 균형 편성을 유지합니다.")
    # 2026-10-05: 근무표 생성 후 현장에서 생긴 변동은 특이사항이 아니라 여기서 날짜·사람·시간·사유로 설명
    for r in general:
        items = [c for c in r.get("현장 변동") or () if c.get("피로도 변화") not in ("+0", "0")]
        if items:
            total = sum(float(c["피로도 변화"]) for c in items)
            out.append(f"{r['직원']}의 월간 피로도에는 현장 변동 {total:+g}점이 들어 있습니다: "
                       + "; ".join(f"{c['날짜']} {c['내용']}(피로도 {c['피로도 변화']})" for c in items)
                       + " — 주석 참조.")
    out.append("참고: 생성기는 월 전체가 아니라 직전 2싸이클(최근 4근무) 실제 기록을 똑같은 비중(5:5)으로 반영합니다. "
               "그래서 월간 차이는 다음 몇 번의 근무에서 조금씩 줄어드는 방식으로 맞춰집니다.")
    return out
