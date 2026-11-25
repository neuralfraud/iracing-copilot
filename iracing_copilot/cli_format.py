"""Shared formatting for a Diagnosis - a full text block (terminal/overlay)
and a short spoken version (text-to-speech), used across all the demo
scripts so they stay in sync.
"""


def format_diagnosis(result):
    lines = [result.symptom_summary]
    for ev in result.cited_evidence:
        lines.append(f"  evidence - {ev.source}: {ev.observation}")
    if not result.recommendations:
        lines.append("  no confident recommendation")
    for rec in result.recommendations:
        path = " > ".join(rec.setup_path)
        lines.append(
            f"  -> {path}: {rec.current_value} -> {rec.recommended_value} "
            f"[{rec.confidence}] - {rec.reasoning}"
        )
    for caveat in result.caveats:
        lines.append(f"  caveat: {caveat}")
    return "\n".join(lines)


def print_diagnosis(result):
    print("\n" + format_diagnosis(result))


def speakable_diagnosis(result):
    """A short, natural-language version for TTS - skips key paths/caveats,
    which read poorly out loud, and just names the last path segment as the
    thing to adjust."""
    parts = [result.symptom_summary]

    if not result.recommendations:
        parts.append("No confident setup recommendation this time.")
    else:
        for rec in result.recommendations:
            component = rec.setup_path[-1] if rec.setup_path else "the setup"
            current = rec.current_value or "its current value"
            parts.append(
                f"Try {component}: {current} to {rec.recommended_value}, "
                f"{rec.confidence} confidence."
            )

    return " ".join(parts)
