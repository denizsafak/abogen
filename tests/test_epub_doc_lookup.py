"""Regression tests for #209 (very slow opening of large EPUBs).

`_find_doc_key` must resolve documents via a prebuilt lookup instead of
scanning every spine document per navigation entry, and spine positions must
be O(1) with first-occurrence semantics like ``list.index``.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.book_parser import EpubParser
from abogen.text_extractor import EpubExtractor


def _orders(hrefs):
    import urllib.parse

    order = {h: i for i, h in enumerate(hrefs)}
    decoded = {urllib.parse.unquote(h): i for h, i in order.items()}
    return order, decoded


def _parser_finders():
    qt = EpubParser.__new__(EpubParser)
    web = EpubExtractor.__new__(EpubExtractor)
    return [qt._find_doc_key, web._find_doc_key]


def test_find_doc_key_exact_decoded_and_basename():
    order, decoded = _orders(["OEBPS/ch%201.xhtml", "OEBPS/ch2.xhtml"])
    for find in _parser_finders():
        assert find("OEBPS/ch2.xhtml", order, decoded) == ("OEBPS/ch2.xhtml", 1)
        assert find("OEBPS/ch%201.xhtml", order, decoded) == ("OEBPS/ch%201.xhtml", 0)
        # Different directory prefix resolves by case-insensitive basename.
        assert find("../Text/CH2.xhtml", order, decoded) == ("OEBPS/ch2.xhtml", 1)
        assert find("missing.xhtml", order, decoded) == (None, None)


def test_find_doc_key_rebuilds_for_new_mappings():
    for find in _parser_finders():
        order, decoded = _orders(["a/one.xhtml"])
        assert find("x/one.xhtml", order, decoded)[0] == "a/one.xhtml"
        order2, decoded2 = _orders(["b/two.xhtml"])
        assert find("x/one.xhtml", order2, decoded2) == (None, None)
        assert find("x/two.xhtml", order2, decoded2)[0] == "b/two.xhtml"


def test_find_doc_key_scales_with_many_documents():
    hrefs = [f"OEBPS/Text/chapter_{i:05d}.xhtml" for i in range(8000)]
    order, decoded = _orders(hrefs)
    for find in _parser_finders():
        start = time.perf_counter()
        for i in range(8000):
            assert find(f"../Text/chapter_{i:05d}.xhtml", order, decoded)[1] == i
        # The old per-call scan took minutes at this size.
        assert time.perf_counter() - start < 5


def test_spine_index_first_occurrence_and_missing():
    web = EpubExtractor.__new__(EpubExtractor)
    web._spine_pos_src = None
    web.spine_docs = ["a", "b", "a"]
    assert web._spine_index("a") == 0
    assert web._spine_index("b") == 1
    try:
        web._spine_index("zzz")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    web.spine_docs = ["z", "a"]  # reassigned list invalidates the cache
    assert web._spine_index("a") == 1
