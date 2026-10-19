"""2026-10-04부터 실제 기록으로 재구성하는 상대적 피로도 장부. 파일 쓰기 없음."""
from datetime import date
from fractions import Fraction
from math import lcm
from pathlib import Path

START = date(2026, 10, 4)
SCALE = 60  # 일반근무자 2~6명 평균의 분모를 보존


def day_delta(values):
    """{고정 이름: 실제 피로도}. 관리자/부분출근은 호출자가 제외한다."""
    if len(values) < 2:
        return {}
    exact = {p: Fraction(str(v)) for p, v in values.items()}
    average = sum(exact.values()) / len(exact)
    return {p: v - average for p, v in exact.items()}


def night_values(record):
    from .service import calculate_all_stats
    stats = calculate_all_stats(record)
    names = {p.employee_id: p.name for p in record.context.employees}
    # 교대일의 대행자도 하루 전체 일반 역할이 아니므로 제외한다.
    handover = record.context.manager_handover
    proxy = handover[1] if handover else None
    return {names[a.employee_id]: stats[a.employee_id].fatigue_value
            for a in record.context.attendance
            if a.present and a.is_general_worker and not a.acts_as_manager
            and a.employee_id != proxy and a.employee_id in stats
            and stats[a.employee_id].available_time == 14}


def weekend_values(schedule):
    from .weekend_day import stats, partial_people
    partial = partial_people(schedule)
    return {schedule.names[p]: r['피로도']
            for p, r in zip(schedule.grid, stats(schedule, 'FM' if schedule.mode == 'FM' else '유도리'))
            if p != 'A' and p not in partial
            and p != (schedule.proxy if schedule.a_half else None)
            and schedule.names[p] not in schedule.rule_exempt_names}


def from_days(days, before):
    """날짜 순서·중복 날짜를 검증해 잔액과 일자별 원장을 만든다."""
    before = date.fromisoformat(str(before)[:10])
    balances, entries, seen = {}, [], set()
    for day, values in sorted(days, key=lambda item: item[0]):
        day = date.fromisoformat(str(day)[:10])
        if not START <= day < before:
            continue
        if day in seen:
            raise ValueError(f'{day}: 장부 원본 날짜 중복')
        seen.add(day)
        delta = day_delta(values)
        for name, change in delta.items():
            balances[name] = balances.get(name, Fraction()) + change
            entries.append({'day': day, 'name': name, 'fatigue': values[name],
                            'delta': change, 'balance': balances[name]})
    return balances, entries


def night_from_records(records, before):
    return from_days([(r.context.shift_start_date, night_values(r)) for r in records], before)


def read(store, before, kind='night'):
    """종류별 저장소만 읽고 선택일과 그 이후는 제외. 손상 파일은 조용히 무시하지 않는다."""
    from . import history_store
    from .weekend_day import load
    before = date.fromisoformat(str(before)[:10])
    days = []
    for path in sorted(Path(store).glob('????-??-??.json')):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if not START <= day < before:
            continue
        try:
            if kind == 'night':
                values = night_values(history_store.actual_record(Path(store), day))
            elif kind == 'weekend':
                values = weekend_values(load(store, str(day)))
            else:
                raise ValueError(f'장부 종류 오류: {kind}')
        except Exception as exc:
            raise ValueError(f'{path.name}: 피로도 장부를 계산하지 못했습니다: {exc}') from exc
        days.append((day, values))
    return from_days(days, before)


def units(value):
    value = Fraction(str(value)) if not isinstance(value, Fraction) else value
    return round(value * SCALE)


def objectives(model, fatigue, balances, prefix='ledger'):
    """당일 균형 다음에 최장 미상환 부담, 이후 잔액 편차를 줄인다. HARD는 추가하지 않음."""
    n = len(fatigue)
    if n < 2:
        return []
    exact = {p: Fraction(str(balances.get(p, 0))) for p in fatigue}
    scale = lcm(SCALE, *(v.denominator for v in exact.values()))
    prior = {p: int(exact[p] * scale) for p in fatigue}
    total = sum(fatigue.values())
    bound = max(abs(v) for v in prior.values()) * n + scale * n * 100
    projected, squares = [], []
    for i, (p, value) in enumerate(fatigue.items()):
        future = model.new_int_var(-bound, bound, f'{prefix}_future_{i}')
        model.add(future == n * prior[p] + scale * (n * value - total))
        projected.append(future)
        square = model.new_int_var(0, bound * bound, f'{prefix}_square_{i}')
        model.add_multiplication_equality(square, [future, future])
        squares.append(square)
    worst = model.new_int_var(0, bound, f'{prefix}_worst')
    model.add_max_equality(worst, [0, *projected])
    return [('long_term_fatigue_worst', worst), ('long_term_fatigue_spread', sum(squares))]


def optimize(model, goals, solve, seconds):
    """일별 균형→장부→기존 선호 순서. 시간 부족 때 마지막 유효 해를 보존한다."""
    from ortools.sat.python import cp_model
    if not goals:
        return solve(model, seconds)
    working = model.Clone()
    last = None
    proven = True
    budget = max(.1, seconds / (len(goals) + 1))
    for goal in goals:
        working.Minimize(goal)
        solver, status = solve(working, budget)
        if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            return (last[0], cp_model.FEASIBLE) if last else (solver, status)
        last = solver, status
        proven = proven and status == cp_model.OPTIMAL
        working.Add(goal == int(solver.Value(goal)))
    # 앞 목표의 도달값을 보존하고 원래 선호 목적식을 복원한다.
    final = model.Clone()
    for goal in goals:
        final.Add(goal == int(last[0].Value(goal)))
    solver, status = solve(final, budget)
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return solver, status if proven else cp_model.FEASIBLE
    return last[0], cp_model.FEASIBLE
