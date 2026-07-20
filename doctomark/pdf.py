"""PDF converter — extracts text and embedded images via pdfminer.six.

Uses pdfminer's page-by-page API to extract both text and raster images.
"""

import io
import struct
from pathlib import Path
from typing import Optional

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTFigure, LTImage, LTTextBox
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser

from PIL import Image as PILImage

from .base import BaseConverter, ConversionResult


class PdfConverter(BaseConverter):
    """Extract text + images from PDF via pdfminer.six."""

    SUPPORTED_EXTENSIONS = (".pdf",)

    def convert(self, input_path: Path) -> ConversionResult:
        md_parts: list[str] = []

        with open(input_path, "rb") as f:
            parser = PDFParser(f)
            document = PDFDocument(parser)

            rsrcmgr = PDFResourceManager()
            laparams = LAParams()
            device = PDFPageAggregator(rsrcmgr, laparams=laparams)
            interpreter = PDFPageInterpreter(rsrcmgr, device)

            for page_num, page in enumerate(PDFPage.create_pages(document), 1):
                interpreter.process_page(page)
                layout = device.get_result()

                md_parts.append(f"\n\n<!-- Page {page_num} -->\n")

                self._process_layout(layout, md_parts)

        return ConversionResult(markdown="".join(md_parts).strip())

    def _process_layout(self, item, md_parts: list[str]) -> None:
        """Recursively walk layout tree, collecting text and images."""
        if isinstance(item, LTTextBox):
            text = item.get_text().strip()
            if text:
                md_parts.append(text + "\n\n")

        elif isinstance(item, LTImage):
            ref = self._extract_image(item)
            if ref:
                md_parts.append(f"![图片]({ref})\n\n")

        else:
            # LTFigure, LTPage, LTContainer — recurse into children
            if hasattr(item, "__iter__"):
                for child in item:
                    self._process_layout(child, md_parts)

    def _extract_image(self, image: LTImage) -> str:
        """Try to decode an LTImage stream to a usable image format and save it."""
        try:
            raw_data = image.stream.get_rawdata()
        except Exception:
            return ""

        if not raw_data:
            return ""

        # If the stream uses a filter, we may need to decode it
        # pdfminer LTImage provides rawdata after base filters are applied
        try:
            data = image.stream.get_data()
        except Exception:
            data = raw_data

        if not data:
            return ""

        # Try to determine the image format
        fmt = self._detect_pdf_image_format(data, image)

        # If it's raw pixel data, try to reconstruct using Pillow
        if fmt is None:
            data = self._reconstruct_raw_image(data, image)
            if data is None:
                return ""
            fmt = "png"
        else:
            # Already in a standard format (JPEG, PNG, etc.)
            pass

        content_type = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "tiff": "image/tiff",
        }.get(fmt, f"image/{fmt}")

        return self._save_image(data, content_type)

    @staticmethod
    def _detect_pdf_image_format(data: bytes, image: LTImage) -> Optional[str]:
        """Detect image format from magic bytes or LTImage metadata."""
        # Check magic bytes first
        if data[:4] == b"\x89PNG":
            return "png"
        if data[:2] == b"\xff\xd8":
            return "jpg"
        if data[:3] == b"GIF":
            return "gif"
        if data[:4] == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
            return "webp"
        if data[:2] in (b"BM",):
            return "bmp"
        if data[:4] in (b"II*\x00", b"MM\x00*"):
            return "tiff"

        # Check PDF stream filter — JPEG streams often use DCTDecode
        filters = []
        try:
            filters = [
                f.name if hasattr(f, "name") else str(f)
                for f in (image.stream.attrs.get("Filter", []) or [])
            ]
        except Exception:
            pass

        for f in filters:
            if "DCT" in f or "JPX" in f:
                return "jpg"
            if "Flate" in f:
                # Could be raw pixel data compressed with FlateDecode
                return None

        # Check image.colorspace for hints about raw pixel data
        return None

    @staticmethod
    def _reconstruct_raw_image(data: bytes, image: LTImage) -> Optional[bytes]:
        """Attempt to reconstruct raw pixel data into a PNG via Pillow.

        Handles common PDF-internal pixel formats: RGB, RGBA, Gray, CMYK.
        """
        width = image.srcsize[0]
        height = image.srcsize[1]
        bits = image.bits_per_component
        if not width or not height or not bits:
            return None

        try:
            color_space = image.colorspace
        except Exception:
            color_space = None

        color_space_name = getattr(color_space, "name", "") if color_space else ""
        num_components = getattr(color_space, "ncomponents", 3)

        if not color_space_name and num_components:
            # Detect by checking expected data size vs actual
            pass

        try:
            if bits == 1:
                # 1-bit monochrome
                mode = "1"
                expected_size = (width + 7) // 8 * height
            elif bits == 8:
                if num_components == 1 or "DeviceGray" in str(color_space_name):
                    mode = "L"
                    expected_size = width * height
                elif num_components == 3 or "DeviceRGB" in str(color_space_name):
                    mode = "RGB"
                    expected_size = width * height * 3
                elif num_components == 4 or "DeviceCMYK" in str(color_space_name):
                    mode = "CMYK"
                    expected_size = width * height * 4
                else:
                    return None
            else:
                return None

            if len(data) < expected_size:
                # Possibly still compressed — give up
                return None

            img = PILImage.frombytes(mode, (width, height), data[:expected_size])

            # If CMYK, convert to RGB for broader compatibility
            if mode == "CMYK":
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        except Exception:
            return None
