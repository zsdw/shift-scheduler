import unittest
from dataclasses import replace
from tests.test_patrol_two import PatrolTwoTests
from night_shift.models import HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.weekend_day import generate,validate

NAMES={'A':'통제A','1':'만년','2':'원종','3':'제욱','4':'광희','5':'성호','6':'준호'}
def event(day,shift,name,excluded=False):
    return {'date':day,'shift':shift,'name':name,'excluded':excluded,'patrol':not excluded}

class MixedPatrolTests(PatrolTwoTests):
    def test_holiday_counts_as_first_of_two(self):
        events=(event('2026-10-15',1,'원종',True),event('2026-10-17',0,'원종'))
        errors=validate_first_trial(self.current,HistoryInput((),()),rules_v220=True,patrol_events=events)
        self.assertTrue(any(e['rule']=='14-1-2' for e in errors))
        events+= (event('2026-10-18',0,'원종'),)
        errors=validate_first_trial(self.current,HistoryInput((),()),rules_v220=True,patrol_events=events)
        self.assertFalse(any(e['rule']=='14-1-2' for e in errors))
    def test_never_excluded_person_is_excluded_first(self):
        events=tuple(event('2026-10-03',1,n,True) for n in list(NAMES.values())[1:6])
        events+=tuple(event(d,0,n) for d in ('2026-10-04','2026-10-10') for n in list(NAMES.values())[1:])
        result,status=generate('2026-10-17',NAMES,seconds=20,patrol_events=events)
        self.assertIsNotNone(result,status)
        self.assertNotIn('순찰',result.grid['6'])
        self.assertFalse(validate(result))

    def test_holiday_generator_and_independent_validator(self):
        events=tuple(event('2026-10-09',1,n,True) for n in list(NAMES.values())[1:])
        # 원종은 직전 야간 제외: 이번 공휴일 순찰 필수. 나머지는 보호 종료, 제외 경험만 남음.
        events+=tuple(event(d,0,n) for d in ('2026-10-10','2026-10-11') for n in list(NAMES.values())[1:])
        events+=(event('2026-10-16',1,'원종',True),)
        result,status=generate('2026-10-17',NAMES,seconds=20,patrol_events=events)
        self.assertIsNotNone(result,status)
        self.assertIn('순찰',result.grid['2'])
        self.assertFalse(validate(result))
        grid={p:list(row) for p,row in result.grid.items()}
        grid['2']=['휴게' if v=='순찰' else v for v in grid['2']]
        self.assertTrue(any('다음 출근 2회' in e for e in validate(replace(result,grid=grid))))

class MixedHistoryLoadingTests(unittest.TestCase):
    def test_day_before_night_and_only_holiday_day(self):
        import tempfile,json
        from pathlib import Path
        from datetime import date,datetime
        from night_shift.models import RecordKind
        from night_shift.history_store import record_from_json,save_confirmed
        from night_shift.patrol_history import load_events
        raw=json.loads((Path(__file__).parent/'fixtures/patrol_rules_record.json').read_text(encoding='utf-8'))
        record=record_from_json(raw['plan'])
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder)
            for day in (date(2026,10,16),date(2026,10,17)):
                save_confirmed(store,replace(record,context=replace(record.context,shift_start_date=day)),'2.20')
            (store/'weekend_day').mkdir()
            for day in ('2026-10-15','2026-10-17'):
                (store/'weekend_day'/f'{day}.json').write_text(json.dumps({'names':NAMES,
                    'grid':{p:['순찰' if p=='2' else '휴게']*10 for p in NAMES}}),encoding='utf-8')
            day_events=load_events(store,date(2026,10,17),'day')
            night_events=load_events(store,date(2026,10,17),'night')
            self.assertFalse(any(e['date']=='2026-10-17' for e in day_events))
            self.assertTrue(any(e['date']=='2026-10-17' and e['shift']==0 for e in night_events))
            self.assertFalse(any(e['date']=='2026-10-17' and e['shift']==1 for e in night_events))
            self.assertFalse(any(e['date']=='2026-10-15' for e in night_events))
