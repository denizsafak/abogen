from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


MARKER_PREFIX = "[[ABOGEN-DBG:"
MARKER_SUFFIX = "]]"


@dataclass(frozen=True)
class DebugTTSSample:
    code: str
    label: str
    text: str


DEBUG_TTS_SAMPLES: Sequence[DebugTTSSample] = (
    DebugTTSSample(
        code="APOS_001",
        label="Apostrophes & contractions (1)",
        text="It's a beautiful day, isn't it? Let's see what we'll do.",
    ),
    DebugTTSSample(
        code="APOS_002",
        label="Apostrophes & contractions (2)",
        text="I'm sure you're ready; we'd better go before it's too late.",
    ),
    DebugTTSSample(
        code="APOS_003",
        label="Apostrophes & contractions (3)",
        text="He'll say it's fine, but I can't promise it'll work.",
    ),
    DebugTTSSample(
        code="APOS_004",
        label="Apostrophes & contractions (4)",
        text="They've done it, and I'd agree they've earned it.",
    ),
    DebugTTSSample(
        code="APOS_005",
        label="Apostrophes & contractions (5)",
        text="She's here, we're late, they're waiting, and you're right.",
    ),
    DebugTTSSample(
        code="POS_001",
        label="Plural possessives (1)",
        text="The dogs' bowls were empty, but the boss's office was quiet.",
    ),
    DebugTTSSample(
        code="POS_002",
        label="Plural possessives (2)",
        text="The teachers' lounge was closed during the students' exams.",
    ),
    DebugTTSSample(
        code="POS_003",
        label="Plural possessives (3)",
        text="The actresses' roles changed, and the directors' notes piled up.",
    ),
    DebugTTSSample(
        code="POS_004",
        label="Plural possessives (4)",
        text="The Joneses' car was parked by the neighbors' fence.",
    ),
    DebugTTSSample(
        code="POS_005",
        label="Plural possessives (5)",
        text="The bosses' meeting ended before the witnesses' statements began.",
    ),
    DebugTTSSample(
        code="NUM_001",
        label="Grouped numbers (1)",
        text="There are 1,234 apples, 56 oranges, and 7.89 liters of juice.",
    ),
    DebugTTSSample(
        code="NUM_002",
        label="Grouped numbers (2)",
        text="The population is 10,000,000 and the area is 123.45 square miles.",
    ),
    DebugTTSSample(
        code="NUM_003",
        label="Grouped numbers (3)",
        text="Set the timer for 0.5 seconds, then wait 2.0 minutes.",
    ),
    DebugTTSSample(
        code="NUM_004",
        label="Grouped numbers (4)",
        text="We measured 3.1415 radians and wrote down 2,718.28 as well.",
    ),
    DebugTTSSample(
        code="NUM_005",
        label="Grouped numbers (5)",
        text="The sequence is 1, 2, 3, 4, 5, and then 13.",
    ),
    DebugTTSSample(
        code="YEAR_001",
        label="Years and decades (1)",
        text="In 1999, people said the '90s were over.",
    ),
    DebugTTSSample(
        code="YEAR_002",
        label="Years and decades (2)",
        text="In 2001, the show premiered; by 2010 it was everywhere.",
    ),
    DebugTTSSample(
        code="YEAR_003",
        label="Years and decades (3)",
        text="The 1980s were loud, and the 1970s were groovy.",
    ),
    DebugTTSSample(
        code="YEAR_004",
        label="Years and decades (4)",
        text="She loved the '80s, but he preferred the '60s.",
    ),
    DebugTTSSample(
        code="YEAR_005",
        label="Years and decades (5)",
        text="In 2024, we looked back at 2020 and planned for 2030.",
    ),
    DebugTTSSample(
        code="DATE_001",
        label="Dates (1)",
        text="On 2023-01-01, we celebrated the new year.",
    ),
    DebugTTSSample(
        code="DATE_002",
        label="Dates (2)",
        text="The deadline is 1999-12-31 at midnight.",
    ),
    DebugTTSSample(
        code="DATE_003",
        label="Dates (3)",
        text="Leap day happens on 2024-02-29.",
    ),
    DebugTTSSample(
        code="DATE_004",
        label="Dates (4)",
        text="Some formats look like 01/02/2003 and can be ambiguous.",
    ),
    DebugTTSSample(
        code="DATE_005",
        label="Dates (5)",
        text="We met on March 5, 2020 and again on Apr. 7, 2021.",
    ),
    DebugTTSSample(
        code="CUR_001",
        label="Currency symbols (1)",
        text="The price is $10.50, but it was £8.00 yesterday.",
    ),
    DebugTTSSample(
        code="CUR_002",
        label="Currency symbols (2)",
        text="Tickets cost €12, and the fine was $0.99.",
    ),
    DebugTTSSample(
        code="CUR_003",
        label="Currency symbols (3)",
        text="The bill was ¥500 and the refund was $-3.25.",
    ),
    DebugTTSSample(
        code="CUR_004",
        label="Currency symbols (4)",
        text="He paid £1,234.56 for the instrument.",
    ),
    DebugTTSSample(
        code="CUR_005",
        label="Currency symbols (5)",
        text="The subscription is $5 per month, or $50 per year.",
    ),
    DebugTTSSample(
        code="TITLE_001",
        label="Titles and abbreviations (1)",
        text="Dr. Smith lives on Elm St. near the U.S. border.",
    ),
    DebugTTSSample(
        code="TITLE_002",
        label="Titles and abbreviations (2)",
        text="Mr. and Mrs. Doe met Prof. Adams at 5 p.m.",
    ),
    DebugTTSSample(
        code="TITLE_003",
        label="Titles and abbreviations (3)",
        text="Gen. Smith spoke to Sgt. Rivera on Main St.",
    ),
    DebugTTSSample(
        code="TITLE_004",
        label="Titles and abbreviations (4)",
        text="The report came from the U.K. office, not the U.S.A. team.",
    ),
    DebugTTSSample(
        code="TITLE_005",
        label="Titles and abbreviations (5)",
        text="St. John's is different from St. Louis.",
    ),
    DebugTTSSample(
        code="PUNC_001",
        label="Terminal punctuation (1)",
        text="This sentence ends without punctuation",
    ),
    DebugTTSSample(
        code="PUNC_002",
        label="Terminal punctuation (2)",
        text="An ellipsis is already present...",
    ),
    DebugTTSSample(
        code="PUNC_003",
        label="Terminal punctuation (3)",
        text="A question without a mark",
    ),
    DebugTTSSample(
        code="PUNC_004",
        label="Terminal punctuation (4)",
        text="An exclamation without a bang",
    ),
    DebugTTSSample(
        code="PUNC_005",
        label="Terminal punctuation (5)",
        text='A quote ends here"',
    ),
    DebugTTSSample(
        code="QUOTE_001",
        label="ALL CAPS inside quotes (1)",
        text='He shouted, "THIS IS IMPORTANT!" and then whispered, "ok."',
    ),
    DebugTTSSample(
        code="QUOTE_002",
        label="ALL CAPS inside quotes (2)",
        text='She said, "NO WAY", but he replied, "maybe".',
    ),
    DebugTTSSample(
        code="QUOTE_003",
        label="ALL CAPS inside quotes (3)",
        text='The sign read "DO NOT ENTER" and the note read "pls knock".',
    ),
    DebugTTSSample(
        code="QUOTE_004",
        label="ALL CAPS inside quotes (4)",
        text='He muttered, "OK", then yelled, "STOP!"',
    ),
    DebugTTSSample(
        code="QUOTE_005",
        label="ALL CAPS inside quotes (5)",
        text='They chanted, "USA!" and someone wrote "idk".',
    ),
    DebugTTSSample(
        code="FOOT_001",
        label="Footnote indicators (1)",
        text="This is a sentence with a footnote[1] and another[12].",
    ),
    DebugTTSSample(
        code="FOOT_002",
        label="Footnote indicators (2)",
        text="Some books use multiple footnotes like this[2][3] in a row.",
    ),
    DebugTTSSample(
        code="FOOT_003",
        label="Footnote indicators (3)",
        text="A footnote can appear mid-sentence[4] and continue afterward.",
    ),
    DebugTTSSample(
        code="FOOT_004",
        label="Footnote indicators (4)",
        text="Edge cases include [0] or very large indices like [1234].",
    ),
    DebugTTSSample(
        code="FOOT_005",
        label="Footnote indicators (5)",
        text="Sometimes a footnote follows punctuation.[5] Sometimes it doesn't[6]",
    ),
)


