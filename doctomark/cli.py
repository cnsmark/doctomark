"""CLI entry point — orchestrates format selection, conversion, and output."""

import argparse
import sys
from pathlib import Path

from .base import ConversionResult
from .docx import DocxConverter
from .pptx import PptxConverter
from .xlsx import XlsxConverter, XlsConverter
from .pdf import PdfConverter


# Registry: extension → converter class
_CONVERTERS = {
    ".docx": DocxConverter,
    ".pptx": PptxConverter,
    ".xlsx": XlsxConverter,
    ".xls": XlsConverter,
    ".pdf": PdfConverter,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doctomark",
        description="将 Office / PDF 文件转换为 Markdown，并提取嵌入图片到 assets 目录。",
        epilog="示例: doctomark report.docx  →  生成 report.md + report_assets/",
    )
    parser.add_argument(
        "input",
        type=str,
        nargs="?",
        default=None,
        help="要转换的输入文件路径（.docx .pptx .xlsx .xls .pdf）",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="输出 Markdown 文件路径（默认 {input_stem}.md）",
    )
    parser.add_argument(
        "-d", "--output-dir",
        type=str,
        default=None,
        help="输出目录（默认与输入文件同目录）",
    )
    parser.add_argument(
        "--assets-dir",
        type=str,
        default=None,
        help="图片资源目录名（默认 {input_stem}_assets）",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="跳过图片提取，仅输出纯文本 Markdown",
    )
    parser.add_argument(
        "--supported",
        action="store_true",
        help="列出支持的文件格式后退出",
    )

    args = parser.parse_args(argv)

    if args.supported:
        print("支持的文件格式：")
        for ext, cls in _CONVERTERS.items():
            print(f"  {ext}  ({cls.__name__})")
        return 0

    if not args.input:
        parser.error("必须指定输入文件")

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"错误: 文件不存在 — {input_path}", file=sys.stderr)
        return 1

    ext = input_path.suffix.lower()
    converter_cls = _CONVERTERS.get(ext)
    if converter_cls is None:
        print(
            f"错误: 不支持的文件格式 '{ext}'。\n"
            f"支持: {', '.join(_CONVERTERS.keys())}",
            file=sys.stderr,
        )
        return 2

    # Determine output paths
    output_dir = Path(args.output_dir) if args.output_dir else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = input_path.stem
    assets_dir = (
        Path(args.assets_dir)
        if args.assets_dir
        else output_dir / f"{stem}_assets"
    )
    md_output = (
        Path(args.output)
        if args.output
        else output_dir / f"{stem}.md"
    )

    # Convert
    converter = converter_cls(assets_dir=assets_dir)
    print(f"📄 转换中: {input_path.name} → {md_output.name}")

    try:
        result = converter.convert(input_path)
    except Exception as exc:
        print(f"错误: 转换失败 — {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 3

    # Write markdown
    md_output.write_text(result.markdown, encoding="utf-8")
    print(f"✅ Markdown: {md_output}")

    # Count assets
    asset_files = sorted(assets_dir.rglob("*")) if assets_dir.exists() else []
    asset_count = len([f for f in asset_files if f.is_file()])
    if asset_count:
        print(f"🖼️  提取 {asset_count} 个图片 → {assets_dir}/")
    elif not args.no_images:
        print("ℹ️  未发现嵌入图片")

    return 0


if __name__ == "__main__":
    sys.exit(main())
