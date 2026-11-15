"""
story_taxonomy.py — Vocab1337
Quản lý Taxonomy thiết kế cốt truyện, Story State (Story Bible),
Cognitive Skills và các bộ Presets định sẵn cho AI Generator.
Dựa trên phân tích kiến trúc trong question_and_response.txt.
"""

import json
from typing import Any

# ── 16 DANH MỤC STORY TAXONOMY & THUỘC TÍNH ──────────────────────────────────

NARRATIVE_STRUCTURES = [
    "linear",
    "nonlinear",
    "fragmented",
    "parallel_timelines",
    "convergent_timelines",
    "circular",
    "episodic",
    "frame_narrative",
]

GENRES = [
    "science_fiction",
    "fantasy",
    "horror",
    "mystery",
    "thriller",
    "dystopian",
    "post_apocalyptic",
    "SCP_like",
    "literary",
    "historical_fiction",
]

TECH_AESTHETICS = [
    "none",
    "steampunk",
    "clockpunk",
    "dieselpunk",
    "cyberpunk",
    "biopunk",
    "arcanepunk",
    "magitech",
    "solarpunk",
    "atompunk",
    "aetherpunk",
]

WORLD_TYPES = [
    "real_world",
    "alternate_history",
    "secondary_world",
    "post_apocalypse",
    "simulation",
    "multiverse",
    "cosmic",
    "metaphysical",
]

POINTS_OF_VIEW = [
    "third_person_limited",
    "third_person_omniscient",
    "first_person",
    "second_person",
    "multiple_pov",
    "unreliable_narrator",
    "documentary",
    "epistolary",
    "mixed",
]

INFORMATION_STRUCTURES = [
    "direct_exposition",
    "investigation",
    "documents",
    "logs",
    "reports",
    "classified_memo",
    "satellite_feed",
    "field_log",
    "dialogue",
    "unreliable_records",
    "gradual_revelation",
    "archive",
    "interrogation",
]

TIME_STRUCTURES = [
    "chronological",
    "flashbacks",
    "flashforwards",
    "parallel_time",
    "recursive_time",
    "fragmented_time",
    "time_loop",
]

TONES = [
    "clinical",
    "academic",
    "ominous",
    "melancholic",
    "philosophical",
    "mysterious",
    "tense",
    "tragic",
    "neutral",
    "absurd",
]

PLOT_STYLES = [
    "investigation",
    "survival",
    "political_conflict",
    "exploration",
    "mystery_revelation",
    "escalation",
    "character_drama",
    "philosophical_discovery",
]

REALITY_RULES = [
    "scientifically_grounded",
    "speculative",
    "realistic",
    "surreal",
    "metaphysical",
    "pataphysical",
    "dreamlike",
]

DIFFICULTIES = ["easy", "medium", "hard", "very_hard"]

NARRATIVE_DENSITIES = ["low", "medium", "high"]

CHARACTER_DYNAMICS = [
    "investigator_subject",
    "mentor_student",
    "ally_rival",
    "creator_creation",
    "human_system",
    "observer_anomaly",
]

CONFLICT_SCALES = [
    "personal",
    "local",
    "institutional",
    "national",
    "global",
    "cosmic",
]

REVEAL_STYLES = [
    "gradual_reveal",
    "false_lead",
    "recontextualization",
    "unreliable_evidence",
    "hidden_causality",
]

COGNITIVE_SKILLS = [
    "contextual_inference",
    "incorrect_usage_detection",
    "error_identification",
    "causal_reasoning",
    "semantic_distinction",
    "literal_context",
    "context_inconsistency",
    "implication",
    "comparison",
    "hidden_relationship",
    "classification",
    "perspective_shift",
]


# ── BỘ PRESETS CỐT TRUYỆN MẪU (PRESET ARCHETYPES) ────────────────────────────

TAXONOMY_PRESETS = {
    "SCP / Anomaly Archive": {
        "genre": "SCP_like",
        "narrative_structure": "fragmented",
        "technology_aesthetic": "biopunk",
        "world_type": "alternate_history",
        "point_of_view": "documentary",
        "information_structure": "classified_memo",
        "time_structure": "fragmented_time",
        "tone": "clinical",
        "plot_style": "investigation",
        "reality_rules": "speculative",
        "difficulty": "hard",
        "narrative_density": "high",
    },
    "Cyberpunk Corporate Intrigue": {
        "genre": "cyberpunk",
        "narrative_structure": "nonlinear",
        "technology_aesthetic": "cyberpunk",
        "world_type": "secondary_world",
        "point_of_view": "third_person_limited",
        "information_structure": "logs",
        "time_structure": "chronological",
        "tone": "tense",
        "plot_style": "investigation",
        "reality_rules": "scientifically_grounded",
        "difficulty": "medium",
        "narrative_density": "medium",
    },
    "Steampunk Subterranean Expedition": {
        "genre": "science_fiction",
        "narrative_structure": "linear",
        "technology_aesthetic": "steampunk",
        "world_type": "secondary_world",
        "point_of_view": "first_person",
        "information_structure": "field_log",
        "time_structure": "chronological",
        "tone": "mysterious",
        "plot_style": "exploration",
        "reality_rules": "speculative",
        "difficulty": "medium",
        "narrative_density": "medium",
    },
    "Arcanepunk Magitech Crisis": {
        "genre": "fantasy",
        "narrative_structure": "frame_narrative",
        "technology_aesthetic": "arcanepunk",
        "world_type": "secondary_world",
        "point_of_view": "multiple_pov",
        "information_structure": "reports",
        "time_structure": "parallel_time",
        "tone": "academic",
        "plot_style": "escalation",
        "reality_rules": "metaphysical",
        "difficulty": "hard",
        "narrative_density": "high",
    },
    "Post-Apocalyptic Ecological Rebirth": {
        "genre": "post_apocalyptic",
        "narrative_structure": "episodic",
        "technology_aesthetic": "solarpunk",
        "world_type": "post_apocalypse",
        "point_of_view": "third_person_limited",
        "information_structure": "gradual_revelation",
        "time_structure": "flashbacks",
        "tone": "melancholic",
        "plot_style": "survival",
        "reality_rules": "speculative",
        "difficulty": "hard",
        "narrative_density": "high",
    },
    "Hard Sci-Fi Cosmic Signal": {
        "genre": "science_fiction",
        "narrative_structure": "linear",
        "technology_aesthetic": "none",
        "world_type": "real_world",
        "point_of_view": "third_person_omniscient",
        "information_structure": "satellite_feed",
        "time_structure": "chronological",
        "tone": "academic",
        "plot_style": "philosophical_discovery",
        "reality_rules": "scientifically_grounded",
        "difficulty": "very_hard",
        "narrative_density": "high",
    },
}


