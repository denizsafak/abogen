"""Regression tests for EPUB -> TXT paragraph-boundary merging.

Bug report:
    Original EPUB paragraphs::

        Test test test? Test it.
        "Test test test test."
        "Test test test test," Test test test test. "Test test."

    were extracted as::

        Test test test? Test it."Test test test test.""Test ..."

    i.e. block boundaries concatenated with ZERO characters (no space,
    no newline). Root cause: ``soup.get_text()`` without explicit break
    markers, with only p/div/h1-h6/li/blockquote handled and <br>,
    <section>, <article>, tables, etc. missed (and the legacy
    ``EpubParser`` spine fallback had no block handling at all).

These tests are intentionally broad: every block tag, <br>/<hr>,
punctuation pairs, both extractors (text_extractor + book_parser),
spine fallback, markdown sections, and the replace_single_newlines
contract (single newline -> exactly one space, never deletion).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from ebooklib import epub

from abogen.domain.text_utils import (
    HTML_BLOCK_TAGS,
    calculate_text_length,
    prepare_soup_block_breaks,
)
from abogen.text_extractor import EpubExtractor, extract_from_path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _soup_text(html: str) -> str:
    """Run the production helper + production clean_text (newlines kept)."""
    import abogen.utils as _u

    orig = _u.load_config
    _u.load_config = lambda: {}  # replace_single_newlines=False default
    try:
        from abogen.utils import clean_text

        soup = BeautifulSoup(html, "html.parser")
        prepare_soup_block_breaks(soup)
        return clean_text(soup.get_text()).strip()
    finally:
        _u.load_config = orig


def _soup_text_single_space(html: str) -> str:
    """Same but with replace_single_newlines=True (single \\n -> ' ')."""
    import abogen.utils as _u

    orig = _u.load_config
    _u.load_config = lambda: {"replace_single_newlines": True}
    try:
        from abogen.utils import clean_text

        soup = BeautifulSoup(html, "html.parser")
        prepare_soup_block_breaks(soup)
        return clean_text(soup.get_text()).strip()
    finally:
        _u.load_config = orig


def _write_epub(path: Path, chapters_html: list[str]) -> Path:
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Boundary Test")
    book.set_language("en")
    book.add_author("Tester")
    items = []
    for i, content in enumerate(chapters_html):
        ch = epub.EpubHtml(
            title=f"Ch{i + 1}", file_name=f"ch{i + 1}.xhtml", lang="en"
        )
        ch.content = content
        ch.id = f"ch{i + 1}"
        book.add_item(ch)
        items.append(ch.id)
    book.toc = [epub.Link(f"ch{i + 1}.xhtml", f"Ch{i + 1}", f"ch{i + 1}")
                for i in range(len(items))]
    book.spine = ["nav"] + items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)
    return path


def _extract_texts(path: Path) -> str:
    return extract_from_path(path).combined_text


# ---------------------------------------------------------------------------
# 1. Unit: every declared block tag separates content
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tag", list(HTML_BLOCK_TAGS))
def test_every_block_tag_separates(tag):
    out = _soup_text(f"<{tag}>Alpha.</{tag}><{tag}>Beta.</{tag}>")
    assert "Alpha.Beta" not in out, f"<{tag}> merged with zero chars"
    assert "Alpha." in out and "Beta." in out
    # must be separated by whitespace (newline or space), never glued
    idx = out.find("Alpha.")
    after = out[idx + len("Alpha."):]
    assert after[:1] in (" ", "\n"), f"<{tag}> boundary: {after[:5]!r}"


def test_br_single_becomes_break_not_glue():
    out = _soup_text("<p>First.</p><p>Second<br/>Third.</p>")
    assert "SecondThird" not in out
    # single <br> -> single newline (kept when replace=False) ...
    assert "Second\nThird." in out
    # ... and a real space when replace_single_newlines=True
    spaced = _soup_text_single_space("<p>Second<br/>Third.</p>")
    assert spaced == "Second Third."


def test_br_double_becomes_paragraph_break():
    out = _soup_text("First.<br/><br/>Second.")
    assert out == "First.\n\nSecond."


def test_hr_becomes_paragraph_break():
    out = _soup_text("First.<hr/>Second.")
    assert out == "First.\n\nSecond."


def test_nested_blocks_do_not_explode():
    out = _soup_text("<div><p>Alpha.</p><p>Beta.</p></div>")
    assert "Alpha.Beta" not in out
    assert out == "Alpha.\n\nBeta."


def test_inline_tags_do_not_gain_spurious_breaks():
    # <b>/<i>/<span>/<a> are inline: no separator must be invented
    out = _soup_text("<p>word <b>bold</b> word</p>")
    assert out == "word bold word"
    out2 = _soup_text("<p>word<b>bold</b>word</p>")
    assert out2 == "wordboldword"  # correct HTML rendering, not our bug


def test_script_style_sup_sub_removed_or_kept():
    # sup/sub are decomposed by the extractor; helper must not crash on them
    out = _soup_text("<p>Hi<sup>1</sup> there.</p>")
    assert "Hi" in out and "there." in out


# ---------------------------------------------------------------------------
# 2. Punctuation pairs: the reported symptom + similar marks
# ---------------------------------------------------------------------------

PUNCT_CASES = [
    ("period+open-quote", "Test it.", '"Quoted."'),
    ("quote+quote", '"First."', '"Second."'),
    ("comma-quote+word", '"First," said.', "He left."),
    ("question+quote", "Really?", '"Yes."'),
    ("exclaim+quote", "Wow!", '"Amazing."'),
    ("ellipsis+quote", "Wait…", '"What?"'),
    ("colon+quote", "He said:", '"Hello."'),
    ("semicolon+word", "One; two.", "Three."),
    ("em-dash+word", "Word — more.", "Next."),
    ("close-paren+word", "(aside).", "Next."),
    ("cjk-period+quote", "テスト。", '"引用。"'),
    ("arabic-qmark+word", "اختبار؟", "كلام."),
]

@pytest.mark.parametrize("name, first, second", PUNCT_CASES)
def test_punctuation_boundaries_never_glue_paragraphs(name, first, second):
    for html in (
        f"<p>{first}</p><p>{second}</p>",
        f"<section>{first}</section><section>{second}</section>",
        f"<div>{first}<br/><br/>{second}</div>",
    ):
        out = _soup_text(html)
        assert f"{first}{second}" not in out, f"{name} glued in {html[:40]}"
        # boundary char must be whitespace
        i = out.find(first)
        assert i != -1
        sep = out[i + len(first): i + len(first) + 1]
        assert sep in (" ", "\n"), f"{name}: separator {sep!r}"


def test_exact_user_report():
    html = (
        "<p>Test test test? Test it.</p>"
        '<p>"Test test test test."</p>'
        '<p>"Test test test test," Test test test test. "Test test."</p>'
    )
    out = _soup_text(html)
    assert out == (
        "Test test test? Test it.\n\n"
        '"Test test test test."\n\n'
        '"Test test test test," Test test test test. "Test test."'
    )
    assert 'it."Test' not in out
    assert '.""Test' not in out


# ---------------------------------------------------------------------------
# 3. End-to-end EPUB extraction (new text_extractor path)
# ---------------------------------------------------------------------------

def test_epub_p_paragraphs_keep_breaks(tmp_path):
    p = _write_epub(tmp_path / "p.epub", [
        "<h1>Ch1</h1><p>Test test test? Test it.</p>"
        '<p>"Test test test test."</p>'
        '<p>"Test test test test," Test test test test. "Test test."</p>',
    ])
    out = _extract_texts(p)
    assert 'it."Test' not in out
    assert '.""Test' not in out
    assert "Test test test? Test it." in out
    assert '"Test test test test."' in out


def test_epub_section_markup_keep_breaks(tmp_path):
    p = _write_epub(tmp_path / "sec.epub", [
        "<h1>Ch1</h1><section>First paragraph here.</section>"
        "<section>Second paragraph here.</section>",
    ])
    out = _extract_texts(p)
    assert "First paragraph here.Second" not in out


def test_epub_br_markup_keep_breaks(tmp_path):
    p = _write_epub(tmp_path / "br.epub", [
        "<h1>Ch1</h1><p>Line one.<br/><br/>Line two.</p>",
    ])
    out = _extract_texts(p)
    assert "Line one.Line two." not in out


def test_epub_table_cells_do_not_glue(tmp_path):
    p = _write_epub(tmp_path / "tbl.epub", [
        "<h1>Ch1</h1><table><tr><td>Cell one.</td><td>Cell two.</td></tr></table>",
    ])
    out = _extract_texts(p)
    assert "Cell one.Cell two." not in out


def test_epub_multi_doc_no_glue(tmp_path):
    p = _write_epub(tmp_path / "multi.epub", [
        "<h1>One</h1><p>First doc ends.</p>",
        "<h1>Two</h1><p>Second doc begins.</p>",
    ])
    out = _extract_texts(p)
    assert "ends.Second" not in out


# ---------------------------------------------------------------------------
# 4. Legacy book_parser paths (nav + spine fallback had the same bug)
# ---------------------------------------------------------------------------

def test_legacy_parser_spine_fallback_p_tags(tmp_path):
    from abogen.book_parser import EpubParser

    p = _write_epub(tmp_path / "spine.epub", [
        "<h1>Ch1</h1><p>Alpha ends.</p><p>Beta begins.</p>",
    ])
    parser = EpubParser(str(p))
    # force the fallback that previously had NO block handling
    parser._process_epub_content_spine_fallback()
    combined = "\n\n".join(parser.content_texts.values())
    assert "Alpha ends.Beta begins." not in combined


def test_legacy_parser_section_and_br(tmp_path):
    from abogen.book_parser import EpubParser

    p = _write_epub(tmp_path / "legacy.epub", [
        "<h1>Ch1</h1><section>Sec one.</section><section>Sec two.</section>",
        "<h1>Ch2</h1><p>Line A.<br/>Line B.</p>",
    ])
    parser = EpubParser(str(p))
    parser.process_content()
    combined = "\n\n".join(parser.content_texts.values())
    assert "Sec one.Sec two." not in combined
    assert "Line A.Line B." not in combined


# ---------------------------------------------------------------------------
# 5. replace_single_newlines contract: space, not deletion
# ---------------------------------------------------------------------------

def test_replace_single_newlines_inserts_space_not_deletion():
    import abogen.utils as _u
    from abogen.utils import clean_text as clean_util

    orig = _u.load_config
    _u.load_config = lambda: {"replace_single_newlines": True}
    try:
        assert clean_util("a\nb") == "a b"
        assert clean_util("a\n\nb") == "a\n\nb"  # paragraph breaks survive
        assert clean_util("it.\n\"Quoted.\"") == 'it. "Quoted."'
    finally:
        _u.load_config = orig


def test_apply_newline_policy_inserts_space():
    from abogen.domain.output_paths import apply_newline_policy
    from abogen.text_extractor import ExtractedChapter

    ch = ExtractedChapter(title="t", text="a\nb\n\nc")
    apply_newline_policy([ch], True)
    assert ch.text == "a b\n\nc"


def test_subtitle_clean_text_inserts_space():
    import abogen.subtitle_utils as _s
    from abogen.subtitle_utils import clean_text as clean_sub

    orig = _s.load_config
    _s.load_config = lambda: {"replace_single_newlines": True}
    try:
        assert clean_sub("a\nb") == "a b"
    finally:
        _s.load_config = orig


# ---------------------------------------------------------------------------
# 6. Markdown sections (shared helper applied there too)
# ---------------------------------------------------------------------------

def test_markdown_section_blocks_separated():
    html = '<h1 id="a">A</h1><p>First.</p><p>Second.</p>'
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find(attrs={"id": "a"})
    if tag:
        tag.decompose()
    prepare_soup_block_breaks(soup)
    import abogen.utils as _u
    from abogen.utils import clean_text

    orig = _u.load_config
    _u.load_config = lambda: {}
    try:
        out = clean_text(soup.get_text()).strip()
    finally:
        _u.load_config = orig
    assert "First.Second." not in out


def test_character_count_unaffected_by_breaks():
    assert calculate_text_length("a\n\nb") == 2
