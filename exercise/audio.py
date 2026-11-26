import base64
import binascii
from dataclasses import dataclass
import io
from pathlib import Path
import re
import wave
import zlib


REFERENCE = re.compile(r'[A-Za-z0-9_-]+\.wav\.z64')
MAX_WAV_BYTES = 600_000


@dataclass(frozen=True)
class AudioSegment:
    reference: str
    wav: bytes
    sample_rate: int
    channels: int
    sample_width: int
    frame_count: int

    def to_dict(self):
        return {
            'reference': self.reference,
            'wav_base64': base64.b64encode(self.wav).decode('ascii'),
            'sample_rate': self.sample_rate,
            'channels': self.channels,
            'sample_width': self.sample_width,
            'frame_count': self.frame_count,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data['reference'], base64.b64decode(data['wav_base64'], validate=True),
            data['sample_rate'], data['channels'], data['sample_width'],
            data['frame_count'],
        )


def read_audio_segment(directory: Path, reference: str) -> AudioSegment:
    if not isinstance(reference, str) or not REFERENCE.fullmatch(reference):
        raise ValueError('invalid_audio_reference')
    directory = directory.resolve()
    try:
        source = (directory / reference).resolve()
        if source.parent != directory:
            raise ValueError('invalid_audio_reference')
        with source.open('rb') as stream:
            encoded = stream.read(MAX_WAV_BYTES * 2 + 1)
        if len(encoded) > MAX_WAV_BYTES * 2:
            raise ValueError('invalid_audio')
        compressed = base64.b64decode(encoded.strip(), validate=True)
        decoder = zlib.decompressobj()
        data = decoder.decompress(compressed, MAX_WAV_BYTES + 1)
        if len(data) > MAX_WAV_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError('invalid_audio')
        with wave.open(io.BytesIO(data), 'rb') as audio:
            rate = audio.getframerate()
            width = audio.getsampwidth()
            channels = audio.getnchannels()
            frames = audio.getnframes()
            if not (8000 <= rate <= 48000 and 0 < frames <= 3 * rate):
                raise ValueError('invalid_audio')
            if width not in (1, 2) or channels not in (1, 2):
                raise ValueError('invalid_audio')
            if len(audio.readframes(frames)) != frames * channels * width:
                raise ValueError('incomplete_audio')
    except (OSError, EOFError, RuntimeError, wave.Error, zlib.error, binascii.Error) as error:
        raise ValueError('invalid_audio') from error
    return AudioSegment(reference, data, rate, channels, width, frames)
