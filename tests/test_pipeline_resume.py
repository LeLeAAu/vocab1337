from contextlib import ExitStack
from copy import deepcopy
import threading
import unittest
from unittest.mock import Mock, patch

import flet as ft
import lesson_pipeline as pipeline
import main
from test_runtime_improvements import walk, button


class ResumeTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.question = stack.enter_context(patch.object(pipeline, '_generate_one_question', side_effect=self.make_question))
        self.challenge = stack.enter_context(patch.object(pipeline, '_generate_challenge', return_value={'challenge': True}))
        self.summary = stack.enter_context(patch.object(pipeline, '_generate_summary_story', return_value='Completed story'))
        self.cards = stack.enter_context(patch.object(pipeline, '_generate_all_flashcards', side_effect=self.make_cards))
        self.inputs = dict(vocab_list=[{'word': 'hello'}, {'word': 'world'}], seed_story='Original story', num_questions=3)

    @staticmethod
    def make_question(**kwargs):
        n = kwargs['question_number']
        return {'question': {'number': n}, 'updated_story': {'story_summary': f'state {n}'}}

    @staticmethod
    def make_cards(**kwargs):
        saved = deepcopy(kwargs.get('completed_cards') or {})
        for i, vocab in enumerate(kwargs['vocab_list']):
            if i not in saved:
                saved[i] = dict(vocab, example_en='Example')
                kwargs['on_card_done'](i, saved[i])
        return [saved[i] for i in range(len(kwargs['vocab_list']))]

    def test_question_retry_uses_completed_story_without_mutating_snapshot(self):
        failed = False
        def question(**kwargs):
            nonlocal failed
            if kwargs['question_number'] == 2 and not failed:
                failed = True
                kwargs['updated_story_state']['poison'] = True
                raise ValueError('invalid JSON')
            self.assertNotIn('poison', kwargs['updated_story_state'])
            return self.make_question(**kwargs)
        self.question.side_effect = question
        first = pipeline.run_lesson_pipeline(**self.inputs)
        self.assertFalse(first['success'])
        self.assertEqual(first['failed_step'], 2)
        self.assertEqual(len(first['checkpoint']['questions']), 1)
        snapshot = deepcopy(first['checkpoint'])
        resumed = pipeline.run_lesson_pipeline(**self.inputs, resume_from=snapshot)
        self.assertTrue(resumed['success'], resumed)
        self.assertEqual([c.kwargs['question_number'] for c in self.question.call_args_list], [1, 2, 2, 3])
        self.assertEqual(len(resumed['questions']), 4)
        self.assertEqual(snapshot, first['checkpoint'])

    def test_challenge_retry_does_not_regenerate_questions(self):
        self.challenge.side_effect = [TimeoutError('provider timed out'), {'challenge': True}]
        first = pipeline.run_lesson_pipeline(**self.inputs)
        self.assertEqual(first['failed_step'], 4)
        self.assertTrue(pipeline.run_lesson_pipeline(**self.inputs, resume_from=first['checkpoint'])['success'])
        self.assertEqual(self.question.call_count, 3)
        self.assertEqual(self.challenge.call_count, 2)
        self.assertEqual(self.summary.call_count, 1)

    def test_summary_retry_keeps_challenge_without_duplicates(self):
        self.summary.side_effect = [ValueError('bad summary'), 'Completed story']
        first = pipeline.run_lesson_pipeline(**self.inputs)
        self.assertEqual(first['failed_step'], 5)
        second = pipeline.run_lesson_pipeline(**self.inputs, resume_from=first['checkpoint'])
        self.assertTrue(second['success'])
        self.assertEqual(self.question.call_count, 3)
        self.assertEqual(self.challenge.call_count, 1)
        self.assertEqual(len(second['questions']), 4)

    def test_partial_flashcards_survive_retry(self):
        def fail(**kwargs):
            kwargs['on_card_done'](0, {'word': 'hello', 'example_en': 'Kept example'})
            raise ValueError('world failed')
        self.cards.side_effect = fail
        first = pipeline.run_lesson_pipeline(**self.inputs)
        self.assertEqual(first['failed_step'], 6)
        self.assertEqual(first['summary_story'], 'Completed story')
        self.cards.side_effect = self.make_cards
        second = pipeline.run_lesson_pipeline(**self.inputs, resume_from=first['checkpoint'])
        self.assertTrue(second['success'])
        self.assertEqual(second['vocab_with_examples'][0]['example_en'], 'Kept example')
        self.assertEqual(self.cards.call_args.kwargs['completed_cards'], first['checkpoint']['flashcards'])
        self.assertEqual(self.summary.call_count, 1)
        self.assertEqual(self.question.call_count, 3)

    def test_repeated_failure_remains_at_same_step(self):
        def question(**kwargs):
            if kwargs['question_number'] == 2:
                raise ValueError('still unavailable')
            return self.make_question(**kwargs)
        self.question.side_effect = question
        first = pipeline.run_lesson_pipeline(**self.inputs)
        second = pipeline.run_lesson_pipeline(**self.inputs, resume_from=first['checkpoint'])
        self.assertFalse(second['success'])
        self.assertEqual(second['checkpoint'], first['checkpoint'])
        self.assertEqual([c.kwargs['question_number'] for c in self.question.call_args_list], [1, 2, 2])

    def test_changed_content_cannot_be_mixed_with_saved_work(self):
        self.challenge.side_effect = ValueError('fail')
        saved = pipeline.run_lesson_pipeline(**self.inputs)['checkpoint']
        calls = self.question.call_count
        for changes in [dict(seed_story='Changed'), dict(num_questions=4), dict(user_notes='Changed'), dict(vocab_list=[{'word': 'different'}]), dict(taxonomy_settings={'genre': 'different'})]:
            with self.subTest(changes=changes):
                result = pipeline.run_lesson_pipeline(**(self.inputs | changes), resume_from=saved)
                self.assertFalse(result['success'])
                self.assertIsNone(result['checkpoint'])
        self.assertEqual(self.question.call_count, calls)

    def test_connection_can_change_and_checkpoint_contains_no_key(self):
        self.challenge.side_effect = [ValueError('fail'), {}]
        first = pipeline.run_lesson_pipeline(**self.inputs, api_key='SECRET_FOR_TEST', model='old')
        self.assertNotIn('SECRET_FOR_TEST', repr(first['checkpoint']))
        second = pipeline.run_lesson_pipeline(**self.inputs, resume_from=first['checkpoint'], api_key='NEW_KEY', model='new', provider='openai')
        self.assertTrue(second['success'])
        self.assertEqual(self.challenge.call_args.kwargs['model'], 'new')
        self.assertEqual(self.challenge.call_args.kwargs['api_key'], 'NEW_KEY')

    def test_restart_without_checkpoint_regenerates_from_first_question(self):
        self.challenge.side_effect = [ValueError('fail'), {}]
        pipeline.run_lesson_pipeline(**self.inputs)
        result = pipeline.run_lesson_pipeline(**self.inputs)
        self.assertTrue(result['success'])
        self.assertEqual([c.kwargs['question_number'] for c in self.question.call_args_list], [1, 2, 3, 1, 2, 3])

    def test_cancelled_inflight_question_is_not_committed(self):
        stop = threading.Event()
        def question(**kwargs):
            if kwargs['question_number'] == 2:
                stop.set()
            return self.make_question(**kwargs)
        self.question.side_effect = question
        first = pipeline.run_lesson_pipeline(**self.inputs, stop_event=stop)
        self.assertTrue(first['cancelled'])
        self.assertEqual(len(first['checkpoint']['questions']), 1)
        self.question.side_effect = self.make_question
        self.assertTrue(pipeline.run_lesson_pipeline(**self.inputs, resume_from=first['checkpoint'])['success'])

    def test_callback_cannot_corrupt_internal_work(self):
        def observer(snapshot):
            snapshot['questions'].clear()
            snapshot['story_state']['poison'] = True
        result = pipeline.run_lesson_pipeline(**self.inputs, on_checkpoint=observer)
        self.assertTrue(result['success'])
        self.assertEqual(len(result['questions']), 4)
        self.assertNotIn('poison', result['story_state'])

    def test_invalid_flashcard_is_not_added_to_saved_work(self):
        def bad_card(**kwargs):
            kwargs['on_card_done'](0, None)
        self.cards.side_effect = bad_card
        first = pipeline.run_lesson_pipeline(**self.inputs)
        self.assertFalse(first['success'])
        self.assertEqual(first['checkpoint']['flashcards'], {})
        self.cards.side_effect = self.make_cards
        self.assertTrue(pipeline.run_lesson_pipeline(**self.inputs, resume_from=first['checkpoint'])['success'])

    def test_malformed_snapshot_is_rejected_before_provider_calls(self):
        for snapshot in ({'version': 1}, ['invalid']):
            with self.subTest(snapshot=snapshot):
                result = pipeline.run_lesson_pipeline(**self.inputs, resume_from=snapshot)
                self.assertFalse(result['success'])
                self.assertIsNone(result['checkpoint'])
        self.question.assert_not_called()


