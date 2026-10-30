import json

import pytest

from app.channels.whatsapp import signature
from app.channels.whatsapp.payload import parse_webhook
from scripts.send_test_webhook import build_payload, sign


@pytest.mark.parametrize("kwargs,kind,field", [({"text": "hi"}, "text", "text"), ({"button_id": "g:c-1:ok"}, "button", "button_id"),
                                                ({"image_id": "IMG"}, "image", "media_id"), ({"audio_id": "AUD"}, "audio", "media_id")])
def test_built_payloads_parse_back(kwargs, kind, field):
    [m] = parse_webhook(build_payload("919810000001", **kwargs))
    assert m.kind == kind and m.from_phone == "919810000001" and getattr(m, field) and m.message_id.startswith("wamid.test-")


def test_payload_requires_content():
    with pytest.raises(ValueError):
        build_payload("91")


def test_signature_matches_what_the_server_verifies():
    body = json.dumps(build_payload("91", text="hi")).encode()
    assert signature.verify("s3cret", body, sign("s3cret", body)) and not signature.verify("other", body, sign("s3cret", body))


def test_each_payload_has_a_unique_message_id():
    assert build_payload("91", text="a")["entry"][0]["changes"][0]["value"]["messages"][0]["id"] != \
           build_payload("91", text="a")["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
