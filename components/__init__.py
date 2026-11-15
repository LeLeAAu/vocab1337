# components/__init__.py — Vocab1337
# Export các component chính để main.py có thể import gọn hơn.

from .flashcard    import build_flashcard_view
from .reading      import build_reading_view
from .quiz_renderer import build_quiz_view

__all__ = ["build_flashcard_view", "build_reading_view", "build_quiz_view"]
