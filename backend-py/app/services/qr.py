"""QR codes for the doctor link.

The caregiver shows the QR on the patient's phone; the doctor scans it and the export
opens in their browser. The image is generated server-side so the frontend does not
need a QR library, and so the encoded URL is always the one the server issued.
"""

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def render_qr_png(url: str, box_size: int = 8) -> bytes:
    """Return a PNG of the given URL. Medium error correction tolerates a phone screen."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_qr_svg(url: str, box_size: int = 8) -> str:
    """SVG variant, for printing or embedding without raster blur."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    factory = qrcode.image.svg.SvgPathImage
    image = qr.make_image(image_factory=factory)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")
