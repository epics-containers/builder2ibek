from pathlib import Path

from builder2ibek.dbcompare import compare_dbs


def test_conmpare(samples: Path):
    old = samples / "SR03C-VA-IOC-01_expanded.db"
    new = samples / "sr03c-va-ioc-01.db"
    result = Path("/tmp") / "compare.diff"

    output = Path("/tmp") / "compare.diff"
    compare_dbs(old, new, ignore=["SR03C-VA-IOC-01:"], output=output)

    assert result.read_text() == output.read_text()
