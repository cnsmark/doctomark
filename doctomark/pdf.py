"""PDF converter — extracts text, tables, and embedded images.

Uses pdfplumber for table detection and pdfminer.six for text/image extraction.
"""

import io
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pdfplumber
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import (
    LAParams,
    LTFigure,
    LTImage,
    LTTextBox,
    LTTextLine,
    LTAnno,
)
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from PIL import Image as PILImage

from .base import BaseConverter, ConversionResult


@dataclass
class _PageElement:
    """A page element with vertical position for sorting."""

    y0: float
    content: str


class PdfConverter(BaseConverter):
    """Extract text + images + tables from PDF."""

    SUPPORTED_EXTENSIONS = (".pdf",)

    # Margin (in points) to expand table bbox for excluding text
    TABLE_BBOX_MARGIN = 6.0

    def convert(self, input_path: Path) -> ConversionResult:
        md_parts: list[str] = []

        pdf = pdfplumber.open(str(input_path))

        with open(input_path, "rb") as f:
            parser = PDFParser(f)
            document = PDFDocument(parser)
            rsrcmgr = PDFResourceManager()
            laparams = LAParams()
            device = PDFPageAggregator(rsrcmgr, laparams=laparams)
            interpreter = PDFPageInterpreter(rsrcmgr, device)

            for page_num, page_data in enumerate(
                PDFPage.create_pages(document), 1
            ):
                interpreter.process_page(page_data)
                layout = device.get_result()
                plumber_page = pdf.pages[page_num - 1]

                md_parts.append(f"\n\n<!-- Page {page_num} -->\n")

                # Page height for coord conversion (pdfplumber → pdfminer)
                page_h = plumber_page.height
                elements = self._collect_page_elements(layout, plumber_page, page_h)
                for elem in elements:
                    md_parts.append(elem.content + "\n\n")

        pdf.close()
        return ConversionResult(markdown="".join(md_parts).strip())

    # ------------------------------------------------------------------
    #  Page element collection
    # ------------------------------------------------------------------

    def _collect_page_elements(
        self, root_item, plumber_page, page_height: float
    ) -> list[_PageElement]:
        elements: list[_PageElement] = []

        # 1. Convert pdfplumber table bboxes (top-origin) to pdfminer coords (bottom-origin)
        m = self.TABLE_BBOX_MARGIN
        table_bboxes: list[tuple[float, float, float, float]] = []
        for tbl in plumber_page.find_tables():
            px0, ptop, px1, pbottom = tbl.bbox  # pdfplumber: (x0, top, x1, bottom)
            # Convert to pdfminer: (x0, page_h - bottom, x1, page_h - top)
            x0 = px0 - m
            y0 = page_height - pbottom - m
            x1 = px1 + m
            y1 = page_height - ptop + m
            table_bboxes.append((x0, y0, x1, y1))

        # 2. Collect text and images from non-table areas
        self._walk_layout(root_item, elements, table_bboxes)

        # 3. Extract cleaned tables from pdfplumber
        for tbl in plumber_page.find_tables():
            md_table = self._extract_clean_table_md(tbl)
            if md_table:
                # Use pdfminer y for sorting: page_h - top
                y0 = page_height - tbl.bbox[1]
                elements.append(_PageElement(y0=y0, content=md_table))

        # 4. Sort by vertical position (pdfminer coords, higher y = earlier on page)
        elements.sort(key=lambda e: e.y0, reverse=True)

        return elements

    def _walk_layout(
        self,
        item,
        elements: list[_PageElement],
        table_bboxes: list[tuple[float, float, float, float]],
    ) -> None:
        if isinstance(item, (LTTextBox, LTTextLine)):
            if hasattr(item, "bbox") and self._inside_any_table(
                item.bbox, table_bboxes
            ):
                return
            text = item.get_text().strip()
            if text:
                y0 = item.bbox[3] if hasattr(item, "bbox") else 0
                elements.append(_PageElement(y0=y0, content=text))

        elif isinstance(item, LTImage):
            ref = self._extract_image(item)
            if ref:
                y0 = item.bbox[3] if hasattr(item, "bbox") else 0
                elements.append(_PageElement(y0=y0, content=f"![图片]({ref})"))

        elif isinstance(item, LTAnno):
            return

        else:
            if hasattr(item, "__iter__"):
                for child in item:
                    self._walk_layout(child, elements, table_bboxes)

    @staticmethod
    def _inside_any_table(text_bbox, table_bboxes) -> bool:
        tx0, ty0, tx1, ty1 = text_bbox
        for bx0, by0, bx1, by1 in table_bboxes:
            if tx0 < bx1 and tx1 > bx0 and ty0 < by1 and ty1 > by0:
                return True
        return False

    # ------------------------------------------------------------------
    #  Table extraction — cleaning pipeline
    # ------------------------------------------------------------------

    def _extract_clean_table_md(self, tbl) -> str:
        """Extract table from pdfplumber, clean, and return markdown."""
        raw = tbl.extract()
        if not raw or not raw[0]:
            return ""

        # Step 1: Normalize column count
        rows = self._normalize_rows(raw)

        # Step 2: Drop fully-empty columns
        rows = self._drop_empty_columns(rows)

        # Step 3: Merge sparse columns into neighbours
        rows = self._merge_sparse_columns(rows)

        # Step 4: Drop fully-empty rows
        rows = [r for r in rows if any(c for c in r)]

        if not rows:
            return ""

        # Step 5: Merge complementary rows (split header rows)
        rows = self._merge_complementary_rows(rows)

        return self._table_to_markdown(rows)

    @staticmethod
    def _normalize_rows(raw: list) -> list[list[str]]:
        max_cols = max(len(row) for row in raw)
        result = []
        for row in raw:
            r = list(row)
            while len(r) < max_cols:
                r.append("")
            result.append([c.strip() if c else "" for c in r])
        return result

    @staticmethod
    def _drop_empty_columns(rows: list[list[str]]) -> list[list[str]]:
        ncols = len(rows[0])
        keep = [
            c
            for c in range(ncols)
            if any(row[c] for row in rows)
        ]
        return [[row[c] for c in keep] for row in rows]

    @staticmethod
    def _merge_sparse_columns(
        rows: list[list[str]], sparse_threshold: float = 0.7
    ) -> list[list[str]]:
        """Merge columns where most cells are empty into the nearest non-empty column.

        A column is "sparse" if >sparse_threshold of its cells are empty.
        Sparse columns are merged leftward into the previous non-sparse column.
        """
        ncols = len(rows[0])
        nrows = len(rows)

        # Identify sparse columns
        sparse = []
        for c in range(ncols):
            empty_count = sum(1 for row in rows if not row[c])
            sparse.append(empty_count / nrows > sparse_threshold)

        # Build merge map: each column → which output column it feeds into
        # Column 0 always stays; sparse columns merge leftward into
        # the nearest non-sparse column.
        merge_map: list[int] = []
        output_col = 1  # col 0 always gets slot 0
        merge_map.append(0)

        for c in range(1, ncols):
            if sparse[c] and not sparse[c - 1]:
                # Merge into previous non-sparse column
                merge_map.append(output_col - 1)
            else:
                merge_map.append(output_col)
                output_col += 1

        # Apply merge
        new_ncols = output_col
        new_rows: list[list[str]] = []
        for row in rows:
            new_row = ["" for _ in range(new_ncols)]
            for c, val in enumerate(row):
                target = merge_map[c]
                if val:
                    if new_row[target]:
                        new_row[target] += " " + val
                    else:
                        new_row[target] = val
            new_rows.append(new_row)

        return new_rows

    @staticmethod
    def _merge_complementary_rows(
        rows: list[list[str]], min_fill: float = 0.3
    ) -> list[list[str]]:
        """Merge adjacent rows whose non-empty columns are complementary.

        Two rows are complementary if:
        - Both rows have fewer than `min_fill` fraction non-empty cells
        - Their non-empty column sets are disjoint
        - Neither row looks like a complete data row (>50% filled)

        This handles pdfplumber splitting a logical row across two physical rows.
        """
        if len(rows) < 2:
            return rows

        merged: list[list[str]] = []
        skip_next = False

        for i, row in enumerate(rows):
            if skip_next:
                skip_next = False
                continue

            if i + 1 >= len(rows):
                merged.append(row)
                continue

            next_row = rows[i + 1]
            ncols = len(row)

            this_cols = {j for j in range(ncols) if row[j]}
            next_cols = {j for j in range(ncols) if next_row[j]}

            this_fill = len(this_cols) / ncols if ncols else 0
            next_fill = len(next_cols) / ncols if ncols else 0

            # Only merge if both are sparse AND disjoint
            if (
                this_fill < min_fill
                and next_fill < min_fill
                and not (this_cols & next_cols)
                and this_fill < 0.5  # neither is a complete row
                and next_fill < 0.5
            ):
                new_row = [
                    row[j] or next_row[j] for j in range(ncols)
                ]
                merged.append(new_row)
                skip_next = True
            else:
                merged.append(row)

        return merged

    @staticmethod
    def _table_to_markdown(rows: list[list[str]]) -> str:
        if not rows:
            return ""

        ncols = len(rows[0])
        lines: list[str] = []

        # Header
        lines.append("| " + " | ".join(rows[0]) + " |")
        # Separator
        lines.append("|" + "|".join([" --- " for _ in range(ncols)]) + "|")
        # Data
        for row in rows[1:]:
            cells = list(row)
            while len(cells) < ncols:
                cells.append("")
            lines.append("| " + " | ".join(cells[:ncols]) + " |")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    #  Image extraction (unchanged)
    # ------------------------------------------------------------------

    def _extract_image(self, image: LTImage) -> str:
        try:
            raw_data = image.stream.get_rawdata()
        except Exception:
            return ""
        if not raw_data:
            return ""
        try:
            data = image.stream.get_data()
        except Exception:
            data = raw_data
        if not data:
            return ""

        fmt = self._detect_pdf_image_format(data, image)
        if fmt is None:
            data = self._reconstruct_raw_image(data, image)
            if data is None:
                return ""
            fmt = "png"

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
                return None
        return None

    @staticmethod
    def _reconstruct_raw_image(data: bytes, image: LTImage) -> Optional[bytes]:
        width = image.srcsize[0]
        height = image.srcsize[1]
        bits = image.bits_per_component
        if not width or not height or not bits:
            return None

        try:
            color_space = image.colorspace
        except Exception:
            color_space = None

        color_space_name = (
            getattr(color_space, "name", "") if color_space else ""
        )
        num_components = getattr(color_space, "ncomponents", 3)

        try:
            if bits == 1:
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
                return None

            img = PILImage.frombytes(mode, (width, height), data[:expected_size])
            if mode == "CMYK":
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None
