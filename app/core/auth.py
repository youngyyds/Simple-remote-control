"""Authentication helpers for the remote control protocol."""

VALID_TOKENS = {
    'secret-token-123',
}


class AuthError(Exception):
    pass


def validate_token(token: str) -> bool:
    if not token:
        return False
    return token in VALID_TOKENS


def require_token(payload: dict):
    token = payload.get('token')
    if not validate_token(token):
        raise AuthError('invalid token')
    return True
