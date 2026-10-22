"""조별 조회 자료와 표시. 생성·수정·규칙 검사는 호출하지 않는다."""
from datetime import date
from pathlib import Path
from html import escape
import json
from team_schedule_analysis import POSTS,RESTS,tokens,hours,people,metrics,totals,normalize_source

def sources(store,team):
    """참조자료만 사용하므로 A조 저장본·규칙·후보와 섞이지 않는다."""
    from night_shift.order_source import UPLOAD_REFERENCE,apply_name_fixes
    path=Path(store)/'order_source'/UPLOAD_REFERENCE
    data=json.loads(path.read_text(encoding='utf-8')).get('sources',{}) if path.exists() else {}
    return {(iso,shift):normalize_source(s) for iso,shifts in data.items()
            for shift,s in apply_name_fixes(shifts,store,date.fromisoformat(iso)).items()
            if str(s.get('team','')).replace('조','')==team}


def table_html(source,mode='FM'):
    columns=[p for p in (*POSTS,'CP','셔틀','순회','순찰',*RESTS)
             if any(str(row.get(p,'')).strip() for row in source['cells'].values())]
    heads='<th>시간</th>'+''.join('<th>'+escape(p)+'</th>' for p in columns)
    body=''
    for h in hours(source):
        cells=source['cells'].get(str(h),{})
        body+='<tr><th>'+f'{h:02}:00'+'</th>'
        from night_shift.calendar_info import is_off_day
        for p in columns:
            flex=mode=='유도리' and ((source['shift']=='night' and p=='I1' and h in (22,23,0,1,2,3)) or
                (source['shift']=='day' and is_off_day(date.fromisoformat(source['day'])) and p in ('G2','G3')))
            style=' style="outline:3px solid #D400FF;outline-offset:-3px"' if flex else ''
            body+='<td'+style+'>'+escape(str(cells.get(p,'')))+'</td>'
        body+='</tr>'
    return ('<style>.team-sheet{width:100%;border-collapse:collapse;table-layout:fixed;font-size:clamp(9px,2.3vw,14px)}'
            '.team-sheet th,.team-sheet td{border:1px solid #999;text-align:center;padding:6px 1px;overflow-wrap:anywhere}'
            '.team-sheet th:first-child{width:34px;white-space:nowrap;font-size:10px}'
            '.team-sheet th{background:#e8ebef;color:#172333}</style><table class="team-sheet"><thead><tr>'
            +heads+'</tr></thead><tbody>'+body+'</tbody></table>')


def page(team,store):
    from team_schedule_view import page as show
    show(team,store)