# ── STORY STATE / STORY BIBLE STRUCTURE ──────────────────────────────────────

def initial_story_state(seed_text: str = "") -> dict:
    """Khởi tạo Story State rỗng hoặc có mô tả hạt giống ban đầu."""
    return {
        "story_summary": seed_text or "",
        "characters": [],
        "locations": [],
        "factions": [],
        "objects_and_systems": [],
        "established_events": [],
        "causal_relationships": [],
        "revealed_information": [],
        "unresolved_mysteries": [],
        "current_conflicts": [],
        "future_threads": [],
        "timeline": [],
        "world_rules": [],
        "vocabulary_usage": {},
        "continuity_notes": []
    }


def validate_or_repair_story_state(state: Any, previous_state: dict = None) -> dict:
    """
    Đảm bảo state luôn là dict có đầy đủ các trường Story Bible chuẩn.
    Nếu AI phản hồi thiếu hoặc trả về rỗng, tự động bảo toàn và kế thừa dữ liệu từ previous_state,
    ngăn ngừa tình trạng reset Story State về 0 nhân vật / 0 sự kiện giữa các bước.
    """
    prev = previous_state if isinstance(previous_state, dict) else {}

    if not isinstance(state, dict):
        if isinstance(state, str) and state.strip():
            base = initial_story_state()
            base["story_summary"] = state.strip()
            return base
        if prev:
            return validate_or_repair_story_state(dict(prev), previous_state=None)
        return initial_story_state()

    template = initial_story_state()
    for key, default_val in template.items():
        if key not in state or state[key] is None:
            # Kế thừa từ previous_state nếu có, ngược lại lấy default_val
            if key in prev and prev[key]:
                state[key] = prev[key]
            else:
                state[key] = default_val
        elif isinstance(default_val, list):
            if not isinstance(state[key], list):
                state[key] = [state[key]] if state[key] else []
            # Nếu mảng mới bị rỗng nhưng previous_state có dữ liệu -> bảo tồn từ previous_state
            prev_items = prev.get(key, []) if isinstance(prev.get(key), list) else []
            if not state[key] and prev_items:
                state[key] = list(prev_items)
            elif prev_items:
                # Merge không trùng lặp các phần tử đã có
                merged = list(prev_items)
                for item in state[key]:
                    item_str = str(item).strip()
                    if item_str and not any(str(p).strip() == item_str for p in merged):
                        merged.append(item)
                state[key] = merged
        elif isinstance(default_val, dict):
            if not isinstance(state[key], dict):
                state[key] = {}
            prev_dict = prev.get(key, {}) if isinstance(prev.get(key), dict) else {}
            if prev_dict:
                merged_dict = dict(prev_dict)
                merged_dict.update(state[key])
                state[key] = merged_dict
        elif isinstance(default_val, str):
            if not isinstance(state[key], str):
                state[key] = str(state[key])
            if not state[key].strip() and prev.get(key) and isinstance(prev[key], str):
                state[key] = prev[key].strip()

    return state


def format_story_taxonomy(props: dict) -> str:
    """Định dạng thuộc tính taxonomy thành chuỗi YAML-like cho Prompt."""
    default = TAXONOMY_PRESETS["SCP / Anomaly Archive"]
    cfg = {**default, **(props or {})}

    lines = []
    if cfg.get("story_style"):
        lines.append(f"story_style: {cfg.get('story_style')}")

    lines.extend([
        f"narrative_structure: {cfg.get('narrative_structure', 'linear')}",
        f"genre: {cfg.get('genre', 'science_fiction')}",
        f"technology_aesthetic: {cfg.get('technology_aesthetic', 'none')}",
        f"world_type: {cfg.get('world_type', 'real_world')}",
        f"point_of_view: {cfg.get('point_of_view', 'third_person_limited')}",
        f"information_structure: {cfg.get('information_structure', 'investigation')}",
        f"time_structure: {cfg.get('time_structure', 'chronological')}",
        f"tone: {cfg.get('tone', 'clinical')}",
        f"plot_style: {cfg.get('plot_style', 'investigation')}",
        f"reality_rules: {cfg.get('reality_rules', 'speculative')}",
        f"difficulty: {cfg.get('difficulty', 'hard')}",
        f"narrative_density: {cfg.get('narrative_density', 'high')}",
        "continuity_priority: strict",
    ])
    return "\n".join(lines)
