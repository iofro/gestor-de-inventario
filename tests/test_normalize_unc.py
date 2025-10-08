import pytest

from tools.verificador.license_backend import normalize_unc


@pytest.mark.parametrize(
    "value, expected",
    [
        (r"\\PC\Admin\LicenciasVertex\licenses", "\\\\PC\\Admin\\LicenciasVertex\\licenses"),
        ("\\\\\\\\PC_ADMIN\\LicenciasVertex\\licenses\\\\", "\\\\PC_ADMIN\\LicenciasVertex\\licenses"),
        ("/PC_ADMIN/LicenciasVertex/licenses", "\\\\PC_ADMIN\\LicenciasVertex\\licenses"),
        ("\\PC_ADMIN\\LicenciasVertex\\licenses", "\\\\PC_ADMIN\\LicenciasVertex\\licenses"),
        ('"\\\\PC_ADMIN\\LicenciasVertex\\licenses\\"', "\\\\PC_ADMIN\\LicenciasVertex\\licenses"),
    ],
)
def test_normalize_unc(value: str, expected: str) -> None:
    assert normalize_unc(value) == expected
