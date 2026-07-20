"""DOCX converter — extracts text and embedded images via mammoth."""

import html
from pathlib import Path

import mammoth
import markdownify

from .base import BaseConverter, ConversionResult


class DocxConverter(BaseConverter):
    SUPPORTED_EXTENSIONS = (".docx",)

    def convert(self, input_path: Path) -> ConversionResult:
        # mammoth expects a file path (str) or file-like object with seek()
        # Pass the string path directly
        result = mammoth.convert_to_html(
            str(input_path),
            convert_image=mammoth.images.img_element(self._handle_image),
        )
        html_content = result.value

        # Warn about mammoth messages
        if result.messages:
            for msg in result.messages:
                if msg.type == "warning":
                    print(f"  [mammoth] {msg.message}")

        # Convert HTML to markdown
        md = _HtmlToMdConverter().convert(html_content)

        return ConversionResult(markdown=md.strip())

    def _handle_image(self, image):
        """Mammoth image callback: read image data, save, return src dict."""
        with image.open() as img_file:
            data = img_file.read()

        rel_path = self._save_image(data, getattr(image, "content_type", ""))
        if rel_path:
            return {"src": rel_path}
        return {"src": ""}


class _HtmlToMdConverter(markdownify.MarkdownConverter):
    """Thin wrapper around markdownify for consistent options."""

    def __init__(self):
        super().__init__(heading_style=markdownify.ATX, bullets="-")

    def convert(self, html_content: str) -> str:
        # Unescape HTML entities first
        text = html.unescape(html_content)
        return super().convert(text)

    def convert_img(self, el, text, convert_as_inline=False, **kwargs):
        alt = el.attrs.get("alt", "") or ""
        src = el.attrs.get("src", "") or ""
        if not src:
            return alt
        title = el.attrs.get("title", "") or ""
        title_part = f' "{title}"' if title else ""
        return f"![{alt}]({src}{title_part})"
