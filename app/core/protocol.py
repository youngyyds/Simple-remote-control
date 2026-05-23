import json
import uuid
from typing import Optional

VERSION = 1


def make_msg(msg_type: str, payload: dict = None, msg_id: Optional[str] = None, version: int = VERSION) -> str:
    if payload is None:
        payload = {}
    if msg_id is None:
        msg_id = str(uuid.uuid4())
    envelope = {
        'version': version,
        'type': msg_type,
        'id': msg_id,
        'payload': payload,
    }
    return json.dumps(envelope)


def parse_msg(raw: str) -> dict:
    data = json.loads(raw)
    # minimal validation
    if 'version' not in data or 'type' not in data:
        raise ValueError('invalid envelope')
    return data
