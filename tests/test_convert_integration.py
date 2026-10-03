"""The real conversion: the pinned office2pdf turns an embedded minimal DOCX into a one-page PDF.

Moved from spire-venue server/tests/office-pdf.integration.test.ts. Skipped unless
OFFICE_PDF_TESTS=1; then a missing converter fails. CI runs it twice: on the runner (the glibc
build) and in the convert image with no network (the musl build). Only the standard library
reads the PDF, so it runs in the convert profile.
"""
import base64
import os
import re

import pytest

from publishing import convert as cv

# Minimal OOXML ZIP: [Content_Types].xml, _rels/.rels and word/document.xml.
# One paragraph: "Spire office PDF integration fixture."; US Letter, 1-inch margins.
# Deflated entries, fixed 1980-01-01 timestamps; no external documents or tooling.
DOCX = (
    "UEsDBBQAAAAIAAAAIQD3VP4j2wAAAGQBAAATAAAAW0NvbnRlbnRfVHlwZXNdLnhtbJWQu07EMBBFf8Vyi2IHCoRQki14lECxfIDlTBILe8byzAbz9yi77BbbUc+591xNt6spqhUKB8Je35pWK0BPY8C515/71+ZB74Zu/5OBVU0RudeLSH60lv0CybGhDFhTnKgkJ2yozDY7/+VmsHdte289oQBKI1uHHrpnmNwhinqpAnjSFois1dMJ3Fy9djnH4J0EQrvieGVp/gymQDwyvITMNzVFbYfufYVSwgjqwxV5cwl6bb+pjHYkf0iAYjbwXz6apuDhkt/aciEPzAHnFM3lklzA8w57fNvwC1BLAwQUAAAACAAAACEANlfe3KQAAAAYAQAACwAAAF9yZWxzLy5yZWxzjc+xCsIwFAXQXwlvN2kdRKRpFxG6Sv2AkLy2wSQvJFHr37s4WHFwvVzO5Tbd4h27Y8qWgoSaV8AwaDI2TBIuw2mzh65tzuhUsRTybGNmi3chS5hLiQchsp7Rq8wpYli8Gyl5VTKnNImo9FVNKLZVtRPp04C1yXojIfWmBjY8I/5j0zhajUfSN4+h/Jj4agAbVJqwSHhQMsK8Y754B6JtxOpi+wJQSwMEFAAAAAgAAAAhANOZPhblAAAAVwEAABEAAAB3b3JkL2RvY3VtZW50LnhtbEWQ0WrDMAxFf8X4fXESslFCkr6Uvg0K3T4gdZTEEFtGVudsXz+cEvJyhNDlXknNebWL+AEKBl0riyyXApzGwbipld9f17eTPHdNrAfUTwuOxWoXF+rYypnZ10oFPYPtQ4Ye3GqXEcn2HDKkSUWkwRNqCMG4yS6qzPMPZXvjZLJ84PCbqk+gBO7u3hAIHEejQdwuV2Ecw0Q9G3RiNCs/CbJGJWkibdwMAmi+bS5+uv+JmFYsyrLKpYj13Mri/VTlUr0Enz2JWDP6VhbVS0JmmvloH8iM9ugXGPep2kL3PLUfoo4ndf9QSwECFAAUAAAACAAAACEA91T+I9sAAABkAQAAEwAAAAAAAAAAAAAAAAAAAAAAW0NvbnRlbnRfVHlwZXNdLnhtbFBLAQIUABQAAAAIAAAAIQA2V97cpAAAABgBAAALAAAAAAAAAAAAAAAAAAwBAABfcmVscy8ucmVsc1BLAQIUABQAAAAIAAAAIQDTmT4W5QAAAFcBAAARAAAAAAAAAAAAAAAAANkBAAB3b3JkL2RvY3VtZW50LnhtbFBLBQYAAAAAAwADALkAAADtAgAAAAA="
)


@pytest.mark.skipif(os.environ.get("OFFICE_PDF_TESTS") != "1", reason="set OFFICE_PDF_TESTS=1 to require the real converter")
def test_real_office2pdf_converts_a_self_contained_docx_into_a_one_page_pdf(tmp_path):
    assert cv.office2pdf_bin(), "OFFICE_PDF_TESTS=1 requires an executable office2pdf; set OFFICE2PDF_BIN"
    src, dest = tmp_path / "minimal.docx", tmp_path / "minimal.pdf"
    src.write_bytes(base64.b64decode(DOCX))
    assert cv.convert(src, dest) == dest
    pdf = dest.read_bytes().decode("latin-1")
    assert re.match(r"%PDF-1\.[0-9]", pdf)
    assert re.search(r"/Type\s*/Catalog\b", pdf)
    assert re.search(r"/Type\s*/Page\b", pdf)
    assert re.search(r"/Count\s+1\b", pdf)
    assert re.search(r"startxref\s+\d+\s+%%EOF\s*$", pdf)
    assert sorted(tmp_path.iterdir()) == sorted([src, dest])
