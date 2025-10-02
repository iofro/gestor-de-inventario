from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import utils.pdf_utils as pdf_utils


def test_draw_wrapped_text_splits_long_words(tmp_path):
    c = canvas.Canvas(str(tmp_path / "out.pdf"), pagesize=letter)
    c.setFont("Helvetica", 12)
    text = "PalabraLarguisimaQueDebeDividirse"
    final_y = pdf_utils.draw_wrapped_text(c, text, 10, 750, 100, 12)
    c.save()
    # should move at least one line_height
    assert final_y < 750


def test_draw_wrapped_text_multiple_lines(tmp_path):
    c = canvas.Canvas(str(tmp_path / "out2.pdf"), pagesize=letter)
    c.setFont("Helvetica", 10)
    text = "uno dos tres cuatro cinco seis siete ocho nueve diez"
    y = pdf_utils.draw_wrapped_text(c, text, 10, 750, 60, 10)
    c.save()
    assert y < 750


def test_draw_text_with_ellipsis_truncates(tmp_path):
    c = canvas.Canvas(str(tmp_path / "ellipsis.pdf"), pagesize=letter)
    c.setFont("Helvetica", 10)
    text = "Nombre: " + "x" * 100
    drawn = pdf_utils.draw_text_with_ellipsis(c, text, 10, 700, 80)
    c.save()
    assert drawn.endswith("...")
    assert pdf_utils.pdfmetrics.stringWidth(drawn, "Helvetica", 10) <= 80


def test_draw_text_with_ellipsis_short_text(tmp_path):
    c = canvas.Canvas(str(tmp_path / "ellipsis2.pdf"), pagesize=letter)
    c.setFont("Helvetica", 10)
    text = "Nombre: corto"
    drawn = pdf_utils.draw_text_with_ellipsis(c, text, 10, 700, 200)
    c.save()
    assert drawn == text
