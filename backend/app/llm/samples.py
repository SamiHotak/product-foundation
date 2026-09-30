"""Sample texts for trying the AI features.

The UI offers them ("Use a sample text"), and the shared demo may ONLY use them: demo
visitors share one account, so a visitor's own text would be visible to the next one,
and free text from anonymous visitors would cost real money.
"""

SUMMARY_SAMPLES: tuple[str, ...] = (
    "Bäckerei Lange wants three short Instagram videos. The shoot is on 14 October at 7:00, "
    "before the shop opens. The budget of 1,890 EUR is agreed. The storyboard is due on "
    "Friday.",
)


def is_summary_sample(text: str) -> bool:
    """True if the text is one of the samples (spaces at the ends don't matter)."""
    return text.strip() in SUMMARY_SAMPLES
