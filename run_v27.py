"""N1/FM/five general workers + A, explicitly empty history, v2.7."""
from pathlib import Path
from dataclasses import asdict
import json
from run_v26 import context, render
from night_shift.models import HistoryInput
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


def posture_triples(record):
    """Audit actual posture, including the 18/07 display exceptions."""
    found = []
    for p in sorted({r.employee_id for r in record.assignments}):
        rows = sorted((r for r in record.assignments if r.employee_id == p), key=lambda r: r.slot.index)
        for start in range(len(rows) - 2):
            window = rows[start:start + 3]
            for posture in ('standing', 'seated'):
                if all(r.actual_work_time_value == 1 and r.posture_or_mode == posture for r in window):
                    found.append({'employee': p, 'start_hour': window[0].slot.hour, 'posture': posture})
    return found


def main():
    history = HistoryInput((), ())
    result = solve_first_trial(context(), history, seconds=30, rules_v27=True)
    print(result.status, result.attempts, flush=True)
    if result.record is None:
        raise RuntimeError('No schedule: ' + result.status)
    errors = validate_first_trial(result.record, history, rules_v27=True)
    if errors:
        raise RuntimeError(errors)
    triples = posture_triples(result.record)
    out = Path(__file__).parent / 'results/2026-09-28-FM-5workers-v2.7'
    Path(str(out) + '.json').write_text(json.dumps({'rulebook': 'v2.7', 'result': asdict(result), 'validation_errors': errors, 'same_posture_triples': triples}, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    report = render(result.record).replace('v2.6', 'v2.7')
    report += '\n## v2.7 동일 자세 3시간 연속 점검\n\n'
    report += f'입식 3연속 {sum(x["posture"] == "standing" for x in triples)}건 · 좌식 3연속 {sum(x["posture"] == "seated" for x in triples)}건. 혼합 자세 3시간은 이 회피 항목에 포함하지 않습니다.\n'
    for x in triples:
        report += f'\n- {x["employee"]}: {x["start_hour"]:02d}시 시작, {x["posture"]}\n'
    Path(str(out) + '.md').write_text(report, encoding='utf-8-sig')
    print('VALIDATION: 0 errors; posture triples:', triples)


if __name__ == '__main__':
    main()
