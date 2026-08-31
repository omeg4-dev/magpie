from pathlib import Path

from magpie.config import Config, load


def test_without_a_config_file_the_defaults_stand(tmp_path):
    config = load(tmp_path / "nothing.toml")
    assert config == Config()


def test_a_key_in_the_file_wins(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('store = "/somewhere/else"\n')

    assert load(path).store == Path("/somewhere/else")


def test_a_tilde_means_home(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('screenshots = "~/Pictures"\n')

    assert load(path).screenshots == Path.home() / "Pictures"


def test_a_key_that_is_not_a_setting_is_ignored(tmp_path):
    # Better a stale key than a viewer that refuses to open over a typo.
    path = tmp_path / "config.toml"
    path.write_text('store = "/a"\nnonsense = 3\n')

    assert load(path).store == Path("/a")


def test_a_broken_file_falls_back_to_the_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("this is not toml [[[")

    assert load(path) == Config()
