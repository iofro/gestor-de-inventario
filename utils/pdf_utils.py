from reportlab.pdfbase import pdfmetrics


def draw_wrapped_text(c, text, x, y, max_width, line_height):
    """Draw text at ``x,y`` wrapping lines so they don't exceed ``max_width``.

    Returns the y position for the next line after drawing.
    """
    fontname = c._fontname
    fontsize = c._fontsize
    words = text.split()
    line = ""
    lines = []

    def _split_long_word(word):
        parts = []
        segment = ""
        for ch in word:
            if pdfmetrics.stringWidth(segment + ch, fontname, fontsize) <= max_width:
                segment += ch
            else:
                if segment:
                    parts.append(segment)
                segment = ch
        if segment:
            parts.append(segment)
        return parts

    for word in words:
        segments = [word]
        if pdfmetrics.stringWidth(word, fontname, fontsize) > max_width:
            segments = _split_long_word(word)
        for seg in segments:
            candidate = seg if not line else f"{line} {seg}"
            if pdfmetrics.stringWidth(candidate, fontname, fontsize) <= max_width:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = seg
        if pdfmetrics.stringWidth(line, fontname, fontsize) > max_width:
            lines.append(line)
            line = ""
    if line:
        lines.append(line)

    for ln in lines:
        c.drawString(x, y, ln)
        y -= line_height
    return y


def ellipsize_text(text, fontname, fontsize, max_width):
    """Return ``text`` truncated with an ellipsis so it fits ``max_width``."""

    text = "" if text is None else str(text)

    if max_width is None:
        return text

    if max_width <= 0:
        return ""

    text_width = pdfmetrics.stringWidth(text, fontname, fontsize)
    if text_width <= max_width:
        return text

    ellipsis = "..."
    ellipsis_width = pdfmetrics.stringWidth(ellipsis, fontname, fontsize)
    if ellipsis_width > max_width:
        return ""

    # Binary search the longest prefix that fits with ellipsis appended
    low = 0
    high = len(text)
    best = ellipsis
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid] + ellipsis
        candidate_width = pdfmetrics.stringWidth(candidate, fontname, fontsize)
        if candidate_width <= max_width:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1

    return best


def draw_text_with_ellipsis(c, text, x, y, max_width):
    """Draw ``text`` ensuring it fits within ``max_width`` using an ellipsis."""

    fontname = c._fontname
    fontsize = c._fontsize
    truncated = ellipsize_text(text, fontname, fontsize, max_width)
    c.drawString(x, y, truncated)
    return truncated
