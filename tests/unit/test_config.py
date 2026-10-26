import pytest

from carl.config import ConfigError, SecretStr, load_settings
from tests.conftest import TOKEN, make_env


def test_loads_valid_environment(tmp_path):
    s = load_settings(make_env(tmp_path))
    assert s.guild_id == 1000
    assert s.household_role_id == 2000
    assert s.admin_role_id == 3000
    assert s.default_timezone == "America/Chicago"
    assert s.default_currency == "USD"
    assert s.date_order == "MDY"
    assert s.db_path == tmp_path / "carl.db"
    assert s.healthcheck_url is None


@pytest.mark.parametrize(
    "missing", ["DISCORD_TOKEN", "CARL_GUILD_ID", "CARL_HOUSEHOLD_ROLE_ID", "CARL_DEFAULT_TIMEZONE"]
)
def test_missing_required_variable_names_it(tmp_path, missing):
    env = make_env(tmp_path)
    del env[missing]
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


def test_blank_required_variable_is_missing(tmp_path):
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        load_settings(make_env(tmp_path, DISCORD_TOKEN="   "))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CARL_GUILD_ID", "abc"),
        ("CARL_HOUSEHOLD_ROLE_ID", "-5"),
        ("CARL_ADMIN_ROLE_ID", "x1"),
        ("CARL_DEFAULT_TIMEZONE", "Mars/Olympus"),
        ("CARL_DEFAULT_CURRENCY", "DOLLAR"),
        ("CARL_DATE_ORDER", "YMD"),
        ("CARL_BACKUP_TIME", "25:00"),
        ("CARL_LOG_LEVEL", "LOUD"),
        ("CARL_ENV", "staging"),
    ],
)
def test_invalid_values_name_the_variable(tmp_path, name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings(make_env(tmp_path, **{name: value}))


def test_admin_role_optional(tmp_path):
    env = make_env(tmp_path)
    del env["CARL_ADMIN_ROLE_ID"]
    assert load_settings(env).admin_role_id is None


def test_secret_never_appears_in_repr_or_str(tmp_path):
    s = load_settings(make_env(tmp_path, CARL_HEALTHCHECK_URL="https://hc-ping.com/secret-uuid"))
    text = repr(s) + str(s.discord_token) + repr(s.healthcheck_url)
    assert TOKEN not in text
    assert "secret-uuid" not in text
    assert str(s.discord_token) == "****" + TOKEN[-4:]
    assert s.discord_token.get() == TOKEN


def test_short_secret_fully_masked():
    assert str(SecretStr("abc")) == "****"
