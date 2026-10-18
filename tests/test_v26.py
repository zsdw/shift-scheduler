import unittest
from dataclasses import replace
from run_v26 import context
from night_shift.models import HistoryInput
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial
from night_shift.profiles import make_record
from night_shift.common import compile_common_policy

class V26Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h=HistoryInput((),())
        cls.result=solve_first_trial(context(),cls.h,seconds=15,rules_v26=True)
        cls.plan=cls.result.record
        assert cls.plan is not None
    def errors(self, labels):
        replacements={(p,t):make_record(self.plan.context,p,t,label) for p,t,label in labels}
        rows=tuple(replacements.get((r.employee_id,r.slot.index),r) for r in self.plan.assignments)
        return validate_first_trial(replace(self.plan,assignments=rows),self.h,rules_v26=True)
    def test_generated_schedule(self):
        self.assertEqual(validate_first_trial(self.plan,self.h,rules_v26=True),[])
    def test_patrol_counts_as_fifth_work_hour(self):
        errors=self.errors([("1",t,label) for t,label in zip(range(3,8),["I1","G1","L3","G1","upper"])])
        self.assertTrue(any(e["rule"]=="H-08" and "Five" in e["detail"] for e in errors))
    def test_four_without_seated_rejected(self):
        errors=self.errors([("1",t,label) for t,label in zip(range(2,6),["G2","L3","G1","lower"])])
        self.assertTrue(any(e["rule"]=="H-08" and "without seated" in e["detail"] for e in errors))
    def test_22_boundary_triple_rejected(self):
        self.assertTrue(any(e["rule"]=="H-04" for e in self.errors([("1",t,"L3") for t in (4,5,6)])))
    def test_missing_04_standby_rejected(self):
        rows=[(r.employee_id,10,"휴게") for r in self.plan.assignments if r.slot.index==10 and r.displayed_assignment.label=="보안실 대기"]
        self.assertTrue(any(e["rule"]=="H-16" for e in self.errors(rows)))
    def test_five_workers_all_patrol_once(self):
        counts={p:sum(r.employee_id==p and r.actual_post_or_work_type.kind=="patrol" for r in self.plan.assignments) for p in ("1","2","3","4","5","A")}
        self.assertEqual(set(counts.values()),{1})
    def test_four_worker_gate_not_accidentally_extended(self):
        c=context()
        c=replace(c,attendance=tuple(replace(a,present=False) if a.employee_id=="5" else a for a in c.attendance))
        policy=compile_common_policy(c)
        self.assertFalse(any(r.slot_index in (1,2) and r.displayed_post=="G2" for r in policy.requirements))
    def test_five_flexible_installation_is_gate(self):
        from night_shift.models import Mode
        from night_shift.profiles import options_for
        c=replace(context(),requested_mode=Mode.FLEXIBLE,effective_mode=Mode.FLEXIBLE)
        opts=options_for(c,"1",2)
        self.assertTrue(any(r.displayed_assignment.label=="G2" and r.barrier_install_flag for r in opts))
        self.assertFalse(any(r.displayed_assignment.label=="I1" and r.barrier_install_flag for r in opts))
if __name__=="__main__":unittest.main()
