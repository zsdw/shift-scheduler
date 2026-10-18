"""Rebuild the 28 September N3/FM plan using rulebook v2.12."""
from night_shift.models import NightType
from run_sep28_n2_fm import main


if __name__ == "__main__":
    main(NightType.N3, "2.12")
