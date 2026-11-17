import base64

import pytest
from taskbot.config import ConfigError, Settings
from taskbot.gcp import read_secret

NAME = "projects/demo-project/secrets/discord-token/versions/latest"


class FakeResponse:
    def __init__(self, status: int, payload: str = "", body: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = body

    def json(self):
        data = base64.b64encode(self._payload.encode()).decode()
        return {"name": NAME, "payload": {"data": data}}


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.urls: list[str] = []

    def get(self, url, timeout=None):
        assert timeout is not None  # never hang start-up forever
        self.urls.append(url)
        return self.response


def test_reads_and_strips_the_secret():
    session = FakeSession(FakeResponse(200, "tok-abc\n"))
    assert read_secret(NAME, session) == "tok-abc"
    assert session.urls == [f"https://secretmanager.googleapis.com/v1/{NAME}:access"]


@pytest.mark.parametrize(
    "name",
    [
        "discord-token",
        "projects/p/secrets/s",
        "projects/p/secrets/s/versions/latest/../../other",
        "https://evil.example/projects/p/secrets/s/versions/1",
        "projects/p/secrets/s/versions/1?x=y",
    ],
)
def test_rejects_names_that_are_not_a_secret_version(name):
    session = FakeSession(FakeResponse(200, "x"))
    with pytest.raises(ConfigError, match="versions/latest"):
        read_secret(name, session)
    assert session.urls == []


def test_error_does_not_echo_the_response_body():
    session = FakeSession(FakeResponse(403, body="leaky-detail"))
    with pytest.raises(ConfigError) as err:
        read_secret(NAME, session)
    assert "403" in str(err.value)
    assert "leaky-detail" not in str(err.value)


def test_empty_secret_is_refused():
    with pytest.raises(ConfigError, match="empty"):
        read_secret(NAME, FakeSession(FakeResponse(200, "  \n")))


def test_secret_name_is_enough_without_a_token_or_key_file():
    s = Settings.from_env(
        {
            "TASKBOT_DISCORD_TOKEN_SECRET": NAME,
            "TASKBOT_SHEET_ID": "abc123",
            "TASKBOT_CHANNEL_ID": "99",
        }
    )
    s.validate()  # Google sign-in comes from the VM, so no credentials setting is needed
    assert NAME in repr(s)  # the name isn't sensitive; the token itself never is shown
