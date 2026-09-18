import io
import wave
from decimal import Decimal

import pytest
from modurouter.errors import AppError
from modurouter.speech import transcription_cost, validate_audio


def wav(seconds, channels=1):
    data = io.BytesIO()
    with wave.open(data, 'wb') as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b'\0\0' * int(seconds * 16000) * channels)
    return data.getvalue()


def test_short_pcm_speech_is_accepted():
    assert validate_audio(wav(1)) == 1


@pytest.mark.parametrize('data', [b'invalid', wav(.1), wav(601), wav(1, 2)])
def test_invalid_or_unbounded_speech_is_rejected(data):
    with pytest.raises(AppError):
        validate_audio(data)


def test_unknown_usage_does_not_settle_as_free():
    assert transcription_cost({}) is None
    assert transcription_cost({'input_token_details': {'audio_tokens': True, 'text_tokens': 0}, 'output_tokens': 1}) is None
    assert transcription_cost({'input_token_details': {'audio_tokens': 100, 'text_tokens': 0}, 'output_tokens': 10}) == Decimal('0.000175')
