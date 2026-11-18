ELLIPSIS = "…"


def truncate(text: str, max_length: int) -> str:
    """Cuts `text` to at most `max_length` characters, ending with an ellipsis when cut."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(ELLIPSIS)] + ELLIPSIS
