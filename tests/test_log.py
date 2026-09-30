import logging

from cuecal.log import KeyValueFormatter


def _format(message: str) -> str:
    record = logging.LogRecord("cuecal.t", logging.INFO, __file__, 1, message, None, None)
    return KeyValueFormatter().format(record)


def test_message_with_quotes_and_newlines_stays_one_line():
    line = _format('said "hi"\nbye')
    assert "\n" not in line
    assert "msg='said \"hi\"\\nbye'" in line


def test_plain_message():
    assert "msg='hello'" in _format("hello")
