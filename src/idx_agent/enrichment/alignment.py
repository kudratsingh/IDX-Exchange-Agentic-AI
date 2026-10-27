"""Conservative original-offset alignment for the existing normalizer."""

from __future__ import annotations

from dataclasses import dataclass

from idx_agent.enrichment.normalize import _COMPILED, normalize_remarks


@dataclass(frozen=True)
class NormalizationAlignment:
    """Normalized text and source spans; keep in memory and never log remarks."""

    text: str
    origins: tuple[tuple[int, int], ...]
    applied_rules: tuple[str, ...]

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a full normalized span back; reject partial abbreviation expansions."""
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(self.text)
        ):
            raise ValueError("invalid normalized span")
        selected = self.origins[start:end]
        source_start = min(left for left, _ in selected)
        source_end = max(right for _, right in selected)
        # A replacement's characters all refer to its whole source interval.
        # If any matching character is outside the requested span, the caller
        # selected only part of an expansion and cannot cite it precisely.
        for i, (left, right) in enumerate(self.origins):
            if (i < start or i >= end) and left < source_end and right > source_start:
                raise ValueError("normalized span cuts through a source expansion")
        return source_start, source_end


def normalize_with_alignment(text: str) -> NormalizationAlignment:
    """Apply the existing bounded normalizer and retain conservative offsets.

    Replacement characters map to the complete source match, not an invented
    character-level alignment. No raw text, spans, or identifiers are logged.
    """
    reference = normalize_remarks(text)
    current = text
    origins = [(i, i + 1) for i in range(len(text))]
    for _name, pattern, replacement in _COMPILED:
        pieces = []
        mapped = []
        cursor = 0
        for match in pattern.finditer(current):
            pieces.append(current[cursor : match.start()])
            mapped.extend(origins[cursor : match.start()])
            expanded = match.expand(replacement)
            source = origins[match.start() : match.end()]
            left = min(item[0] for item in source)
            right = max(item[1] for item in source)
            pieces.append(expanded)
            mapped.extend([(left, right)] * len(expanded))
            cursor = match.end()
        pieces.append(current[cursor:])
        mapped.extend(origins[cursor:])
        current, origins = "".join(pieces), mapped
    if current != reference.text or len(origins) != len(current):
        raise RuntimeError("normalizer alignment does not match output")
    return NormalizationAlignment(current, tuple(origins), reference.applied_rules)
