"""Regression checks that do not need a microphone, downloaded model or API key."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import flet as ft
from components.quiz_renderer import build_quiz_view
from components.flashcard import show_pronunciation_modal

import audio_processor as audio
import database
import ingestion


class LessonImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db_patch = patch.object(database, "DB_PATH", Path(self.temp.name) / "test.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_db()

    def test_invalid_json_structures_do_not_write_or_raise(self):
        for payload in (
            {"title": "Test", "vocab": None},
            {"title": "Test", "vocab": "hello"},
            {"title": "Test", "vocab": [None]},
            {"title": "Test", "vocab": ["hello"]},
            {"title": "Test", "vocab": [{"word": 123}]},
            {"title": "Test", "vocab": [{"word": "  "}]},
            {"title": 123, "vocab": []},
            {"title": "  ", "vocab": []},
            {"title": "Test", "questions": {}},
            {"title": "Test", "questions": [None]},
            {"title": "Test", "flashcards": "invalid"},
        ):
            with self.subTest(payload=payload):
                result = ingestion.load_lesson_from_dict(payload)
                self.assertFalse(result["success"])
                self.assertTrue(result["errors"])
        self.assertEqual(database.get_total_lesson_count(), 0)
        self.assertEqual(database.get_total_vocab_count(), 0)

    def test_duplicate_words_only_appear_once_in_lesson(self):
        result = ingestion.load_lesson_from_dict({
            "title": "Test", "vocab": [{"word": "Hello"}, {"word": "hello"}],
        })
        self.assertTrue(result["success"], result)
        self.assertEqual(len(json.loads(database.get_lesson_by_id(result["lesson_id"])["vocab_ids"])), 1)
        self.assertEqual(database.get_total_vocab_count(), 1)

    def test_sample_import_export(self):
        sample = Path(__file__).resolve().parents[1] / "lessons/example_lesson.json"
        result = ingestion.load_lesson_from_json(sample)
        self.assertTrue(result["success"], result)
        exported = database.export_lesson_to_dict(result["lesson_id"])
        self.assertEqual(exported["title"], "The Last Forest")
        self.assertEqual(len(exported["vocab"]), 3)


class PronunciationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.wav = Path(self.temp.name) / "recording.wav"
        self.wav.touch()

    def assertUnavailable(self, result):
        self.assertFalse(result["passed"])
        self.assertTrue(result["error"])
        self.assertEqual(result["transcribed_text"], "")
        self.assertIsNone(result["distance"])

    def test_missing_dependencies_never_pass(self):
        with patch.object(audio, "AI_AVAILABLE", False):
            self.assertUnavailable(audio.check_pronunciation(str(self.wav), "hello"))

    def test_missing_model_never_passes(self):
        with patch.object(audio, "AI_AVAILABLE", True), patch.object(audio, "get_whisper_model", return_value=(None, "")):
            self.assertUnavailable(audio.check_pronunciation(str(self.wav), "hello"))

    def test_recognizer_failure_never_passes(self):
        model = Mock()
        model.transcribe.side_effect = RuntimeError("decoder failed")
        with patch.object(audio, "AI_AVAILABLE", True), patch.object(audio, "get_whisper_model", return_value=(model, "")):
            self.assertUnavailable(audio.check_pronunciation(str(self.wav), "hello"))

    def test_silence_does_not_pass_short_words(self):
        model = Mock()
        model.transcribe.return_value = ([], None)
        with patch.object(audio, "AI_AVAILABLE", True), patch.object(audio, "get_whisper_model", return_value=(model, "")):
            self.assertFalse(audio.check_pronunciation(str(self.wav), "a")["passed"])

    def test_matching_speech_still_passes(self):
        model = Mock()
        model.transcribe.return_value = ([SimpleNamespace(text="Hello!")], None)
        with patch.object(audio, "AI_AVAILABLE", True), patch.object(audio, "get_whisper_model", return_value=(model, "")):
            result = audio.check_pronunciation(str(self.wav), "hello")
        self.assertTrue(result["passed"])
        self.assertEqual(result["distance"], 0)

    def test_recording_failure_skips_recognition(self):
        with patch.object(audio, "record_audio", side_effect=RuntimeError("No mic")), patch.object(audio, "check_pronunciation") as recognize:
            self.assertUnavailable(audio.verify_voice_pronunciation("hello"))
            recognize.assert_not_called()

    def test_temporary_recordings_are_unique_and_removed(self):
        paths = []
        def record(path, **kwargs):
            paths.append(path)
            self.assertTrue(Path(path).exists())
        with patch.object(audio, "record_audio", side_effect=record), patch.object(audio, "check_pronunciation", return_value={"passed": True}):
            audio.verify_voice_pronunciation("hello")
            audio.verify_voice_pronunciation("world")
        self.assertNotEqual(*paths)
        self.assertTrue(all(not Path(path).exists() for path in paths))

    def test_no_microphone_does_not_generate_fake_audio(self):
        with patch.object(audio, "SD_AVAILABLE", False):
            with self.assertRaises(RuntimeError):
                audio.record_audio(str(self.wav))


class SpeechQuizTests(unittest.TestCase):
    def test_flashcard_record_button_handles_unavailable_microphone(self):
        page = Mock()
        with patch.object(audio, "verify_voice_pronunciation", return_value=audio._unavailable("No mic")):
            show_pronunciation_modal(page, "hello")
        dialog = page.show_dialog.call_args.args[0]
        record = dialog.content.controls[-1].controls[-1]
        with patch.object(ft.Control, "update"), patch("threading.Thread") as thread:
            record.on_click(None)
            with patch.object(audio, "verify_voice_pronunciation", return_value=audio._unavailable("No mic")):
                thread.call_args.kwargs["target"]()
        self.assertFalse(record.disabled)
        self.assertEqual(dialog.content.controls[1].content.controls[1].value, "No mic")

    def test_recording_and_failed_retry_cannot_submit_old_success(self):
        answer = Mock()
        root = build_quiz_view({"type": "speech_verification", "target_text": "hello"}, on_answer=answer)

        def descendants(control):
            yield control
            content = getattr(control, "content", None)
            if isinstance(content, ft.Control):
                yield from descendants(content)
            for child in getattr(control, "controls", []):
                yield from descendants(child)

        buttons = [c for c in descendants(root) if isinstance(c, ft.Container) and c.on_click]
        def button_with(text):
            return next(c for c in buttons if any(
                isinstance(t, ft.Text) and text in (t.value or "") for t in descendants(c)
            ))
        record = button_with("BẮT ĐẦU NÓI")
        submit = button_with("NỘP BÀI")
        with patch.object(ft.Control, "update"), patch.object(ft.Control, "page", new_callable=PropertyMock, return_value=Mock()), patch("threading.Thread") as thread:
            record.on_click(None)
            submit.on_click(None)
            answer.assert_not_called()
            with patch.object(audio, "verify_voice_pronunciation", return_value={"passed": True, "transcribed_text": "hello"}):
                thread.call_args.kwargs["target"]()
            # A new recording invalidates the previous successful result immediately.
            record.on_click(None)
            submit.on_click(None)
            answer.assert_not_called()
            with patch.object(audio, "verify_voice_pronunciation", return_value=audio._unavailable("No mic")):
                thread.call_args.kwargs["target"]()
            submit.on_click(None)
            answer.assert_not_called()
            # The learner can retry and submit a real result afterwards.
            record.on_click(None)
            with patch.object(audio, "verify_voice_pronunciation", return_value={"passed": True, "transcribed_text": "hello"}):
                thread.call_args.kwargs["target"]()
            submit.on_click(None)
            self.assertTrue(answer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
