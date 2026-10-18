import unittest
from datetime import date
from dataclasses import replace
from tests.test_manager_first_last import staff
from night_shift.models import Mode, NightType
from night_shift.service import ShiftRequest, build_context, flexible_view
from night_shift.profiles import make_record
from night_shift.solver import _flexible_delta
from night_shift import history_import as imp

class Flexible22Tests(unittest.TestCase):
    def test_new_request_default_and_explicit_override(self):
        req=ShiftRequest(date(2026,10,16),NightType.N2,Mode.FM,staff((),False))
        self.assertEqual(build_context(req).post_operations,(("I1",4,9,"rest"),))
        self.assertEqual(build_context(replace(req,post_operations=())).post_operations,())
    def test_solver_delta_matches_profile_22_to_03(self):
        c=build_context(ShiftRequest(date(2026,10,16),NightType.N2,Mode.FM,staff((),False)))
        flex=replace(c,requested_mode=Mode.FLEXIBLE,effective_mode=Mode.FLEXIBLE)
        for slot in range(3,10):
            row=make_record(c,"1",slot,"I1")
            changed=make_record(flex,"1",slot,"I1")
            self.assertEqual(_flexible_delta(row,slot,flex),
                (changed.fatigue_value-row.fatigue_value,changed.actual_work_time_value-row.actual_work_time_value))
            self.assertEqual(changed.actual_rest_time_value,int(slot>=4))
    def test_flexible_view_preserves_custom_and_legacy(self):
        grid={p:["휴게"]*14 for p in ("A","1","2","3","4","5","6")}
        grid["1"][4:10]=["I1"]*6
        old=imp.build_import_record(date(2026,10,16),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
        old=replace(old,context=replace(old.context,post_operations=None))
        self.assertIsNone(old.context.post_operations)
        new=replace(old,context=replace(old.context,post_operations=(("I1",4,9,"rest"),)))
        old_view=flexible_view(old);new_view=flexible_view(new)
        self.assertEqual(new_view.context.post_operations,new.context.post_operations)
        self.assertEqual(sum(r.actual_rest_time_value for r in new_view.assignments if r.employee_id=="1" and 4<=r.slot.index<=9),6)
        self.assertEqual(sum(r.actual_rest_time_value for r in old_view.assignments if r.employee_id=="1" and 4<=r.slot.index<=9),4)
