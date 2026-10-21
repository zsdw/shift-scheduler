"""Actual supplied weekday PNG: uncertain cells, review, route, backup and reopen."""
import os,json,tempfile,unittest,copy
from dataclasses import replace
from datetime import date
from pathlib import Path
from io import BytesIO
from unittest.mock import patch
from PIL import Image,ImageOps
from streamlit.testing.v1 import AppTest
from night_shift import schedule_image_import as imp
from night_shift import history_import,history_store
from night_shift.day_shift import load_day

SOURCE=Path(__file__).parent/'fixtures'/'weekday_2026-10-07_field.png'

@unittest.skipUnless(os.name=='nt','Windows OCR required')
class ImageImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=SOURCE.read_bytes();cls.draft=imp.parse_image(cls.data)

    def reviewed(self):
        d=copy.deepcopy(self.draft)
        # Two readings verified visually against source; CP3 name corrected from the source header.
        d.rows[1]['CP']='CP1';d.rows[3]['순찰']='A';d.extra_names['CP3']='철룡'
        return d

    def qa_saveable(self):
        d=self.reviewed()
        # Source rest overlap stays intact; user's explicit work-over-rest priority resolves it.
        return d

    def test_actual_source_metadata_numbers_and_uncertainty(self):
        d=self.draft
        self.assertEqual((d.day,d.kind,d.team),(date(2026,10,7),'day','A'))
        self.assertEqual(d.mapping,dict(zip(map(str,range(1,12)),('준형','원종','제욱','광희','만년','도운','성욱','용주','준호','여진','지훈'))))
        self.assertEqual(len(d.rows),10)
        self.assertEqual(d.rows[0]['G1'],'1')
        self.assertEqual(imp.persons(d.rows[6]['휴게']),['7','8','11'])
        self.assertEqual(d.rows[1]['CP'],imp.UNKNOWN)
        self.assertEqual(d.rows[3]['순찰'],'A')   # single glyph read by shape + hourly headcount (2026-10-07)
        self.assertEqual(d.rows[8]['휴게'],'1.3.CP2')
        with self.assertRaises(ValueError):imp.build_day(d.day,d.rows,d.mapping)

    def test_work_and_patrol_take_priority_over_rest_but_work_work_blocks(self):
        d=self.reviewed()
        self.assertEqual(imp.build_day(d.day,d.rows,d.mapping).grid['제욱'][8],'순찰')
        self.assertTrue(any('제욱' in s and '순찰 우선' in s for s in imp.rest_priority_notes(d.rows,d.mapping)))
        self.assertEqual(d.rows[8]['휴게'],'1.3.CP2')
        d.rows[8]['G1']='2.3'
        with self.assertRaisesRegex(ValueError,'16:00.*중복'):
            imp.build_day(d.day,d.rows,d.mapping)

    def test_program_table_preserves_auxiliary_tenth_worker_and_cp(self):
        from night_shift.day_shift import from_json,to_json
        from day_ui import day_sheet_html
        d=self.reviewed();s=imp.build_day(d.day,d.rows,d.mapping)
        s=from_json(to_json(s));html=day_sheet_html(s)
        self.assertIn('10여진',html);self.assertIn('<th>4C</th>',html)
        self.assertIn('<th>CP</th>',html);self.assertIn('<th>1C</th>',html)
        for hour in (8,10,12,14,16):
            self.assertIn('A.10',html.split(f'{hour:02}:00',1)[1].split('</tr>',1)[0])
        for hour in (9,11,13,15,17):
            self.assertIn('10',html.split(f'{hour:02}:00',1)[1].split('</tr>',1)[0])
        self.assertIn('CP1',html.split('09:00',1)[1].split('</tr>',1)[0])
        last=html.split('17:00',1)[1].split('</tr>',1)[0]
        self.assertIn('CP3',last);self.assertIn('11</span>',last)
        # Legacy saved imports need no write or re-upload to gain the full program table.
        payload=to_json(s);payload.pop('source_layout');payload['source_review']={'mapping':d.mapping,'rows':d.rows}
        self.assertIn('A.10',day_sheet_html(from_json(payload)))

    def test_joint_workers_render_and_newcomer_rule_exemption_persists(self):
        from night_shift.day_shift import to_json,from_json,rule_schedule,validate_day
        from day_ui import day_sheet_html
        d=self.reviewed();s=imp.build_day(d.day,d.rows,d.mapping,newcomers=['11'])
        s=from_json(to_json(s));self.assertEqual(s.rule_exempt_names,('지훈',))
        self.assertEqual(s.grid['지훈'][1],'G3');self.assertEqual(s.grid['용주'][1],'G3')
        row=day_sheet_html(s).split('09:00',1)[1].split('</tr>',1)[0]
        self.assertIn("8</span>.<span",row);self.assertIn("11</span>",row)
        self.assertNotIn('지훈',rule_schedule(s).grid)
        self.assertFalse(any('지훈' in e['detail'] for e in validate_day(s)))

    def test_multiple_manager_patrols_survive_save_render_and_resave(self):
        from night_shift.day_shift import to_json,from_json,control_patrol_at
        from day_ui import day_sheet_html
        d=self.reviewed();s=imp.build_day(d.day,d.rows,d.mapping)
        self.assertEqual(s.control_patrol_slots,(3,6))
        for _ in range(2):
            s=from_json(to_json(s))
            self.assertTrue(control_patrol_at(s,3));self.assertTrue(control_patrol_at(s,6))
            html=day_sheet_html(s)
            for hour in ('11:00','14:00'):
                row=html.split(hour,1)[1].split('</tr>',1)[0]
                self.assertGreaterEqual(row.count(">A</td>"),1)
        self.assertEqual(d.rows[1]['CP'],'CP1')

    def test_unknown_name_missing_assignment_and_duplicate_name_block(self):
        d=self.qa_saveable();d.mapping['1']=''
        with self.assertRaises(ValueError):imp.build_day(d.day,d.rows,d.mapping)
        d=self.qa_saveable();d.rows[0]['G1']=''
        with self.assertRaisesRegex(ValueError,'배정을 읽지 못'):
            imp.build_day(d.day,d.rows,d.mapping)
        d=self.qa_saveable();d.mapping['1']=d.mapping['2']
        with self.assertRaisesRegex(ValueError,'같은 이름'):imp.build_day(d.day,d.rows,d.mapping)

    def test_save_backup_reopen_and_stale_review(self):
        d=self.qa_saveable();s=imp.build_day(d.day,d.rows,d.mapping)
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder)/'day'
            p=imp.save_day_image(store,s,d,d.rows,d.mapping,self.data,'1007주간.png',team='A')
            first=p.read_bytes();payload=load_day(store,d.day)
            self.assertEqual(payload['source_review']['rows'],d.rows)
            self.assertEqual(payload['source_review']['mapping']['10'],'여진')
            self.assertEqual(payload['schedule'].grid['제욱'][8],'순찰')
            self.assertEqual(payload['schedule'].grid['준형'][2],'교육')
            self.assertTrue(Path(payload['source_image']).is_file())
            stamp=imp.fingerprint(store,d.day)
            imp.save_day_image(store,s,d,d.rows,d.mapping,self.data,'1007주간.png',stamp,'A')
            self.assertEqual(p.read_bytes(),first);self.assertFalse((store/'.trash').exists())
            # 2026-10-10 사용자 확정: CP만 다른 업로드는 같은 표(덮어쓰지 않음)
            cp_only=copy.deepcopy(d.rows);cp_only[1]['CP']='CP2'
            imp.save_day_image(store,s,d,cp_only,d.mapping,self.data,'1007주간.png',stamp,'A')
            self.assertEqual(p.read_bytes(),first);self.assertFalse((store/'.trash').exists())
            # 포스트 투입자가 바뀌면 덮어쓰고 이전 저장본을 백업
            changed=copy.deepcopy(d.rows);changed[1]['G1'],changed[1]['G2']=changed[1]['G2'],changed[1]['G1']
            s2=imp.build_day(d.day,changed,d.mapping)
            imp.save_day_image(store,s2,d,changed,d.mapping,self.data,'1007주간.png',stamp,'A')
            self.assertEqual(next((store/'.trash').glob('*.json')).read_bytes(),first)
            self.assertIn('덮어씌워진 근무표',load_day(store,d.day)['note'])
            with self.assertRaisesRegex(ValueError,'바뀌었'):
                imp.save_day_image(store,s,d,d.rows,d.mapping,self.data,'1007주간.png','stale','A')

    def test_scaled_and_grayscale_source_retains_classification(self):
        for factor,gray in ((.85,False),(1.15,True)):
            with self.subTest(factor=factor,gray=gray):
                im=Image.open(BytesIO(self.data));im=im.resize((round(im.width*factor),round(im.height*factor)))
                if gray:im=ImageOps.grayscale(im)
                b=BytesIO();im.save(b,'PNG');d=imp.parse_image(b.getvalue())
                self.assertEqual((d.day,d.kind,d.team),(date(2026,10,7),'day','A'))
                self.assertEqual(len(d.rows),10)
                self.assertIn(d.rows[0]['G1'],('1',imp.UNKNOWN))

    def test_night_source_automatic_classification(self):
        d=imp.parse_image((SOURCE.parent/'night_2026-10-03_field.png').read_bytes())
        self.assertEqual((d.kind,d.day),('night',date(2026,10,3)))
        self.assertEqual([r['시간'] for r in d.rows],['18:00','19:00','20:00','21:00','22:00','23:00','00:00','01:00','02:00','03:00','04:00','05:00','06:00','07:00'])

    def test_pc_mobile_upload_review_save_and_overwrite(self):
        data=self.data;draft=self.qa_saveable()
        draft.warnings += ['09:00 CP: 확인 필요','11:00 순찰: 확인 필요']
        class Upload:
            name='1007주간.png'
            def getvalue(self):return data
        for view in ('pc','mobile'):
            with self.subTest(view=view),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}):
                at=AppTest.from_string('from import_ui import render_importer\nrender_importer()',default_timeout=60)
                at.query_params['view']=view
                def run():
                    with patch('streamlit.file_uploader',return_value=Upload()),patch('night_shift.schedule_image_import.parse_image',return_value=copy.deepcopy(draft)):
                        at.run()
                run();self.assertFalse(at.exception,[e.message for e in at.exception])
                self.assertTrue(any('평일 주간' in x.value for x in at.success))
                self.assertFalse(any('09:00 CP: 확인 필요' in x.value or '11:00 순찰: 확인 필요' in x.value for x in at.warning))
                from hashlib import sha256
                key='image_review_'+sha256(data).hexdigest()[:12]
                self.assertFalse(at.button(key=key+'_save').disabled)
                self.assertFalse(at.button(key=key+'_save_edited').disabled)
                at.button(key=key+'_save').click();run();self.assertFalse(at.exception,[e.message for e in at.exception])
                path=Path(folder)/'day'/'2026-10-07.json';self.assertTrue(path.exists())
                self.assertFalse((Path(folder)/'2026-10-07.json').exists())
                first=path.read_bytes()
                at.button(key=key+'_save').click();run()
                self.assertFalse(at.exception)
                self.assertEqual(path.read_bytes(),first)
                self.assertFalse((path.parent/'.trash').exists())

