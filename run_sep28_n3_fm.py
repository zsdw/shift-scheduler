"""Corrected 2026-09-28 N3/FM plan with the assumed 27 Sep FM balance history."""
from night_shift.models import NightType
from run_sep28_n2_fm import main


if __name__ == "__main__":
    main(NightType.N3)
