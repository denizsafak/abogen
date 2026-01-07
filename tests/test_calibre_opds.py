from abogen.integrations.calibre_opds import CalibreOPDSClient, OPDSEntry, OPDSFeed, OPDSLink, feed_to_dict


def test_calibre_opds_feed_exposes_series_metadata() -> None:
    client = CalibreOPDSClient("http://example.com/catalog")
    xml_payload = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\"
          xmlns:dc=\"http://purl.org/dc/terms/\"
          xmlns:calibre=\"http://calibre.kovidgoyal.net/2009/catalog\">
      <id>catalog</id>
      <title>Example Catalog</title>
      <entry>
        <id>book-1</id>
        <title>Sample Book</title>
        <calibre:series>The Expanse</calibre:series>
        <calibre:series_index>4</calibre:series_index>
        <link rel=\"http://opds-spec.org/acquisition\"
              href=\"books/sample.epub\"
              type=\"application/epub+zip\" />
      </entry>
    </feed>
    """

    feed = client._parse_feed(xml_payload, base_url="http://example.com/catalog")
    assert feed.entries, "Expected at least one entry in parsed feed"
    entry = feed.entries[0]

    assert entry.series == "The Expanse"
    assert entry.series_index == 4.0

    feed_dict = feed_to_dict(feed)
    assert feed_dict["entries"][0]["series"] == "The Expanse"
    assert feed_dict["entries"][0]["series_index"] == 4.0


def test_calibre_opds_feed_exposes_subtitle_metadata() -> None:
    client = CalibreOPDSClient("http://example.com/catalog")
    xml_payload = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\"
          xmlns:calibre_md=\"http://calibre.kovidgoyal.net/2009/metadata\">
      <id>catalog</id>
      <title>Example Catalog</title>
      <entry>
        <id>book-1</id>
        <title>Sample Book</title>
        <calibre_md:subtitle>A Novel</calibre_md:subtitle>
        <link rel=\"http://opds-spec.org/acquisition\"
              href=\"books/sample.epub\"
              type=\"application/epub+zip\" />
      </entry>
    </feed>
    """

    feed = client._parse_feed(xml_payload, base_url="http://example.com/catalog")
    assert feed.entries
    assert feed.entries[0].subtitle == "A Novel"

    feed_dict = feed_to_dict(feed)
    assert feed_dict["entries"][0]["subtitle"] == "A Novel"


def test_calibre_opds_feed_extracts_series_from_categories() -> None:
    client = CalibreOPDSClient("http://example.com/catalog")
    xml_payload = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\"
          xmlns:dc=\"http://purl.org/dc/terms/\"
          xmlns:calibre=\"http://calibre.kovidgoyal.net/2009/catalog\">
      <id>catalog</id>
      <title>Example Catalog</title>
      <entry>
        <id>book-2</id>
        <title>Network Effect</title>
        <category
          scheme=\"http://calibre.kovidgoyal.net/2009/series\"
          term=\"The Murderbot Diaries #5\"
          label=\"The Murderbot Diaries [5]\" />
        <link rel=\"http://opds-spec.org/acquisition\"
              href=\"books/network-effect.epub\"
              type=\"application/epub+zip\" />
      </entry>
    </feed>
    """

    feed = client._parse_feed(xml_payload, base_url="http://example.com/catalog")
    assert feed.entries, "Expected at least one entry in parsed feed"
    entry = feed.entries[0]

    assert entry.series == "The Murderbot Diaries"
    assert entry.series_index == 5.0


def test_calibre_opds_does_not_map_author_into_series_from_categories() -> None:
    client = CalibreOPDSClient("http://example.com/catalog")
    xml_payload = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\"
          xmlns:dc=\"http://purl.org/dc/terms/\"
          xmlns:calibre=\"http://calibre.kovidgoyal.net/2009/catalog\">
      <id>catalog</id>
      <title>Example Catalog</title>
      <entry>
        <id>book-author-series-bug</id>
        <title>Sample Book</title>
        <author>
          <name>Alexandre Dumas</name>
        </author>
        <category
          scheme=\"http://calibre.kovidgoyal.net/2009/series\"
          term=\"Books: Alexandre Dumas\"
          label=\"Books: Alexandre Dumas\" />
        <link rel=\"http://opds-spec.org/acquisition\"
              href=\"books/sample.epub\"
              type=\"application/epub+zip\" />
      </entry>
    </feed>
    """

    feed = client._parse_feed(xml_payload, base_url="http://example.com/catalog")
    assert feed.entries
    entry = feed.entries[0]

    assert entry.authors == ["Alexandre Dumas"]
    assert entry.series is None
    assert entry.series_index is None


