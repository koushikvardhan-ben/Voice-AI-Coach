"""Stereo call recording: mu-law decode, speaker channels, timeline alignment."""
import os
import struct
import tempfile
import unittest
import wave

from app.models import Speaker
from app.services.recording import CallRecorder, _decode

SILENCE = b"\xff"   # mu-law zero
LOUD = b"\x00"      # mu-law large-magnitude sample


def _read(path):
    with wave.open(path, "rb") as w:
        return w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes(), w.readframes(w.getnframes())


class RecordingTests(unittest.TestCase):
    def test_ulaw_decode_zero_and_extreme(self):
        self.assertEqual(struct.unpack("<h", _decode(SILENCE))[0], 0)
        self.assertNotEqual(struct.unpack("<h", _decode(LOUD))[0], 0)

    def test_stereo_maps_agent_left_customer_right(self):
        rec = CallRecorder()
        rec.new_stream()
        rec.add(Speaker.AGENT, 0.0, LOUD * 160)      # 20 ms, left
        rec.add(Speaker.CUSTOMER, 0.0, SILENCE * 160)  # 20 ms, right
        self.assertTrue(rec.has_audio())
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.wav")
            rec.write_wav(path)
            chans, rate, width, _, frames = _read(path)
        self.assertEqual((chans, rate, width), (2, 8000, 2))
        left0 = struct.unpack("<h", frames[0:2])[0]
        right0 = struct.unpack("<h", frames[2:4])[0]
        self.assertNotEqual(left0, 0)   # agent audio present on the left
        self.assertEqual(right0, 0)     # customer silence on the right

    def test_no_leading_silence_when_stream_starts_late(self):
        rec = CallRecorder()
        rec.new_stream()
        rec.add(Speaker.CUSTOMER, 5000.0, LOUD * 160)  # first frame at ts=5s
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.wav")
            rec.write_wav(path)
            *_, nframes, _ = _read(path)
        self.assertEqual(nframes, 160)  # starts at 0, not 5s of silence

    def test_intra_stream_gap_is_padded(self):
        rec = CallRecorder()
        rec.new_stream()
        rec.add(Speaker.CUSTOMER, 1000.0, LOUD * 160)  # -> t=0
        rec.add(Speaker.CUSTOMER, 2000.0, LOUD * 160)  # +1000 ms -> sample 8000
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.wav")
            rec.write_wav(path)
            *_, nframes, _ = _read(path)
        self.assertGreaterEqual(nframes, 8000 + 160)

    def test_reconnect_continues_after_existing_audio(self):
        rec = CallRecorder()
        rec.new_stream()
        rec.add(Speaker.AGENT, 0.0, LOUD * 160)
        rec.new_stream()                      # media socket reconnect; clock resets to 0
        rec.add(Speaker.AGENT, 0.0, LOUD * 160)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.wav")
            rec.write_wav(path)
            *_, nframes, _ = _read(path)
        self.assertGreaterEqual(nframes, 320)  # two chunks back-to-back, not overlaid

    def test_no_audio_means_nothing_to_write(self):
        self.assertFalse(CallRecorder().has_audio())


if __name__ == "__main__":
    unittest.main()
