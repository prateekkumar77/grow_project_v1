import json

from auth import authenticate, parse_users


def test_parse_users_empty_string_returns_empty():
    assert parse_users("") == {}
    assert parse_users("   ") == {}


def test_parse_users_invalid_json_returns_empty():
    assert parse_users("not json") == {}


def test_parse_users_non_list_returns_empty():
    assert parse_users(json.dumps({"username": "admin"})) == {}


def test_parse_users_valid_entries():
    raw = json.dumps(
        [
            {"username": "admin", "password": "adminpass", "role": "admin"},
            {"username": "viewer", "password": "viewerpass", "role": "viewer"},
        ]
    )
    users = parse_users(raw)

    assert set(users.keys()) == {"admin", "viewer"}
    assert users["admin"].role == "admin"
    assert users["viewer"].role == "viewer"


def test_parse_users_skips_invalid_role():
    raw = json.dumps([{"username": "root", "password": "x", "role": "superuser"}])
    assert parse_users(raw) == {}


def test_parse_users_skips_missing_fields():
    raw = json.dumps([{"username": "admin", "role": "admin"}])
    assert parse_users(raw) == {}


def test_parse_users_skips_duplicate_username():
    raw = json.dumps(
        [
            {"username": "admin", "password": "first", "role": "admin"},
            {"username": "admin", "password": "second", "role": "viewer"},
        ]
    )
    users = parse_users(raw)

    assert len(users) == 1
    assert users["admin"].password == "first"


def test_authenticate_correct_credentials():
    users = parse_users(json.dumps([{"username": "admin", "password": "secret", "role": "admin"}]))

    user = authenticate(users, "admin", "secret")

    assert user is not None
    assert user.role == "admin"


def test_authenticate_wrong_password():
    users = parse_users(json.dumps([{"username": "admin", "password": "secret", "role": "admin"}]))

    assert authenticate(users, "admin", "wrong") is None


def test_authenticate_unknown_username():
    users = parse_users(json.dumps([{"username": "admin", "password": "secret", "role": "admin"}]))

    assert authenticate(users, "nobody", "secret") is None


def test_authenticate_empty_users():
    assert authenticate({}, "admin", "secret") is None
