"""Tool: convert a local PDF file to Markdown via SiliconFlow DeepSeek-OCR.

Usage:
    python3 pdf_to_md.py <pdf_file_path>

Environment:
    OCR_API_KEY: SiliconFlow API key for DeepSeek-OCR
"""

import base64
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz  # PyMuPDF
import httpx

# Pattern to strip grounding coordinate tags from OCR output
_GROUNDING_TAG_RE = re.compile(r"<\|ref\|>.*?<\|/ref\|><\|det\|>\[\[.*?\]\]<\|/det\|>\s*")

API_URL = "https://api.siliconflow.cn/v1/chat/completions"
MODEL = "deepseek-ai/DeepSeek-OCR"

MAX_FILE_SIZE_MB = 50
MAX_WORKERS = 10


def _ocr_single_page(pdf_bytes: bytes, api_key: str) -> str:
    """Send a single-page PDF (bytes) to DeepSeek-OCR and return cleaned text."""
    pdf_b64 = base64.b64encode(pdf_bytes).decode()

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:application/pdf;base64,{pdf_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": "<image>\n<|grounding|>Convert the document to markdown.",
                    },
                ],
            }
        ],
    }

    transport = httpx.HTTPTransport(retries=3, verify=False)

    with httpx.Client(transport=transport, timeout=180.0) as client:
        resp = client.post(
            API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json=payload,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"API request failed ({resp.status_code}): {resp.text}")

    data = resp.json()
    raw = data["choices"][0]["message"]["content"]
    return _GROUNDING_TAG_RE.sub("", raw).strip()


def _extract_page_bytes(doc: fitz.Document, page_idx: int) -> bytes:
    """Extract a single page from a PDF document as bytes."""
    single = fitz.open()
    single.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
    page_bytes = single.tobytes()
    single.close()
    return page_bytes


def pdf_to_md(file_path: str) -> dict[str, str]:
    """Read a local PDF, OCR each page in parallel, return merged Markdown.

    - Max file size: 50 MB; files above this are rejected.
    - All pages are OCR'd in parallel (up to 10 workers).
    - Each page is sent as a separate API request (API only processes 1 page).

    Args:
        file_path: Absolute or relative path to a PDF file.

    Returns:
        dict with ``markdown`` (the converted text) or ``error``.
    """
    api_key = os.environ.get("OCR_API_KEY", "")

    if not api_key:
        raise ValueError("OCR_API_KEY environment variable is required for PDF OCR")

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {"error": f"File not found: {path}"}
    if path.suffix.lower() != ".pdf":
        return {"error": f"Not a PDF file: {path}"}

    file_size_mb = path.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        return {"error": f"File too large: {file_size_mb:.1f}MB (max {MAX_FILE_SIZE_MB}MB)"}

    doc = fitz.open(str(path))
    total_pages = len(doc)

    # Extract all pages as individual PDFs
    pages: list[tuple[int, bytes]] = []
    for i in range(total_pages):
        pages.append((i, _extract_page_bytes(doc, i)))
    doc.close()

    # OCR all pages in parallel (max 10 concurrent)
    page_results: dict[int, str] = {}

    def _process_page(page_idx: int, pdf_bytes: bytes) -> tuple[int, str]:
        try:
            text = _ocr_single_page(pdf_bytes, api_key)
            return page_idx, f"<!-- Page {page_idx + 1} -->\n\n{text}"
        except RuntimeError as e:
            return page_idx, f"<!-- Page {page_idx + 1} -->\n\n> OCR failed: {e}"

    with ThreadPoolExecutor(max_workers=min(total_pages, MAX_WORKERS)) as executor:
        futures = {
            executor.submit(_process_page, idx, pdf_bytes): idx
            for idx, pdf_bytes in pages
        }
        for future in as_completed(futures):
            idx, result = future.result()
            page_results[idx] = result

    ordered_results = [page_results[i] for i in range(total_pages)]

    markdown = "\n\n---\n\n".join(ordered_results)

    # Write full output alongside the source PDF
    out_path = path.with_suffix(".md")
    out_path.write_text(markdown, encoding="utf-8")

    # Truncate content returned to LLM at 10k chars; full text saved to file
    max_content_len = 10000
    truncated = len(markdown) > max_content_len
    if truncated:
        content_for_llm = (
            markdown[:max_content_len]
            + f"\n\n... [内容已截断，完整文本共 {len(markdown)} 字符，"
            + f"已保存至 {out_path}]"
        )
    else:
        content_for_llm = markdown

    return {
        "markdown": content_for_llm,
        "truncated": str(truncated),
        "total_chars": str(len(markdown)),
        "output_file": str(out_path),
        "total_pages": str(total_pages),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 pdf_to_md.py <pdf_file_path>", file=sys.stderr)
        sys.exit(1)

    result = pdf_to_md(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
