import re
from copy import deepcopy

from app.dte import ND_BASE, ensure_numero_control, ND_CONTROL_REGEX


def test_numero_control_regex():
    env = deepcopy(ND_BASE)
    ensure_numero_control(env)
    numero = env["identificacion"]["numeroControl"]
    assert re.fullmatch(ND_CONTROL_REGEX, numero)
