import base64
from io import BytesIO

import qrcode


def qr_code_png_base64(data: str) -> str:
    """Render `data` as a QR code PNG and return it as a base64 data-URI string,
    ready to drop straight into an <img src="..."> on the admin website or
    into an Android ImageView/Compose Image via BitmapFactory."""

    img = qrcode.make(data)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
