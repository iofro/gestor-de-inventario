"""Example script to generate a Code128 barcode PDF using ReportLab.

This script demonstrates how to include ReportLab barcode submodules when
building with PyInstaller. It works as a regular Python script and also
when frozen into an executable, provided the PyInstaller spec includes the
hidden imports shown in ``barcode_example.spec``.
"""

from reportlab.graphics.barcode import code128  # Import for Code128 barcode
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def make_barcode_pdf(text: str, output: str = "barcode_example.pdf") -> None:
    """Generate a PDF containing a Code128 barcode.

    Parameters
    ----------
    text:
        The text to encode inside the barcode.
    output:
        Name of the PDF file to generate.
    """
    # Create a PDF canvas to draw on
    c = canvas.Canvas(output)

    # Create the barcode object. barWidth and barHeight are optional but
    # allow custom sizing.
    barcode = code128.Code128(text, barWidth=0.5 * mm, barHeight=20 * mm)

    # Draw the barcode onto the canvas at the specified coordinates.
    barcode.drawOn(c, 10 * mm, 250 * mm)

    # Finalize the PDF file.
    c.save()
    print(f"PDF generated: {output}")


if __name__ == "__main__":
    # Example usage: encode an invoice number
    make_barcode_pdf("INV-0001")