def marker_for(code: str) -> str:
    return f"{MARKER_PREFIX}{code}{MARKER_SUFFIX}"


def build_debug_epub(dest_path: Path, *, title: str = "abogen debug samples") -> Path:
    """Create a tiny EPUB containing all debug samples.

    The text includes stable marker codes so developers can report failures
    precisely.
    """

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    chapter_lines: List[str] = [
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>",
        "<!DOCTYPE html>",
        "<html xmlns=\"http://www.w3.org/1999/xhtml\">",
        "<head>",
        f"  <title>{title}</title>",
        "  <meta charset=\"utf-8\" />",
        "</head>",
        "<body>",
        f"  <h1>{title}</h1>",
        "  <p>Each paragraph begins with a stable debug code marker.</p>",
    ]

    for sample in DEBUG_TTS_SAMPLES:
        safe_label = sample.label.replace("&", "and")
        chapter_lines.append(f"  <h2>{safe_label}</h2>")
        chapter_lines.append(
            "  <p><strong>" + marker_for(sample.code) + "</strong> " + sample.text + "</p>"
        )

    chapter_lines += ["</body>", "</html>"]
    chapter_xhtml = "\n".join(chapter_lines)

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

    content_opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">abogen-debug-samples</dc:identifier>
    <dc:title>abogen debug samples</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml" />
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
  </manifest>
  <spine>
    <itemref idref="chapter" />
  </spine>
