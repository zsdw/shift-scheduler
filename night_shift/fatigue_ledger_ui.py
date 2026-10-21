"""PC·폰 공통 장부 표시. 후보/보기 변경은 저장된 실제 장부에 적립하지 않는다."""
from datetime import timedelta
from html import escape
import streamlit as st
from . import fatigue_ledger as ledger


def _table(rows, columns):
    """좁은 화면에서도 한 사람을 한 행으로 비교한다."""
    head = ''.join(f'<th scope="col">{escape(label)}</th>' for _, label in columns)
    body = ''.join('<tr>' + ''.join(
        f'<td>{escape(str(row[field]))}</td>' for field, _ in columns) + '</tr>'
        for row in rows)
    return ('<style>.fatigue-ledger{width:100%;max-width:760px;table-layout:fixed;'
            'border-collapse:collapse;font-size:clamp(11px,2.9vw,14px);font-variant-numeric:tabular-nums}'
            '.fatigue-ledger th,.fatigue-ledger td{text-align:center;padding:8px 2px;'
            'border-bottom:1px solid #94a3b833;overflow-wrap:anywhere}'
            '.fatigue-ledger th{background:#3182f610;font-weight:600}'
            '.fatigue-ledger td:first-child{font-weight:600}'
            '</style><table class="fatigue-ledger"><thead><tr>' + head +
            '</tr></thead><tbody>' + body + '</tbody></table>')


def render(store, day, kind='night', current=None, key='main'):
    title = '야간' if kind == 'night' else '주말 주간'
    st.markdown(f'**장기 피로도 손해 장부 · {title}**')
    try:
        before, entries = ledger.read(store, day, kind)
        actual, _ = ledger.read(store, day + timedelta(days=1), kind)
        values = (ledger.night_values(current) if kind == 'night' else ledger.weekend_values(current)) if current is not None else {}
        extras = ledger.night_extras(current) if kind == 'night' and current is not None else {}
        delta = ledger.day_delta(values, extras) if day >= ledger.START else {}
    except (OSError, ValueError) as exc:
        st.error(str(exc))
        return
    st.caption('2026-10-04부터 · 양수=동료보다 더 맡은 미상환 부담, 음수=상대적으로 덜 맡음. '
               '온전 출근 일반근무일만 집계하며 야간·주말 주간은 별도입니다. 월평균·최근 6회 평균과 다릅니다.')
    names = sorted(set(before) | set(actual) | set(delta), key=lambda n: -before.get(n, 0))
    if not names:
        st.caption('집계할 실제 기록이 없습니다. 첫 확정 근무부터 누적됩니다.')
        return
    fmt = lambda v: f'{float(v):+.2f}' if v else '0.00'
    rows = [{'근무자': n, '이전 잔액': fmt(before.get(n, 0)),
             '이 표 증감': fmt(delta.get(n, 0)) if n in delta else '제외',
             '적용 후 예상': fmt(before.get(n, 0) + delta.get(n, 0)),
             '실제 저장 잔액': fmt(actual.get(n, 0))} for n in names]
    import mobile_ui
    mobile = mobile_ui.is_mobile()
    if mobile:
        st.markdown(_table(rows, [('근무자', '근무자'), ('이전 잔액', '이전'),
                    ('이 표 증감', '증감'), ('적용 후 예상', '예상'),
                    ('실제 저장 잔액', '실제 저장')]), unsafe_allow_html=True)
    else:
        st.dataframe(rows, hide_index=True, width='stretch', key=f'ledger_{kind}_{day}_{key}_totals')
    st.caption('후보를 다시 생성해도 적립되지 않습니다. 실제 저장 잔액은 선택일까지 확정한 기록만 반영하며, '
               '과거 기록 수정·삭제·복구 시 다시 계산됩니다. 이 표 증감과 예상은 현재 배정의 미리보기입니다.')
    with st.expander(f'장부 날짜별 내역 · {title}', expanded=False):
        if mobile:
            detail = [{'날짜': e['day'].strftime('%m/%d'), '근무자': e['name'],
                       '당일 손해': fmt(e['delta']), '당시 잔액': fmt(e['balance'])}
                      for e in entries[-60:]]
            st.markdown(_table(detail, [('날짜', '날짜'), ('근무자', '근무자'),
                        ('당일 손해', '당일 증감'), ('당시 잔액', '당시 잔액')]), unsafe_allow_html=True)
            if len(entries) > 60:
                st.caption('화면에는 최근 60건만 표시하며 잔액은 전체 기간을 반영합니다.')
        else:
            st.dataframe([{'날짜': str(e['day']), '근무자': e['name'], '피로도': float(e['fatigue']),
                       '당일 손해': fmt(e['delta']), '당시 잔액': fmt(e['balance'])}
                      for e in entries], hide_index=True, width='stretch', key=f'ledger_{kind}_{day}_{key}_entries')
