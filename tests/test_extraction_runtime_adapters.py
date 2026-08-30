import io

import pytest
from docx import Document
from pypdf import PdfWriter

from ai_interviewer.extraction_runtime.adapters import (
    DOCX_ADAPTER,
    DOCX_ADAPTER_VERSION,
    PDF_ADAPTER,
    PDF_ADAPTER_VERSION,
    TEXT_ADAPTER,
    TEXT_ADAPTER_VERSION,
    CorruptInputError,
    EmptyInputError,
    EncryptedInputError,
    OutputBoundsExceededError,
    UnsupportedInputError,
    extract_text_docx,
    extract_text_pdf,
    extract_text_txt,
    resolve_adapter,
    sanitize_extracted_text,
)


def _docx_bytes(paragraphs: list[str]) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes_without_text() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_sanitize_extracted_text_normalizes_newlines_and_strips_controls() -> None:
    assert sanitize_extracted_text("a\r\nb\rc\x00d‮e") == "a\nb\ncde"


def test_sanitize_extracted_text_trims_surrounding_whitespace() -> None:
    assert sanitize_extracted_text("\n\n  hello  \n\n") == "hello"


def test_resolve_adapter_returns_registered_callable() -> None:
    assert resolve_adapter(TEXT_ADAPTER, TEXT_ADAPTER_VERSION) is extract_text_txt
    assert resolve_adapter(PDF_ADAPTER, PDF_ADAPTER_VERSION) is extract_text_pdf
    assert resolve_adapter(DOCX_ADAPTER, DOCX_ADAPTER_VERSION) is extract_text_docx


@pytest.mark.parametrize(
    ("adapter", "version"),
    [("isolated-pdf-parser", "2"), ("unknown-parser", "1"), ("", "")],
)
def test_resolve_adapter_rejects_unknown_pairs(adapter: str, version: str) -> None:
    with pytest.raises(UnsupportedInputError):
        resolve_adapter(adapter, version)


def test_extract_text_txt_returns_sanitized_content() -> None:
    assert extract_text_txt(b"hello\r\nworld") == "hello\nworld"


def test_extract_text_txt_rejects_empty_input() -> None:
    with pytest.raises(EmptyInputError):
        extract_text_txt(b"")


def test_extract_text_txt_rejects_whitespace_only_input() -> None:
    with pytest.raises(EmptyInputError):
        extract_text_txt(b"   \n\t  ")


def test_extract_text_txt_rejects_non_utf8_bytes() -> None:
    with pytest.raises(CorruptInputError):
        extract_text_txt(b"\xff\xfe\x00\x00not-utf8")


def test_extract_text_pdf_rejects_empty_input() -> None:
    with pytest.raises(EmptyInputError):
        extract_text_pdf(b"")


def test_extract_text_pdf_rejects_corrupt_input() -> None:
    with pytest.raises(CorruptInputError):
        extract_text_pdf(b"%PDF-1.4 not a real pdf")


def test_extract_text_pdf_rejects_blank_page_as_empty() -> None:
    with pytest.raises(EmptyInputError):
        extract_text_pdf(_pdf_bytes_without_text())


def test_extract_text_pdf_detects_encryption() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="secret", owner_password="secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(EncryptedInputError):
        extract_text_pdf(buffer.getvalue())


def test_extract_text_docx_rejects_empty_input() -> None:
    with pytest.raises(EmptyInputError):
        extract_text_docx(b"")


def test_extract_text_docx_rejects_corrupt_input() -> None:
    with pytest.raises(CorruptInputError):
        extract_text_docx(b"not a docx file at all")


def test_extract_text_docx_rejects_empty_document() -> None:
    with pytest.raises(EmptyInputError):
        extract_text_docx(_docx_bytes([]))


def test_extract_text_docx_extracts_paragraph_text() -> None:
    assert extract_text_docx(_docx_bytes(["Experienced backend engineer."])) == (
        "Experienced backend engineer."
    )


def test_extract_text_txt_rejects_output_over_the_bounded_limit() -> None:
    with pytest.raises(OutputBoundsExceededError):
        extract_text_txt(("a" * 500_001).encode())
