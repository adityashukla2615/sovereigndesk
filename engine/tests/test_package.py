import re

import sovereign_engine


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", sovereign_engine.__version__)
