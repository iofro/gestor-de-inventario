from app.dte import ensure_numero_control, NC_BASE
from copy import deepcopy
import re

CONTROL_REGEX = re.compile(r"^DTE-05-[A-Z0-9]{8}-[0-9]{15}$")


def test_generate_control_number_matches_pattern():
    env = deepcopy(NC_BASE)
    numero = ensure_numero_control(env)
    assert CONTROL_REGEX.match(numero)
    ident = env["identificacion"]
    assert CONTROL_REGEX.match(ident["numeroControl"])
    # codigoGeneracion should be UUID-like uppercase
    codigo = ident["codigoGeneracion"]
    assert codigo and codigo == codigo.upper()


def test_control_number_accepts_correlativo():
    env = deepcopy(NC_BASE)
    numero = ensure_numero_control(env, correlativo15="123")
    assert numero.split("-")[-1] == "000000000000123"
