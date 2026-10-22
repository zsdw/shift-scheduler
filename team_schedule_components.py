"""A조 표·달력 컴포넌트를 조별 조회에도 사용한다."""
from datetime import date,timedelta
from html import escape
from pathlib import Path
from team_schedule_analysis import people,hours,tokens,POSTS,RESTS,details


def night_payload(source,mode,compact=False):
    from night_shift.day_shift import NUMBER_COLORS
    persons=dict(sorted(people(source).items(),key=lambda item:(item[0].isdigit(),int(item[0]) if item[0].isdigit() else item[0])));rows=[];colors={};shown={};heads=[]
    detail={(r['번호'],r['시']):r for r in details(source,mode)}
    for who,name in persons.items():
        heads.append([who,(who if who.isdigit() else '')+name])
        labels=[]
        for h in hours(source):
            c=source['cells'].get(str(h),{})
            labels.append([p for p in POSTS if who in tokens(c.get(p))]+
                ([(detail[who,h]['층'] or '순찰')] if who in tokens(c.get('순찰')) else []))
            if not labels[-1]:
                labels[-1]=['보안실 대기' if any(who in tokens(c.get(p)) for p in RESTS[2:])
                            else '휴게' if any(who in tokens(c.get(p)) for p in RESTS[:2]) else '—']
        for extra in range(max(map(len,labels))):
            pid=who if extra==0 else f'{who}_{extra}'
            colors[pid]=NUMBER_COLORS.get(int(who),'FFFFFF') if who.isdigit() else 'FFFFFF';shown[pid]=who
            rows.append({'id':pid,'label':name,'movable':False,'cells':[
                {'t':t,'label':values[extra] if extra<len(values) else '—','color':'FFFFFF','movable':False,
                 'notes':('↑설치' if detail[who,h]['설치'] else '↓철수' if detail[who,h]['철수'] else '') if extra==0 else ''}
                for t,(h,values) in enumerate(zip(hours(source),labels))]})
    heads += [[f'cp{n}',f'CP{n}{v}'] for n,v in source.get('cp',{}).items()]
    d=date.fromisoformat(source['day'])
    return {'hours':[f'{h:02}시' for h in hours(source)],'rows':rows,'compact':compact,'readonly':True,
            'hour_click':False,'cell_click':False,'tap_swap':False,'view_toggle':True,'view_mode':mode,
            'band':[4,10] if mode=='유도리' else None,
            'sheet':{'title':'야간 근무 편성표','sub':f'{d:%Y년 %m월 %d일} {"월화수목금토일"[d.weekday()]}요일 근무조 : {source["team"]}조',
                     'heads':heads,'tokens':shown,'colors':colors,'hours':[f'{24 if h==0 else h:02}:00' for h in hours(source)],
                     'cp':[source['cells'].get(str(h),{}).get('CP','') for h in hours(source)],
                     'shuttle':[source['cells'].get(str(h),{}).get('셔틀','') for h in hours(source)],
                     'operations':{}}}