class FlashcardResumeTests(unittest.TestCase):
    def test_actual_pool_only_generates_missing_cards(self):
        original = {0: {'word': 'hello', 'example_en': 'Already generated'}}
        done = Mock()
        with patch.object(pipeline, '_generate_one_flashcard', return_value={'word': 'world'}) as create:
            result = pipeline._generate_all_flashcards([{'word': 'hello'}, {'word': 'world'}], 'story', 'ollama', 'test', '', 1, completed_cards=original, on_card_done=done)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(create.call_args.args[0]['word'], 'world')
        self.assertEqual(result[0], original[0])
        done.assert_called_once_with(1, {'word': 'world'})

    def test_completed_pool_does_not_call_provider(self):
        with patch.object(pipeline, '_generate_one_flashcard') as create:
            result = pipeline._generate_all_flashcards([{'word': 'hello'}], 'story', 'ollama', 'test', '', 1, completed_cards={0: {'word': 'hello'}})
        create.assert_not_called()
        self.assertEqual(result, [{'word': 'hello'}])


class ResumeViewTests(unittest.TestCase):
    make_question = staticmethod(ResumeTests.make_question)
    make_cards = staticmethod(ResumeTests.make_cards)

    def setUp(self):
        ResumeTests.setUp(self)
        self.enterContext(patch.object(ft.Control, 'update'))
        self.enterContext(patch.object(main, 'load_settings', return_value={}))
        self.enterContext(patch.object(main, 'save_settings'))
        self.enterContext(patch.object(main, 'load_all_model_options', return_value=([ft.dropdown.Option('ollama:test', 'Test')], 'ollama:test')))
        self.thread = self.enterContext(patch('threading.Thread'))
        self.page, self.on_success = Mock(), Mock()
        self.view = main.build_pipeline_tab_content(self.page, self.on_success)
        fields = [c for c in walk(self.view) if isinstance(c, ft.TextField)]
        self.vocab = next(c for c in fields if c.label.startswith('Từ vựng'))
        self.count = next(c for c in fields if c.label.startswith('Số câu hỏi'))
        self.story = next(c for c in fields if 'Cốt truyện' in c.label or 'Gợi ý' in c.label)
        self.vocab.value, self.count.value, self.story.value = 'hello, world', '3', 'Original story'
        self.start, self.retry = button(self.view, 'BẮT ĐẦU'), button(self.view, 'THỬ LẠI BƯỚC BỊ LỖI')
        self.restart, self.save = button(self.view, 'LÀM LẠI TỪ ĐẦU'), button(self.view, 'LƯU BÀI HỌC')
        self.failed_once = False
        def question(**kwargs):
            if kwargs['question_number'] == 2 and not self.failed_once:
                self.failed_once = True
                raise ValueError('Simulated failure')
            return self.make_question(**kwargs)
        self.question.side_effect = question

    def execute(self, button):
        button.on_click(None)
        self.thread.call_args.kwargs['target']()

    def test_retry_button_preserves_content_and_accepts_new_model(self):
        self.execute(self.start)
        self.assertTrue(self.retry.visible)
        self.assertFalse(self.retry.disabled)
        self.assertTrue(self.restart.visible)
        self.assertFalse(self.save.visible)
        self.vocab.value, self.count.value, self.story.value = 'different', '1', 'Changed story'
        dropdown = next(c for c in walk(self.view) if isinstance(c, ft.Dropdown) and c.value == 'ollama:test')
        dropdown.value = 'ollama:replacement'
        self.execute(self.retry)
        self.assertEqual([c.kwargs['question_number'] for c in self.question.call_args_list], [1, 2, 2, 3])
        last = self.question.call_args.kwargs
        self.assertEqual(last['total_questions'], 3)
        self.assertEqual(last['vocab_list'], self.inputs['vocab_list'])
        self.assertEqual(last['model'], 'replacement')
        self.assertTrue(self.save.visible)
        self.assertFalse(self.retry.visible)
        with patch('ingestion.load_lesson_from_dict', return_value={'success': True}) as store:
            self.save.on_click(None)
        self.assertEqual(store.call_args.args[0]['title'], 'Original story')
        self.on_success.assert_called_once()

    def test_restart_button_uses_current_content_and_drops_old_steps(self):
        self.execute(self.start)
        self.vocab.value, self.count.value, self.story.value = 'different', '1', 'Changed story'
        self.execute(self.restart)
        self.assertEqual([c.kwargs['question_number'] for c in self.question.call_args_list], [1, 2, 1])
        self.assertEqual(self.question.call_args.kwargs['vocab_list'], [{'word': 'different'}])
        self.assertTrue(self.save.visible)

    def test_double_click_retry_does_not_start_two_workers(self):
        self.execute(self.start)
        self.retry.on_click(None)
        calls = self.thread.call_count
        self.retry.on_click(None)
        self.assertEqual(self.thread.call_count, calls)


if __name__ == '__main__':
    unittest.main()
