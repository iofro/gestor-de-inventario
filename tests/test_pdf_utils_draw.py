from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import utils.pdf_utils as pdf_utils


def test_draw_wrapped_text_splits_long_words(temp_pdf):
    pdf_path = temp_pdf("out.pdf", b"")
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.setFont("Helvetica", 12)
    text = "PalabraLarguisimaQueDebeDividirse"
    final_y = pdf_utils.draw_wrapped_text(c, text, 10, 750, 100, 12)
    c.save()
    # should move at least one line_height
    assert final_y < 750


def test_draw_wrapped_text_multiple_lines(temp_pdf):
    pdf_path = temp_pdf("out2.pdf", b"")
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.setFont("Helvetica", 10)
    text = "uno dos tres cuatro cinco seis siete ocho nueve diez"
    y = pdf_utils.draw_wrapped_text(c, text, 10, 750, 60, 10)
    c.save()
    assert y < 750