def day_html(source,mode,compact=False):
    from night_shift.day_shift import NUMBER_COLORS
    from night_shift.calendar_info import is_off_day
    from night_shift.day_image import cp_color
    d=date.fromisoformat(source['day'])
    columns=[p for p in ('G1','G2','G3','4C','L1','L2','L3','I1','C1','C2','CP','1C','셔틀','순찰','보안실','대기','휴게')
             if p in ('G1','G2','L1','순찰','휴게') or any(str(r.get(p,'')).strip() for r in source['cells'].values())]
    width=len(columns)+1
    style="""<style>.dsheet{border-collapse:collapse;width:100%;table-layout:fixed;font-size:.9rem;text-align:center;color:#111827;background:#fff}
    .dsheet td,.dsheet th{border:1px solid #9ca3af;height:34px;padding:2px;color:#111827;overflow-wrap:anywhere}.dsheet td{background:#fff}
    .dsheet th{background:#d9d9d9;font-weight:600}.dsheet .title{font-size:1.35rem;font-weight:800;height:48px}.dsheet .sub{font-size:1.1rem;font-weight:700}
    .dsheet .name{font-weight:500;height:40px}.dsheet .legend{text-align:left;font-size:.78rem;color:#4b5563;height:auto;padding:5px 8px}
    .dsheet .vbtn{border:1px solid #cbd5e1;border-radius:5px;background:white;padding:4px 8px;cursor:pointer}.dsheet .vbtn.on{background:#e0f2fe}
    .dsheet .flex{outline:3px solid #D400FF;outline-offset:-3px}.dsheet .titleline{display:flex;align-items:center;justify-content:space-between;gap:6px}
    </style>"""
    if compact:style+="<style>.dsheet{font-size:10px}.dsheet td,.dsheet th{height:28px;padding:2px 0}.dsheet .title{font-size:15px}.dsheet .sub{font-size:11px}.dsheet .name{height:28px}.dsheet .legend{font-size:9px}</style>"
    button=lambda m:f'<button class="vbtn{" on" if mode==m else ""}" data-view="{m}">{m}</button>'
    out=[style,f'<table class="dsheet"><colgroup><col style="width:{36 if compact else 80}px">'+ '<col>'*len(columns)+'</colgroup>',
         f'<tr><td class="title" colspan="{width}"><div class="titleline">{button("FM")}<span>주간 근무 편성표</span>{button("유도리")}</div></td></tr>',
         f'<tr><td class="sub" colspan="{width}">{d:%Y년 %m월 %d일} {"월화수목금토일"[d.weekday()]}요일 근무조 : {source["team"]}조</td></tr>']
    names=sorted(people(source).items(),key=lambda item:(item[0].isdigit(),int(item[0]) if item[0].isdigit() else item[0]))
    tags=[(n,(n if n.isdigit() else '')+v) for n,v in names]+[(f'CP{n}',f'CP{n}{v}') for n,v in source.get('cp',{}).items()]
    for i in range(0,max(1,len(tags)),len(columns)):
        part=tags[i:i+len(columns)]
        out.append('<tr>'+('<th rowspan="'+str((len(tags)+len(columns)-1)//len(columns))+'">근무자명</th>' if i==0 else '')+
                   ''.join(f'<td class="name" data-who="{escape(n)}">{escape(v)}</td>' for n,v in part)+'<td></td>'*(len(columns)-len(part))+'</tr>')
    out.append('<tr><th>근무시간</th>'+''.join('<th>'+escape(p)+'</th>' for p in columns)+'</tr>')
    for t,h in enumerate(hours(source)):
        out.append(f'<tr><th>{h:02}:00</th>')
        for p in columns:
            text=str(source['cells'].get(str(h),{}).get(p,'') or '')
            nums=[int(n) for n in tokens(text) if n.isdigit()]
            color=cp_color(text) if p=='CP' else NUMBER_COLORS.get(max(nums),'FFFFFF') if nums and p not in RESTS else 'FFFFFF'
            flex=mode=='유도리' and is_off_day(d) and p in ('G2','G3')
            body='.'.join(f'<span data-who="{escape(n)}">{escape(n)}</span>' for n in sorted(tokens(text),key=lambda n:(not n.isdigit(),int(n) if n.isdigit() else n))) if text and not any(x in text for x in ('교육','(',')','부팀장')) else escape(text)
            out.append(f'<td data-col="{p}" data-t="{t}" class="{"flex" if flex else ""}" style="background:#{color or "FFFFFF"}">{body}</td>')
        out.append('</tr>')
    out.append(f'<tr><td class="legend" colspan="{width}">번호·이름에 마우스를 올리면(누르면 고정) 그 사람의 하루 칸 강조</td></tr></table>')
    return ''.join(out)


def schedule(source,mode,compact=False):
    import streamlit as st
    import streamlit.components.v1 as components
    root=Path(__file__).resolve().parent/'night_shift'
    if source['shift']=='night':
        grid=components.declare_component('team_night_sheet',path=str(root/'drag_grid'))
        event=grid(data=night_payload(source,mode,compact),key=f'team_grid_{source["team"]}_{source["day"]}_night',default=None)
    else:
        grid=components.declare_component('team_day_sheet',path=str(root/'day_grid'))
        event=grid(data={'html':day_html(source,mode,compact),'menus':{},'edit':False,'name_pin':True},key=f'team_grid_{source["team"]}_{source["day"]}_day',default=None)
    if isinstance(event,dict) and event.get('kind')=='view' and event.get('nonce')!=st.session_state.get('team_view_nonce'):
        st.session_state['team_view_nonce']=event.get('nonce')
        st.session_state['team_analysis_mode']='유도리' if event.get('mode')=='유도리' else 'FM'
        st.rerun()