def test_calibre_opds_extracts_tags_and_rating_from_summary() -> None:
    client = CalibreOPDSClient("http://example.com/catalog")
    xml_payload = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\"
    xmlns:dc=\"http://purl.org/dc/terms/\">
      <id>catalog</id>
      <title>Example Catalog</title>
      <entry>
  <id>book-3</id>
  <title>Summary Sample</title>
  <dc:date>2024-01-15T00:00:00+00:00</dc:date>
  <summary type=\"text\">RATING: ★★★½
TAGS: Science Fiction; Adventure
SERIES: Saga [3]
This is the detailed summary text.</summary>
  <link rel=\"http://opds-spec.org/acquisition\"
        href=\"books/sample.epub\"
        type=\"application/epub+zip\" />
      </entry>
    </feed>
    """

    feed = client._parse_feed(xml_payload, base_url="http://example.com/catalog")
    entry = feed.entries[0]

    assert entry.series == "Saga"
    assert entry.series_index == 3.0
    assert entry.tags == ["Science Fiction", "Adventure"]
    assert entry.rating == 3.5
    assert entry.rating_max == 5.0
    assert entry.summary == "This is the detailed summary text."
    assert entry.published == "2024-01-15T00:00:00+00:00"


def test_calibre_opds_relative_urls_keep_catalog_prefix() -> None:
  client = CalibreOPDSClient("http://example.com/opds/")

  assert client._make_url("search") == "http://example.com/opds/search"
  assert client._make_url("books/sample.epub") == "http://example.com/opds/books/sample.epub"
  assert client._make_url("/cover/1") == "http://example.com/cover/1"
  assert client._make_url("?page=2") == "http://example.com/opds?page=2"


def test_calibre_opds_base_url_without_trailing_slash() -> None:
  """Ensure the client works with base URLs that don't have trailing slashes."""
  client = CalibreOPDSClient("http://example.com/api/v1/opds")

  # Base URL should be stored without trailing slash
  assert client._base_url == "http://example.com/api/v1/opds"
  # Relative paths should resolve as siblings to the base URL
  assert client._make_url("catalog") == "http://example.com/api/v1/opds/catalog"
  assert client._make_url("search?q=test") == "http://example.com/api/v1/opds/search?q=test"
  assert client._make_url("/api/v1/opds/books") == "http://example.com/api/v1/opds/books"
  assert client._make_url("?page=2") == "http://example.com/api/v1/opds?page=2"


