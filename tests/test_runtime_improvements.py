import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import flet as ft
import audio_processor as audio
import lesson_pipeline as pipeline
import main


def walk(control):
    yield control
    content = getattr(control, 'content', None)
    if isinstance(content, ft.Control):
        yield from walk(content)
    for child in getattr(control, 'controls', []):
        yield from walk(child)


def button(root, label):
    return next(c for c in walk(root) if isinstance(c, ft.Container) and c.on_click and
                any(isinstance(t, ft.Text) and label in (t.value or '') for t in walk(c)))


class ModelCacheTests(unittest.TestCase):
    def setUp(self):
        for name, value in [('_MODEL_CACHE', {}), ('_MODEL_WARNINGS', {}), ('AI_AVAILABLE', True)]:
            mock = patch.object(audio, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_concurrent_calls_load_one_model(self):
        model = object()
        barrier = threading.Barrier(6)
        def load(_):
            barrier.wait(timeout=2)
            return audio.get_whisper_model('tiny', 'cpu')[0]
        with patch.object(audio, 'WhisperModel', return_value=model) as constructor:
            with ThreadPoolExecutor(max_workers=6) as executor:
                results = list(executor.map(load, range(6)))
        constructor.assert_called_once()
        self.assertTrue(all(result is model for result in results))

    def test_cuda_fallback_keeps_model_and_warning(self):
        model = object()
        with patch.object(audio, 'WhisperModel', side_effect=[RuntimeError('no GPU'), model]) as constructor:
            first = audio.get_whisper_model('tiny', 'cuda')
            self.assertEqual(audio.get_whisper_model('tiny', 'cuda'), first)
            self.assertIs(audio.get_whisper_model('tiny', 'cpu')[0], model)
        self.assertTrue(first[1])
        self.assertEqual(constructor.call_count, 2)

    def test_fallback_reuses_previously_loaded_cpu(self):
        model = object()
        audio._MODEL_CACHE[('tiny', 'cpu')] = model
        with patch.object(audio, 'WhisperModel', side_effect=RuntimeError('no GPU')) as constructor:
            self.assertIs(audio.get_whisper_model('tiny', 'cuda')[0], model)
        constructor.assert_called_once()

    def test_failed_load_can_be_retried(self):
        model = object()
        with patch.object(audio, 'WhisperModel', side_effect=[RuntimeError('download failed'), model]):
            self.assertIsNone(audio.get_whisper_model('tiny')[0])
            self.assertIs(audio.get_whisper_model('tiny')[0], model)


class PipelineTests(unittest.TestCase):
    def test_provider_timeout_is_not_mistaken_for_polling_timeout(self):
        with patch.object(pipeline, '_call_ai_raw', side_effect=TimeoutError('provider timed out')):
            with self.assertRaisesRegex(TimeoutError, 'provider timed out'):
                pipeline._call_ai('user', 'system', 'ollama', 'test', timeout=100)

    def test_cancelled_call_returns_before_provider_finishes(self):
        started, release, stop = threading.Event(), threading.Event(), threading.Event()
        def provider(*args):
            started.set()
            release.wait(timeout=3)
            return '{}'
        errors = []
        def call():
            try:
                pipeline._call_ai('user', 'system', 'ollama', 'test', stop_event=stop)
            except Exception as exc:
                errors.append(exc)
        try:
            with patch.object(pipeline, '_call_ai_raw', side_effect=provider):
                worker = threading.Thread(target=call)
                worker.start()
                self.assertTrue(started.wait(timeout=2))
                stop.set()
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.assertIsInstance(errors[0], pipeline.PipelineCancelledException)
        finally:
            release.set()

    def test_cancel_during_flashcard_fallback_is_not_swallowed(self):
        with patch.object(pipeline, '_pause'), patch.object(pipeline, '_generate_one_flashcard', side_effect=[ValueError('bad JSON'), pipeline.PipelineCancelledException('cancel')]):
            with self.assertRaises(pipeline.PipelineCancelledException):
                pipeline._generate_all_flashcards([{'word': 'hello'}], 'story', 'ollama', 'test', '', 1)

    def test_flashcard_failure_does_not_look_like_success(self):
        stop = threading.Event()
        with patch.object(pipeline, '_pause'), patch.object(pipeline, '_generate_one_flashcard', side_effect=ValueError('bad JSON')):
            with self.assertRaisesRegex(ValueError, 'hello'):
                pipeline._generate_all_flashcards([{'word': 'hello'}], 'story', 'ollama', 'test', '', 1, stop_event=stop)
        self.assertFalse(stop.is_set())

    def test_cancellation_at_last_stage_does_not_report_done(self):
        stop = threading.Event()
        events = []
        def cards(**kwargs):
            stop.set()
            return []
        with patch.object(pipeline, '_generate_one_question', return_value={'question': {}, 'updated_story': {}}), patch.object(pipeline, '_generate_challenge', return_value={}), patch.object(pipeline, '_generate_summary_story', return_value='story'), patch.object(pipeline, '_generate_all_flashcards', side_effect=cards):
            result = pipeline.run_lesson_pipeline([{'word': 'hello'}], 'story', num_questions=1, stop_event=stop, on_progress=events.append)
        self.assertFalse(result['success'])
        self.assertTrue(result['cancelled'])
        self.assertFalse(any(event['status'] == 'done' for event in events))


class PipelineViewTests(unittest.TestCase):
    def test_closing_dialog_does_not_pop_an_unrelated_notification(self):
        page = Mock()
        dialog, snackbar = ft.AlertDialog(open=True), ft.SnackBar(ft.Text('saved'), open=True)
        with patch.object(ft.Control, 'update'):
            main.safe_close_dialog(page, dialog)
        self.assertFalse(dialog.open)
        self.assertTrue(snackbar.open)
        page.pop_dialog.assert_not_called()

    def test_settings_change_mounts_a_snackbar(self):
        page = Mock()
        with patch.object(main, 'load_settings', return_value={}), patch.object(main, 'save_settings') as save, patch.object(ft.Control, 'update'):
            view = main.build_settings_screen(page)
            button(view, 'small').on_click(None)
        save.assert_called_once()
        snackbar = page.show_dialog.call_args.args[0]
        self.assertIsInstance(snackbar, ft.SnackBar)
        self.assertIn('small', snackbar.content.value)

    def test_old_worker_cannot_overwrite_new_run(self):
        page, lock = Mock(), Mock()
        generating = {'status': False}
        options = ([ft.dropdown.Option('ollama:test', 'Test')], 'ollama:test')
        with patch.object(ft.Control, 'update'), patch.object(main, 'load_settings', return_value={}), patch.object(main, 'save_settings'), patch.object(main, 'load_all_model_options', return_value=options), patch('threading.Thread') as thread:
            view = main.build_pipeline_tab_content(page, Mock(), lock, generating)
            vocab = next(c for c in walk(view) if isinstance(c, ft.TextField) and c.label.startswith('Từ vựng'))
            vocab.value = 'hello'
            start, cancel, save = button(view, 'BẮT ĐẦU'), button(view, 'HỦY'), button(view, 'LƯU BÀI HỌC')
            start.on_click(None)
            old_worker = thread.call_args.kwargs['target']
            cancel.on_click(None)
            start.on_click(None)
            new_worker = thread.call_args.kwargs['target']
            def old_result(**kwargs):
                kwargs['on_progress']({'label': 'STALE PROGRESS', 'status': 'done'})
                return {'success': True, 'questions': [], 'vocab_with_examples': []}
            with patch.object(pipeline, 'run_lesson_pipeline', side_effect=old_result):
                old_worker()
            self.assertTrue(generating['status'])
            self.assertFalse(start.visible)
            self.assertTrue(cancel.visible)
            self.assertFalse(save.visible)
            self.assertFalse(any(isinstance(c, ft.Text) and c.value == 'STALE PROGRESS' for c in walk(view)))
            with patch.object(pipeline, 'run_lesson_pipeline', side_effect=RuntimeError('provider failed')):
                new_worker()
            self.assertFalse(generating['status'])
            self.assertFalse(start.visible)
            self.assertTrue(button(view, 'LÀM LẠI TỪ ĐẦU').visible)
            self.assertFalse(save.visible)
            lock.assert_called_with(False)


if __name__ == '__main__':
    unittest.main()
