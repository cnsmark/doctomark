# doctomark 📄 → 📝

**doctomark** 是一个轻量级 Python CLI 工具，将 Office 文件和 PDF 转换为 Markdown 格式，**同时完整提取嵌入图片**并保持引用关系。

## 为什么需要它？

现有工具（如 `markitdown`）虽然支持 Office/PDF → Markdown 转换，但存在关键缺陷：

| 格式 | markitdown 的问题 | doctomark 的改进 |
|------|------------------|-----------------|
| `.docx` | mammoth 默认模式图片全部丢失 | ✅ 自定义图片回调，提取到 `_assets/` |
| `.pptx` | 只写 `![alt](filename)`，图片未实际保存 | ✅ 提取 `shape.image.blob` 到文件 |
| `.xlsx` | 只读表格数据，图片忽略 | ✅ 从 zip 的 `xl/media/` 提取图片 |
| `.pdf` | `extract_text()` 纯文本，图片全丢 | ✅ pdfminer 低阶 API 提取图片流 |

## 安装

```bash
cd doctomark
pip install -e doctomark
```

或者直接使用：

```bash
cd doctomark && python -m doctomark.cli <输入文件>
```

## 用法

```bash
# 基本用法
doctomark report.docx
# → 生成 report.md + report_assets/

# 指定输出目录
doctomark report.docx -d /path/to/output

# 自定义输出文件名
doctomark report.docx -o my_report.md

# 自定义资源目录
doctomark report.docx --assets-dir images

# 列出支持的格式
doctomark --supported
```

## 支持格式

| 格式 | 扩展名 | 文本 | 图片 | 表格 | 图表 |
|------|--------|------|------|------|------|
| Word | `.docx` | ✅ | ✅ | ✅ | — |
| PowerPoint | `.pptx` | ✅ | ✅ | ✅ | ✅ |
| Excel | `.xlsx` | ✅ | ✅ | ✅ | — |
| Excel(旧) | `.xls` | ✅ | ⚠️ | ✅ | — |
| PDF | `.pdf` | ✅ | ✅ | — | — |

> ⚠️ 旧版 `.xls` 格式的图片提取因 OLE2 结构复杂暂不支持。

## 工作原理

```
doctomark input.docx
        │
        ▼
┌───────────────────────────────────┐
│  格式检测 (by extension)          │
│  .docx → DocxConverter           │
│  .pptx → PptxConverter           │
│  .xlsx → XlsxConverter           │
│  .pdf  → PdfConverter            │
└──────────────┬────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
  📝 Markdown      🖼️ 图片提取
  文本+表格+结构    (去重、格式识别)
       │                │
       └────────┬───────┘
                ▼
    output.md + output_assets/
```

## 项目结构

```
doctomark/
├── pyproject.toml
├── doctomark/
│   ├── __init__.py
│   ├── base.py          # 基础类：图片保存、去重、格式识别
│   ├── docx.py          # DOCX 转换器 (mammoth + 自定义回调)
│   ├── pptx.py          # PPTX 转换器 (python-pptx)
│   ├── xlsx.py          # XLSX/XLS 转换器 (pandas + zip)
│   ├── pdf.py           # PDF 转换器 (pdfminer + Pillow)
│   └── cli.py           # CLI 入口
└── tests/
    ├── gen_test_files.py # 测试文件生成
    └── test_files/       # 测试输入/输出
```

## 开发

```bash
# 生成测试文件
cd doctomark && python tests/gen_test_files.py

# 运行所有测试
for ext in docx pptx xlsx pdf; do
    python -m doctomark.cli tests/test_files/test.$ext \
        -d tests/test_files/out_$ext
done

# 验证输出
find tests/test_files/out_* -type f | sort
```
