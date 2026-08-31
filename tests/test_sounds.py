"""The two little sounds.

Nothing here plays anything — the test asserts on the command that would be
run, because a test that makes a noise is a test nobody runs twice.
"""

import wave

import pytest

from magpie import sounds


def test_both_sounds_ship_with_the_program():
    for name in ("open", "copy"):
        assert sounds.file(name).exists(), f"{name}.wav is missing"


def test_they_are_short_enough_to_be_a_cue_rather_than_a_jingle():
    for name in ("open", "copy"):
        with wave.open(str(sounds.file(name))) as wav:
            seconds = wav.getnframes() / wav.getframerate()
            assert 0.02 < seconds < 0.35, f"{name} is {seconds:.2f}s"


def test_playing_hands_the_file_to_the_player():
    calls = []
    sounds.play("copy", player="pw-play", run=calls.append)
    assert calls and calls[0][0] == "pw-play"
    assert calls[0][-1].endswith("copy.wav")


def test_a_machine_with_no_player_stays_quiet_rather_than_crashing():
    calls = []
    sounds.play("copy", player=None, run=calls.append)
    assert calls == []


def test_a_player_that_fails_is_not_worth_an_exception():
    def boom(_cmd):
        raise OSError("no such device")

    sounds.play("open", player="pw-play", run=boom)  # must not raise


def test_a_name_that_is_not_a_sound_is_ignored():
    calls = []
    sounds.play("nonsense", player="pw-play", run=calls.append)
    assert calls == []


def test_it_finds_a_player_that_is_actually_installed():
    found = sounds.find_player()
    assert found is None or found in sounds.PLAYERS


def test_players_are_reaped_rather_than_left_as_zombies():
    # Spawned and never waited for, a player stays in the process table as a
    # defunct child — one per copy, for as long as the viewer is running.
    sounds._children.clear()
    sounds._spawn(["true"])
    assert len(sounds._children) == 1
    sounds._children[0].wait()
    sounds._spawn(["true"])
    assert len(sounds._children) == 1, "the finished one should have been let go"
    sounds._children[0].wait()
    sounds._reap()
    assert sounds._children == []
