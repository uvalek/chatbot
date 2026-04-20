from app.splitter import split_response


def test_array_basico():
    raw = '["hola", "como estas"]'
    assert split_response(raw) == ["hola", "como estas"]


def test_array_con_fence_json():
    raw = '```json\n["uno", "dos"]\n```'
    assert split_response(raw) == ["uno", "dos"]


def test_texto_plano_devuelve_un_solo_chunk():
    raw = "esto no es json"
    assert split_response(raw) == ["esto no es json"]


def test_filtra_strings_vacios():
    raw = '["hola", "", "  ", "fin"]'
    assert split_response(raw) == ["hola", "fin"]


def test_string_dentro_de_array_con_emoji():
    raw = '["¡Hola! 🏡", "¿En qué te ayudo?"]'
    assert split_response(raw) == ["¡Hola! 🏡", "¿En qué te ayudo?"]


def test_vacio():
    assert split_response("") == []


def test_objeto_no_lista_se_vuelve_string():
    raw = '{"foo": "bar"}'
    out = split_response(raw)
    assert len(out) == 1