def test_calibre_opds_filters_out_unsupported_formats() -> None:
    client = CalibreOPDSClient("http://example.com/catalog")
    xml_payload = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\">
      <id>catalog</id>
      <title>Example Catalog</title>
      <entry>
        <id>audio-book</id>
        <title>Unsupported Audio</title>
        <link rel=\"http://opds-spec.org/acquisition\"
              href=\"books/sample.mp3\"
              type=\"audio/mpeg\" />
      </entry>
      <entry>
        <id>pdf-book</id>
        <title>Allowed PDF</title>
        <link rel=\"http://opds-spec.org/acquisition\"
              href=\"books/sample.pdf\"
              type=\"application/pdf\" />
      </entry>
      <entry>
        <id>epub-book</id>
        <title>Allowed EPUB</title>
        <link rel=\"http://opds-spec.org/acquisition\"
              href=\"books/sample.epub\" />
      </entry>
      <entry>
        <id>nav-author</id>
        <title>Authors (A)</title>
        <link rel=\"http://opds-spec.org/subsection\"
              href=\"/opds/authors/a\"
              type=\"application/atom+xml;profile=opds-catalog\" />
      </entry>
    </feed>
    """

    feed = client._parse_feed(xml_payload, base_url="http://example.com/catalog")

    identifiers = {entry.id for entry in feed.entries}
    assert identifiers == {"pdf-book", "epub-book", "nav-author"}
    for entry in feed.entries:
        if entry.id.startswith("nav-"):
            assert entry.download is None
            assert entry.links, "Expected navigation entry to preserve links"
        else:
            assert entry.download is not None
            assert entry.download.href.endswith((".pdf", ".epub"))


def test_calibre_opds_navigation_entries_without_download_are_preserved() -> None:
    client = CalibreOPDSClient("http://example.com/catalog")
    xml_payload = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\">
      <id>catalog</id>
      <title>Example Catalog</title>
      <entry>
        <id>nav-series</id>
        <title>Series</title>
        <link rel=\"http://opds-spec.org/subsection\"
              href=\"/opds/series\"
              type=\"application/atom+xml;profile=opds-catalog\" />
      </entry>
    </feed>
    """

    feed = client._parse_feed(xml_payload, base_url="http://example.com/catalog")

    assert [entry.id for entry in feed.entries] == ["nav-series"]
    entry = feed.entries[0]
    assert entry.download is None
    assert any(link.href.endswith("/opds/series") for link in entry.links)


def test_calibre_opds_search_filters_by_title_and_author() -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  feed = OPDSFeed(
    id="catalog",
    title="Catalog",
    entries=[
      OPDSEntry(id="1", title="The Long Journey", authors=["Alice Smith"]),
      OPDSEntry(id="2", title="Hidden Worlds", authors=["Bob Johnson"]),
      OPDSEntry(id="3", title="Side Stories", authors=["Cara Nguyen"], series="Journey Tales"),
    ],
  )

  filtered = client._filter_feed_entries(feed, "journey alice")
  assert [entry.id for entry in filtered.entries] == ["1"]

  filtered = client._filter_feed_entries(feed, "bob")
  assert [entry.id for entry in filtered.entries] == ["2"]

  filtered = client._filter_feed_entries(feed, "journey tales")
  assert [entry.id for entry in filtered.entries] == ["3"]

  filtered = client._filter_feed_entries(feed, "missing")
  assert filtered.entries == []


def test_calibre_opds_local_search_follows_next(monkeypatch) -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  page_one = OPDSFeed(
    id="catalog",
    title="Catalog",
    entries=[OPDSEntry(id="1", title="Unrelated", authors=["Alice Smith"])],
    links={"next": OPDSLink(href="http://example.com/catalog?page=2", rel="next")},
  )
  page_two = OPDSFeed(
    id="catalog",
    title="Catalog",
    entries=[OPDSEntry(id="2", title="The Journey Continues", authors=["Bob Johnson"])],
    links={},
  )

  def fake_fetch(href=None, params=None):
    if href == "http://example.com/catalog?page=2":
      return page_two
    return page_one

  monkeypatch.setattr(client, "fetch_feed", fake_fetch)

  result = client._local_search("journey", seed_feed=page_one)
  assert [entry.id for entry in result.entries] == ["2"]


def test_calibre_opds_local_search_traverses_navigation(monkeypatch) -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  root_feed = OPDSFeed(
    id="catalog",
    title="Catalog",
    entries=[
      OPDSEntry(
        id="nav-authors",
        title="Browse Authors",
        links=[
          OPDSLink(
            href="http://example.com/catalog/authors",
            rel="http://opds-spec.org/navigation",
            type="application/atom+xml;profile=opds-catalog",
          )
        ],
      )
    ],
    links={},
  )
  authors_feed = OPDSFeed(
    id="authors",
    title="Authors",
    entries=[
      OPDSEntry(id="book-42", title="The Count of Monte Cristo", authors=["Alexandre Dumas"])
    ],
    links={},
  )

  def fake_fetch(href=None, params=None):
    if href == "http://example.com/catalog/authors":
      return authors_feed
    return root_feed

  monkeypatch.setattr(client, "fetch_feed", fake_fetch)

  result = client._local_search("monte cristo", seed_feed=root_feed)
  assert [entry.id for entry in result.entries] == ["book-42"]


