"""XLSX / XLS converter — extracts tables and embedded images."""

import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd

from .base import BaseConverter, ConversionResult


class XlsxConverter(BaseConverter):
    """Converts XLSX files: tables via pandas, images from zip's xl/media/."""

    SUPPORTED_EXTENSIONS = (".xlsx",)

    def convert(self, input_path: Path) -> ConversionResult:
        md_parts: list[str] = []

        # 1. Extract sheet data via pandas
        sheets = pd.read_excel(str(input_path), sheet_name=None, engine="openpyxl")
        for sheet_name, df in sheets.items():
            md_parts.append(f"## {sheet_name}\n")
            if df.empty:
                md_parts.append("（空表）\n\n")
            else:
                md_parts.append(_df_to_markdown_table(df))
                md_parts.append("\n")

        # 2. Extract embedded images from zip
        image_refs: list[str] = []
        try:
            with zipfile.ZipFile(input_path, "r") as zf:
                media_names = [
                    n for n in zf.namelist()
                    if n.startswith("xl/media/") and not n.endswith("/")
                ]
                for name in sorted(media_names):
                    data = zf.read(name)
                    # Guess content type from extension
                    ext = Path(name).suffix
                    content_type_map = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".bmp": "image/bmp",
                        ".webp": "image/webp",
                        ".tiff": "image/tiff",
                        ".svg": "image/svg+xml",
                    }
                    ct = content_type_map.get(ext.lower(), f"image/{ext.lstrip('.')}")
                    rel_path = self._save_image(data, ct)
                    if rel_path:
                        image_refs.append(f"![{Path(name).name}]({rel_path})")
        except Exception:
            pass

        if image_refs:
            md_parts.append("## 图片\n\n")
            md_parts.extend(f"{ref}\n\n" for ref in image_refs)

        return ConversionResult(markdown="".join(md_parts).strip())


class XlsConverter(BaseConverter):
    """Converts legacy XLS files — tables via pandas, images not supported."""

    SUPPORTED_EXTENSIONS = (".xls",)

    def convert(self, input_path: Path) -> ConversionResult:
        md_parts: list[str] = []

        sheets = pd.read_excel(str(input_path), sheet_name=None, engine="xlrd")
        for sheet_name, df in sheets.items():
            md_parts.append(f"## {sheet_name}\n")
            if df.empty:
                md_parts.append("（空表）\n\n")
            else:
                md_parts.append(_df_to_markdown_table(df))
                md_parts.append("\n")

        # Note: image extraction from legacy .xls (OLE2) is complex
        md_parts.append("\n> ⚠️ 旧版 .xls 格式不支持图片提取。\n")

        return ConversionResult(markdown="".join(md_parts).strip())


def _df_to_markdown_table(df: pd.DataFrame) -> str:
    """Convert a pandas DataFrame to a GitHub-flavored markdown table."""
    # Replace None/NaN with empty string
    safe_df = df.fillna("")

    lines: list[str] = []
    cols = [str(c) for c in safe_df.columns]

    # Header
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")

    # Rows
    for _, row in safe_df.iterrows():
        cells = [str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"
