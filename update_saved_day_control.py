from pathlib import Path
from datetime import date
import json
from night_shift.day_control import control_e_slots

root = Path(__file__).resolve().parent
store = root / 'history'
for path in sorted((store / 'day').glob('*.json')):
    data = json.loads(path.read_text(encoding='utf-8'))
    data['control_e_slots'] = control_e_slots(store, date.fromisoformat(data['date']))
    backup = json.loads((root / 'backup/control_e_20261007/day' / path.name).read_text(encoding='utf-8'))
    assert {k:v for k,v in data.items() if k != 'control_e_slots'} == {k:v for k,v in backup.items() if k != 'control_e_slots'}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    assert json.loads(path.read_text(encoding='utf-8')) == data
    print(path.name, data['control_e_slots'])