class RoutingTests(unittest.TestCase):
    def test_newcomer_personnel_dates_and_ambiguous_names(self):
        from night_shift.newcomers import detect
        from night_shift.daily_report import save_roster
        from night_shift.leave_schedule import save_text
        rows=[{'시간':'09:00','G3':'8.11','휴게':'1'}]
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder)
            save_roster(store,[{'이름':'조용주','소속':'주간고정','직책':'대원'}, {'이름':'이지훈','소속':'C조','직책':'대원','시작':'2026-10-06'}])
            mapping={'8':'용주','11':'지훈'}
            self.assertEqual(set(detect(store,date(2026,10,7),rows,mapping)),{'11'})
            self.assertFalse(detect(store,date(2026,10,5),rows,mapping))
            save_text(store,'10월 6일\nC조 이지훈 사원 - 입사\n10월 8일\nC조 이지훈 사원 - 입사 예정')
            self.assertIn('연차일정',detect(store,date(2026,10,7),rows,mapping)['11'])
            save_roster(store,[{'이름':'이지훈','소속':'C조','직책':'대원'}, {'이름':'김지훈','소속':'B조','직책':'대원'}])
            self.assertFalse(detect(store,date(2026,10,7),rows,mapping))

    def test_single_glyph_cells_and_roster_names_1008(self):
        from night_shift.daily_report import save_roster
        data=(SOURCE.parent/'weekday_2026-10-08_field.png').read_bytes()
        d=imp.parse_image(data)
        self.assertFalse([w for w in d.warnings if w.endswith('확인 필요')],d.warnings)
        for hour,col in (('08:00','4C'),('10:00','4C'),('11:00','순찰'),('12:00','4C'),('14:00','4C'),('14:00','순찰'),('16:00','4C'),('17:00','휴게')):
            self.assertEqual(next(r for r in d.rows if r['시간']==hour)[col],'A',(hour,col))
        self.assertEqual(next(r for r in d.rows if r['시간']=='16:00')['대기'],'5')
        self.assertEqual(d.mapping['4'],'원종')
        self.assertIn('D',d.controls)
        with tempfile.TemporaryDirectory() as folder:
            save_roster(Path(folder),[{'이름':'안철룡','소속':'A조','직책':'CP'},{'이름':'한만년','소속':'A조','직책':'대원'}])
            d=imp.roster_repair(d,folder)
        self.assertEqual(d.extra_names['CP2'],'철룡')
        self.assertTrue(any('1·6번' in w for w in d.warnings))

    def test_single_glyph_reading_refuses_a_person_already_counted_that_hour(self):
        from night_shift import glyph_read
        data=(SOURCE.parent/'weekday_2026-10-08_field.png').read_bytes()
        with patch.object(glyph_read,'classify',return_value=('2',.95,.3)):
            d=imp.parse_image(data)
        # 11:00 L1 is already 2, so a shape that looks like 2 in 순찰 must stay for review.
        self.assertEqual(next(r for r in d.rows if r['시간']=='11:00')['순찰'],imp.UNKNOWN)
        with patch.object(glyph_read,'classify',return_value=('A',.75,.72)):
            d=imp.parse_image(data)
        self.assertEqual(next(r for r in d.rows if r['시간']=='08:00')['4C'],imp.UNKNOWN)   # unclear margin

    def test_newcomer_recorded_from_first_solo_post(self):
        import json
        from night_shift.newcomers import detect
        from night_shift.daily_report import save_roster
        paired=[{'시간':'09:00','G3':'8.11','순찰':'11','휴게':'1'}]
        solo=[{'시간':'09:00','G3':'8.11'},{'시간':'10:00','G1':'11'}]
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder);mapping={'8':'용주','11':'지훈'}
            save_roster(store,[{'이름':'조용주','소속':'주간고정','직책':'대원'}, {'이름':'이지훈','소속':'C조','직책':'대원','시작':'2026-10-06'}])
            # Patrol or paired posts alone do not start the record; a solo post does, from that day on.
            self.assertEqual(set(detect(store,date(2026,10,7),paired,mapping)),{'11'})
            self.assertFalse(detect(store,date(2026,10,7),solo,mapping))
            (store/'day').mkdir()
            write=lambda day,exempt:(store/'day'/f'{day}.json').write_text(json.dumps({'people':[{'pid':'용주'},{'pid':'지훈'}],'rule_exempt_names':exempt}),encoding='utf-8')
            write('2026-10-07',['지훈'])
            self.assertEqual(set(detect(store,date(2026,10,8),paired,mapping)),{'11'})
            write('2026-10-08',[])
            self.assertFalse(detect(store,date(2026,10,9),paired,mapping))
            self.assertEqual(set(detect(store,date(2026,10,8),paired,mapping)),{'11'})


    def test_review_swap_preserves_cp_and_rejects_other_hours(self):
        rows=[{'시간':'08:00','G1':'1','G2':'2','휴게':'3.CP1'},{'시간':'09:00','G1':'2','G2':'1','휴게':'3.CP2'}]
        changed=imp.swap_review(rows,['1',0],['2',0])
        self.assertEqual((changed[0]['G1'],changed[0]['G2'],changed[0]['휴게']),('2','1','3.CP1'))
        self.assertEqual(changed[1],rows[1]);self.assertEqual(rows[0]['G1'],'1')
        with self.assertRaises(ValueError):imp.swap_review(rows,['1',0],['2',1])

    def test_title_clocks_holiday_and_conflict(self):
        self.assertEqual(imp.classify('주간 근무 2026년 10월 09일',[8,9,10]),(date(2026,10,9),'weekend_day'))
        self.assertEqual(imp.classify('야간 2026년 10월 09일',[18,19,20]),(date(2026,10,9),'night'))
        with self.assertRaisesRegex(ValueError,'제목과 시간대'):imp.classify('야간',[8,9,10])
        with self.assertRaises(ValueError):imp.classify('그냥 사진',[])

    def test_weekend_store_reopens_without_metadata_error(self):
        from night_shift.weekend_day import load
        rows=[{'시간':f'{h:02}:00','G1':'1','G2':'2','I1':'3','L1':'4','순찰':'5','휴게':'A.6'} for h in range(8,18)]
        mapping={str(p):f'직원{chr(65+p)}' for p in range(1,7)}
        d=imp.ImageDraft(date(2026,10,9),'weekend_day','A',mapping,['A'],rows,[],'','')
        s=imp.build_day(d.day,rows,mapping,'weekend_day')
        b=BytesIO();Image.new('RGB',(40,40),'white').save(b,'PNG')
        with tempfile.TemporaryDirectory() as folder:
            imp.save_day_image(folder,s,d,rows,mapping,b.getvalue(),'holiday.png',team='A')
            self.assertEqual(load(folder,d.day).grid,s.grid)
            self.assertEqual(json.loads((Path(folder)/f'{d.day}.json').read_text(encoding='utf-8'))['source_review']['kind'],'weekend_day')

    def test_night_review_build_and_existing_store(self):
        from night_shift.models import Mode
        rows=[{'시간':f'{h:02}:00','G1':'1','L3':'2','I1':'3','보안실':'4','휴게':'A.1.4.5.6','순찰':'','CP':''} for h in list(range(18,24))+list(range(8))]
        mapping={p:n for p,n in history_import.ROSTER.items() if p!='A'}
        record=imp.build_night(date(2026,10,3),rows,mapping,Mode.FM)
        self.assertEqual(next(r.displayed_assignment.label for r in record.assignments if r.employee_id=='1' and r.slot.index==0),'G1')
        with tempfile.TemporaryDirectory() as folder:
            history_import.save_import(Path(folder),record,'image-import','QA actual review')
            self.assertEqual(history_store.load(Path(folder),date(2026,10,3))['plan_record'].assignments,record.assignments)

if __name__=='__main__':unittest.main()
