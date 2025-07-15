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
