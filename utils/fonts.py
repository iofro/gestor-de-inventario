from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

FONT_NORMAL = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def register_fonts():
    """Register custom fonts if available.

    If Arial TTF files are present in common system locations, they will be
    registered and used. Otherwise the built-in Helvetica fonts are kept.
    """
    global FONT_NORMAL, FONT_BOLD

    # Potential locations for Arial fonts on Debian-based systems
    candidates = [
        ("/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"),
        ("/usr/share/fonts/truetype/msttcorefonts/arial.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/arialbd.ttf"),
        ("/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"),
    ]

    for normal_path, bold_path in candidates:
        if os.path.exists(normal_path) and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont("Arial", normal_path))
                pdfmetrics.registerFont(TTFont("Arial-Bold", bold_path))
                FONT_NORMAL = "Arial"
                FONT_BOLD = "Arial-Bold"
                break
            except Exception:
                pass


# Register on import so all modules reuse the same fonts
register_fonts()
