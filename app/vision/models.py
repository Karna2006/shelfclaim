"""Order vision models for controlled transient-failure fallback.

Input: the configured primary vision model. Output: a stable de-duplicated
model chain. Keeps the default fallback order shared by frame and sweep tools.
"""

VISION_MODEL_FALLBACKS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
)


def vision_model_chain(primary: str) -> tuple[str, ...]:
    """Try the configured model first, followed by the approved fallback order."""
    return tuple(dict.fromkeys((primary, *VISION_MODEL_FALLBACKS)))
