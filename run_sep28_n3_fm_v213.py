"""Rebuild the 28 September N3/FM plan using rulebook v2.13."""
from night_shift.models import NightType
from run_sep28_n2_fm import main


if __name__ == "__main__":
    # September 27 is a balance estimate, not a confirmed actual shift.
    main(NightType.N3, "2.13", actual_records=(), soft_debt=None)