def test_calibre_opds_search_falls_back_to_local_search(monkeypatch) -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  search_page = OPDSFeed(
    id="catalog",
    title="Catalog",
    entries=[OPDSEntry(id="1", title="Unrelated", authors=["Alice Smith"])],
    links={"next": OPDSLink(href="http://example.com/catalog?page=2", rel="next")},
  )
  next_page = OPDSFeed(
    id="catalog",
    title="Catalog",
    entries=[OPDSEntry(id="2", title="Journey in Space", authors=["Cara Nguyen"])],
    links={},
  )

  def fake_fetch(path=None, params=None):
    if path == "search":
      return search_page
    if path == "http://example.com/catalog?page=2":
      return next_page
    return search_page

  monkeypatch.setattr(client, "fetch_feed", fake_fetch)

  result = client.search("journey")
  assert [entry.id for entry in result.entries] == ["2"]


def test_calibre_opds_search_collects_next_page_results(monkeypatch) -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  first_page = OPDSFeed(
    id="catalog",
    title="Catalog",
    entries=[OPDSEntry(id="1", title="Ryan's Adventure")],
    links={"next": OPDSLink(href="http://example.com/catalog?page=2", rel="next")},
  )
  second_page = OPDSFeed(
    id="catalog",
    title="Catalog",
    entries=[OPDSEntry(id="2", title="Return of Ryan")],
    links={},
  )

  def fake_fetch(path=None, params=None):
    if path == "search":
      return first_page
    if path == "http://example.com/catalog?page=2":
      return second_page
    if path is None and params is None:
      return first_page
    return first_page

  monkeypatch.setattr(client, "fetch_feed", fake_fetch)

  result = client.search("ryan")
  assert [entry.id for entry in result.entries] == ["1", "2"]


def test_calibre_opds_search_supplements_with_local_navigation(monkeypatch) -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  search_feed = OPDSFeed(
    id="catalog",
    title="Catalog",
    entries=[
      OPDSEntry(id="book-1", title="Ryan's First Mission"),
      OPDSEntry(
        id="nav-authors",
        title="Browse Authors",
        links=[
          OPDSLink(
            href="http://example.com/catalog/authors",
            rel="http://opds-spec.org/navigation",
            type="application/atom+xml;profile=opds-catalog",
          )
        ],
      ),
    ],
    links={},
  )
  authors_feed = OPDSFeed(
    id="authors",
    title="Authors",
    entries=[OPDSEntry(id="book-2", title="Chronicles of Ryan")],
    links={},
  )

  def fake_fetch(path=None, params=None):
    if path == "search":
      return search_feed
    if path == "http://example.com/catalog/authors":
      return authors_feed
    if path is None and params is None:
      return search_feed
    return search_feed

  monkeypatch.setattr(client, "fetch_feed", fake_fetch)

  result = client.search("ryan")
  assert [entry.id for entry in result.entries] == ["book-1", "book-2"]


def test_calibre_opds_browse_letter_traverses_next(monkeypatch) -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  root_feed = OPDSFeed(
    id="catalog",
    title="Browse Authors",
    entries=[
      OPDSEntry(
        id="nav-a",
        title="A",
        links=[
          OPDSLink(
            href="http://example.com/catalog/authors/a",
            rel="http://opds-spec.org/navigation",
            type="application/atom+xml;profile=opds-catalog",
          )
        ],
      )
    ],
    links={"next": OPDSLink(href="http://example.com/catalog?page=2", rel="next")},
  )
  page_two = OPDSFeed(
    id="catalog",
    title="Browse Authors",
    entries=[
      OPDSEntry(
        id="nav-c",
        title="C",
        links=[
          OPDSLink(
            href="http://example.com/catalog/authors/c",
            rel="http://opds-spec.org/navigation",
            type="application/atom+xml;profile=opds-catalog",
          )
        ],
      )
    ],
    links={},
  )
  letter_feed = OPDSFeed(
    id="authors-c",
    title="Authors starting with C",
    entries=[OPDSEntry(id="author-1", title="Clarke, Arthur C.")],
    links={},
  )

  def fake_fetch(href=None, params=None):
    if not href:
      return root_feed
    if href == "http://example.com/catalog?page=2":
      return page_two
    if href == "http://example.com/catalog/authors/c":
      return letter_feed
    return root_feed

  monkeypatch.setattr(client, "fetch_feed", fake_fetch)

  result = client.browse_letter("C")
  assert [entry.id for entry in result.entries] == ["author-1"]


