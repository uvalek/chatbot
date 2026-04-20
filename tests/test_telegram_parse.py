from app.channels.telegram import parse_update


def test_parse_text():
    update = {"message": {"chat": {"id": 123}, "text": "hola"}}
    out = parse_update(update)
    assert out["chat_id"] == "123"
    assert out["text"] == "hola"
    assert out["media_type"] is None


def test_parse_voice():
    update = {"message": {"chat": {"id": 9}, "voice": {"file_id": "abc"}}}
    out = parse_update(update)
    assert out["media_type"] == "audio"
    assert out["media_file_id"] == "abc"


def test_parse_photo_picks_largest():
    update = {
        "message": {
            "chat": {"id": 9},
            "photo": [{"file_id": "small"}, {"file_id": "big"}],
        }
    }
    out = parse_update(update)
    assert out["media_type"] == "image"
    assert out["media_file_id"] == "big"


def test_parse_unknown_returns_none():
    assert parse_update({}) is None
