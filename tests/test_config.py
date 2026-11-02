from pathlib import Path

from dragonfly import __version__
from dragonfly.config import Settings


def test_version_is_set():
    assert __version__


def test_defaults_without_environment():
    settings = Settings.from_env({})
    assert settings.radar_host == "127.0.0.1"
    assert settings.radar_port == 5000
    assert settings.api_key == ""


def test_reads_prefixed_environment_variables():
    settings = Settings.from_env(
        {
            "DRAGONFLY_RADAR_HOST": "192.0.2.10",
            "DRAGONFLY_RADAR_PORT": "6000",
            "DRAGONFLY_DATA_DIR": "recordings/dragonfly",
            "DRAGONFLY_LOG_LEVEL": "debug",
        }
    )
    assert settings.radar_host == "192.0.2.10"
    assert settings.radar_port == 6000
    assert settings.data_dir == Path("recordings/dragonfly")
    assert settings.log_level == "DEBUG"


def test_api_key_is_hidden_from_repr():
    settings = Settings.from_env({"DRAGONFLY_API_KEY": "placeholder-not-a-real-key"})
    assert "placeholder-not-a-real-key" not in repr(settings)
