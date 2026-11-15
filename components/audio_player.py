"""Per-page playback: audio is played on the user's client, including web."""
import threading
from pathlib import Path

import flet_audio as fa
import tts_processor


class PageAudioPlayer:
    def __init__(self, page):
        self.page = page
        # Flet requires a nonempty source when mounting an Audio service.
        self.audio = None
        self._lock = threading.Lock()
        self._request = 0
        self._on_error = None

    async def _loaded(self, event):
        try:
            await self.audio.play()
        except Exception as exc:
            if self._on_error:
                self._on_error(exc)

    async def _play(self, path, request):
        if request != self._request:
            return
        try:
            source = Path(path).read_bytes()
            if self.audio is None:
                self.audio = fa.Audio(src=source, release_mode=fa.ReleaseMode.STOP, on_loaded=self._loaded)
                self.page.services.append(self.audio)
                self.page.update()
            elif self.audio.src == source:
                await self.audio.play()
            else:
                self.audio.src = source
                self.audio.update()
        except Exception as exc:
            if self._on_error and request == self._request:
                self._on_error(exc)

    def speak(self, text, voice, rate, on_error):
        with self._lock:
            self._request += 1
            request = self._request
            self._on_error = on_error

        def ready(path):
            if request == self._request:
                self.page.run_task(self._play, path, request)

        def failed(exc):
            if request == self._request and on_error:
                on_error(exc)

        tts_processor.speak(text, voice=voice, rate=rate,
                            on_audio_ready=ready, on_error=failed)