def test_calibre_opds_browse_letter_filters_when_missing_navigation(monkeypatch) -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  titles_feed = OPDSFeed(
    id="catalog",
    title="Browse Titles",
    entries=[
      OPDSEntry(id="book-1", title="The Moon is a Harsh Mistress"),
      OPDSEntry(id="book-2", title="Another Story"),
    ],
    links={},
  )

  def fake_fetch(href=None, params=None):
    return titles_feed

  monkeypatch.setattr(client, "fetch_feed", fake_fetch)

  result = client.browse_letter("M")
  assert [entry.id for entry in result.entries] == ["book-1"]


def test_calibre_opds_browse_letter_collects_paginated_entries(monkeypatch) -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  first_page = OPDSFeed(
    id="catalog",
    title="Browse Titles",
    entries=[
      OPDSEntry(id="book-1", title="Ryan's First Adventure"),
      OPDSEntry(id="book-2", title="Another Tale"),
    ],
    links={"next": OPDSLink(href="http://example.com/catalog?page=2", rel="next")},
  )
  second_page = OPDSFeed(
    id="catalog",
    title="Browse Titles",
    entries=[OPDSEntry(id="book-3", title="Return of Ryan")],
    links={},
  )

  def fake_fetch(href=None, params=None):
    if not href:
      return first_page
    if href == "http://example.com/catalog?page=2":
      return second_page
    return first_page

  monkeypatch.setattr(client, "fetch_feed", fake_fetch)

  result = client.browse_letter("R")
  assert [entry.id for entry in result.entries] == ["book-1", "book-3"]


def test_calibre_opds_browse_letter_collects_paginated_navigation(monkeypatch) -> None:
  client = CalibreOPDSClient("http://example.com/catalog")
  root_feed = OPDSFeed(
    id="catalog",
    title="Browse Authors",
    entries=[
      OPDSEntry(
        id="nav-a",
        title="A",
        links=[
          OPDSLink(
            href="http://example.com/catalog/authors/a",
            rel="http://opds-spec.org/navigation",
            type="application/atom+xml;profile=opds-catalog",
          )
        ],
      ),
      OPDSEntry(
        id="nav-r",
        title="R",
        links=[
          OPDSLink(
            href="http://example.com/catalog/authors/r",
            rel="http://opds-spec.org/navigation",
            type="application/atom+xml;profile=opds-catalog",
          )
        ],
      ),
    ],
    links={},
  )
  letter_feed = OPDSFeed(
    id="authors-r",
    title="Authors — R",
    entries=[
      OPDSEntry(id="author-1", title="Ryan, Alice"),
    ],
    links={"next": OPDSLink(href="http://example.com/catalog/authors/r?page=2", rel="next")},
  )
  letter_page_two = OPDSFeed(
    id="authors-r",
    title="Authors — R",
    entries=[OPDSEntry(id="author-2", title="Ryan, Bob")],
    links={},
  )

  def fake_fetch(href=None, params=None):
    if not href:
      return root_feed
    if href == "http://example.com/catalog/authors/r":
      return letter_feed
    if href == "http://example.com/catalog/authors/r?page=2":
      return letter_page_two
    return root_feed

  monkeypatch.setattr(client, "fetch_feed", fake_fetch)

  result = client.browse_letter("R")
  assert [entry.id for entry in result.entries] == ["author-1", "author-2"]
