"""Shared text-normalization helpers for Edge-TTS word-boundary alignment."""

from __future__ import annotations

import unicodedata
from typing import Any


def is_word_boundary_separator(character: str) -> bool:
    """Return whether a character is omitted from Edge WordBoundary text coverage."""
    return character.isspace() or unicodedata.category(character).startswith("P")


def normalize_word_boundary_coverage_text(text: str) -> str:
    """Remove whitespace and Unicode punctuation, preserving lexical characters and symbols."""
    return "".join(
        character
        for character in str(text)
        if not is_word_boundary_separator(character)
    )


def restore_word_boundary_source_separators(
    boundaries: list[dict[str, Any]],
    source_text: str,
) -> list[dict[str, Any]]:
    """Restore authored punctuation/spacing into boundary text without changing its timing."""
    restored = [dict(boundary) for boundary in boundaries]
    if not restored:
        return restored

    cores: list[str] = []
    locations: list[tuple[int, int]] = []
    for boundary_index, boundary in enumerate(restored):
        core_characters: list[str] = []
        for character in str(boundary.get("text") or ""):
            if is_word_boundary_separator(character):
                continue
            locations.append((boundary_index, len(core_characters)))
            core_characters.append(character)
        cores.append("".join(core_characters))

    normalized_boundary_text = "".join(cores)
    normalized_source_text = normalize_word_boundary_coverage_text(source_text)
    if not normalized_boundary_text or normalized_boundary_text != normalized_source_text:
        return restored

    insertions: dict[tuple[int, int], list[str]] = {}
    prefix: list[str] = []
    previous_location: tuple[int, int] | None = None
    lexical_index = 0

    for character in source_text:
        if is_word_boundary_separator(character):
            if previous_location is None:
                prefix.append(character)
            else:
                key = (previous_location[0], previous_location[1] + 1)
                insertions.setdefault(key, []).append(character)
            continue

        if lexical_index >= len(locations):
            return restored
        boundary_index, character_index = locations[lexical_index]
        if cores[boundary_index][character_index] != character:
            return restored
        previous_location = (boundary_index, character_index)
        lexical_index += 1

    if lexical_index != len(locations):
        return restored

    first_nonempty_boundary = next(
        (index for index, core in enumerate(cores) if core),
        None,
    )
    for boundary_index, core in enumerate(cores):
        characters: list[str] = []
        if boundary_index == first_nonempty_boundary:
            characters.extend(prefix)
        for character_index, character in enumerate(core):
            characters.append(character)
            characters.extend(insertions.get((boundary_index, character_index + 1), []))
        restored[boundary_index]["text"] = "".join(characters)
    return restored
