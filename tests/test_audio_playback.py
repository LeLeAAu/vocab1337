import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import tts_processor as tts
from components.audio_player import PageAudioPlayer


class AudioPlaybackTests(unittest.TestCase):
    def test_browser_receives_cached_audio_without_native_player(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(tts, 'CACHE_DIR', folder), patch.object(tts.threading, 'Thread') as thread, patch.object(tts, 'play_audio_file') as native:
            path = Path(tts.get_cache_path('hello', tts.DEFAULT_VOICE, tts.DEFAULT_RATE))
            path.write_bytes(b'audio' * 30)
            ready, error = Mock(), Mock()
            tts.speak('hello', on_audio_ready=ready, on_error=error)
            thread.call_args.kwargs['target']()
            ready.assert_called_once_with(str(path))
            error.assert_not_called()
            native.assert_not_called()

    def test_download_failure_reports_error_without_windows_fallback_for_web(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(tts, 'CACHE_DIR', folder), patch.object(tts, 'EDGE_TTS_AVAILABLE', False), patch.object(tts.threading, 'Thread') as thread, patch.object(tts, '_sapi_fallback') as sapi:
            ready, error = Mock(), Mock()
            tts.speak('hello', on_audio_ready=ready, on_error=error)
            thread.call_args.kwargs['target']()
            error.assert_called_once()
            ready.assert_not_called()
            sapi.assert_not_called()

    def test_old_download_cannot_replace_new_audio(self):
        page = Mock()
        player = PageAudioPlayer(page)
        with patch.object(tts, 'speak') as speak:
            player.speak('old', 'voice', '+0%', Mock())
            old = speak.call_args.kwargs
            player.speak('new', 'voice', '+0%', Mock())
            new = speak.call_args.kwargs
            old['on_audio_ready']('/old.mp3')
            old['on_error'](RuntimeError('old error'))
            page.run_task.assert_not_called()
            new['on_audio_ready']('/new.mp3')
            page.run_task.assert_called_once()

    def test_client_audio_receives_bytes_and_plays_on_loaded(self):
        page = Mock()
        player = PageAudioPlayer(page)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'clip.mp3'
            path.write_bytes(b'clip bytes')
            asyncio.run(player._play(path, 0))
            page.update.assert_called_once()
        self.assertEqual(player.audio.src, b'clip bytes')
        with patch.object(player.audio, 'play', new_callable=AsyncMock) as play:
            asyncio.run(player._loaded(None))
            play.assert_awaited_once()

    def test_repeated_clip_plays_again_without_waiting_for_another_loaded_event(self):
        page = Mock()
        player = PageAudioPlayer(page)
        player.audio = Mock(src=b'clip bytes', play=AsyncMock())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'clip.mp3'
            path.write_bytes(b'clip bytes')
            asyncio.run(player._play(path, 0))
        player.audio.play.assert_awaited_once()

    def test_native_playback_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(tts, 'CACHE_DIR', folder), patch.object(tts.threading, 'Thread') as thread, patch.object(tts, 'play_audio_file', return_value=False), patch.object(tts, '_sapi_fallback', return_value=False):
            Path(tts.get_cache_path('hello', tts.DEFAULT_VOICE, tts.DEFAULT_RATE)).write_bytes(b'audio' * 30)
            error = Mock()
            tts.speak('hello', on_error=error)
            thread.call_args.kwargs['target']()
            error.assert_called_once()


if __name__ == '__main__':
    unittest.main()