</package>
"""

    nav_xhtml = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>Navigation</title>
  <meta charset="utf-8" />
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h2>Table of Contents</h2>
    <ol>
      <li><a href="chapter.xhtml">Debug samples</a></li>
    </ol>
  </nav>
</body>
</html>
"""

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "mimetype").write_text("application/epub+zip", encoding="utf-8")
        meta_inf = tmp_path / "META-INF"
        meta_inf.mkdir(parents=True, exist_ok=True)
        (meta_inf / "container.xml").write_text(container_xml, encoding="utf-8")
        oebps = tmp_path / "OEBPS"
        oebps.mkdir(parents=True, exist_ok=True)
        (oebps / "content.opf").write_text(content_opf, encoding="utf-8")
        (oebps / "chapter.xhtml").write_text(chapter_xhtml, encoding="utf-8")
        (oebps / "nav.xhtml").write_text(nav_xhtml, encoding="utf-8")

        # Per EPUB spec: mimetype must be the first entry and stored (no compression).
        with zipfile.ZipFile(dest_path, "w") as zf:
            zf.write(tmp_path / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            for source in (meta_inf / "container.xml", oebps / "content.opf", oebps / "chapter.xhtml", oebps / "nav.xhtml"):
                arcname = str(source.relative_to(tmp_path)).replace("\\", "/")
                zf.write(source, arcname, compress_type=zipfile.ZIP_DEFLATED)

    return dest_path


def iter_expected_codes() -> Iterable[str]:
    for sample in DEBUG_TTS_SAMPLES:
        yield sample.code
