from app.channels.manychat import parse_webhook


def test_parse_text_from_body_wrapper():
    body = {"body": {"id": "subs_1", "text": "hola"}}
    out = parse_webhook(body)
    assert out["chat_id"] == "subs_1"
    assert out["text"] == "hola"
    assert out["media_type"] is None


def test_parse_image():
    body = {
        "id": "subs_2",
        "text": None,
        "last_interaction": {
            "mime_type": "image/jpeg",
            "url": "https://x/img.jpg",
        },
    }
    out = parse_webhook(body)
    assert out["media_type"] == "image"
    assert out["media_url"] == "https://x/img.jpg"


def test_parse_audio():
    body = {
        "id": "subs_3",
        "last_interaction": {"mime_type": "video/mp4", "url": "https://x/a.mp4"},
    }
    out = parse_webhook(body)
    assert out["media_type"] == "audio"


def test_returns_none_without_id():
    assert parse_webhook({"text": "hola"}) is None
