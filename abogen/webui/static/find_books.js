const modal = document.querySelector('[data-role="opds-modal"]');
const browser = modal?.querySelector('[data-role="opds-browser"]') || null;

if (modal && browser) {
  const statusEl = browser.querySelector('[data-role="opds-status"]');
  const resultsEl = browser.querySelector('[data-role="opds-results"]');
  const navEl = browser.querySelector('[data-role="opds-nav"]');
  const navBottomEl = browser.querySelector('[data-role="opds-nav-bottom"]');
  const alphaPickerEl = browser.querySelector('[data-role="opds-alpha-picker"]');
  const tabsEl = modal.querySelector('[data-role="opds-tabs"]');
  const searchForm = modal.querySelector('[data-role="opds-search"]');
  const searchInput = searchForm?.querySelector('input[name="q"]');
  const refreshButton = searchForm?.querySelector('[data-action="opds-refresh"]');
  const openButtons = document.querySelectorAll('[data-action="open-opds-modal"]');
  const closeTargets = modal.querySelectorAll('[data-role="opds-modal-close"]');

  const TabIds = {
    ROOT: 'root',
    SEARCH: 'search',
    CUSTOM: 'custom',
  };

  const EntryTypes = {
    BOOK: 'book',
    NAVIGATION: 'navigation',
    OTHER: 'other',
  };

  const LETTER_ALL = 'ALL';
  const LETTER_NUMERIC = '#';
  const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

  const state = {
    query: '',
    currentHref: '',
    activeTab: TabIds.ROOT,
    tabs: [],
    tabsReady: false,
    requestToken: 0,
    feedTitle: '',
    lastEntries: [],
    activeLetter: LETTER_ALL,
    availableLetters: new Set(),
    totalStats: null,
    filteredStats: null,
    status: { message: '', level: null },
    baseStatus: null,
    lastContextKey: '',
    currentLinks: {},
    alphabetBaseHref: '',
  };

  let isOpen = false;
  let lastTrigger = null;

  const truncate = (text, limit = 160) => {
    if (!text || typeof text !== 'string') {
      return '';
    }
    if (text.length <= limit) {
      return text;
    }
    return `${text.slice(0, limit - 1).trim()}…`;
  };

  const formatAuthors = (authors) => {
    if (!Array.isArray(authors) || !authors.length) {
      return '';
    }
    return authors.filter((author) => !!author).join(', ');
  };

  const formatSeriesIndex = (position) => {
    if (position === null || position === undefined) {
      return '';
    }
    const numeric = Number(position);
    if (Number.isFinite(numeric)) {
      if (Math.abs(numeric - Math.round(numeric)) < 0.01) {
        return String(Math.round(numeric));
      }
      return numeric.toLocaleString(undefined, {
        minimumFractionDigits: 1,
        maximumFractionDigits: 2,
      });
    }
    if (typeof position === 'string') {
      const trimmed = position.trim();
      if (trimmed) {
        return trimmed;
      }
    }
    return '';
  };

  const formatSeriesLabel = (entry) => {
    if (!entry) {
      return '';
    }
    const rawSeries = typeof entry.series === 'string' ? entry.series.trim() : '';
    const rawIndex =
      entry.series_index ??
      entry.seriesIndex ??
      entry.series_position ??
      entry.seriesPosition ??
      entry.book_number ??
      entry.bookNumber ??
      null;
    const indexLabel = formatSeriesIndex(rawIndex);
    if (rawSeries && indexLabel) {
      return `${rawSeries} · Book ${indexLabel}`;
    }
    if (rawSeries) {
      return rawSeries;
    }
    if (indexLabel) {
      return `Book ${indexLabel}`;
    }
    return '';
  };

  const deriveBrowseMode = () => {
    const title = (state.feedTitle || '').toLowerCase();
    if (!title) {
      return 'generic';
    }
    if (title.includes('author')) {
      return 'author';
    }
    if (title.includes('series')) {
      return 'series';
    }
    if (title.includes('title')) {
      return 'title';
    }
    if (title.includes('books')) {
      return 'title';
    }
    return 'generic';
  };

  const stripLeadingArticle = (text) => text.replace(/^(?:the|a|an)\s+/i, '').trim();

  const extractAlphabetSource = (entry) => {
    if (!entry) {
      return '';
    }
    const mode = deriveBrowseMode();
    if (mode === 'author') {
      if (Array.isArray(entry.authors) && entry.authors.length) {
        return entry.authors[0] || '';
      }
    }
    if (mode === 'series' && entry.series) {
      return entry.series;
    }
    if (entry.title) {
      return entry.title;
    }
    if (entry.series) {
      return entry.series;
    }
    const navLink = findNavigationLink(entry);
    if (navLink?.title) {
      return navLink.title;
    }
    return '';
  };

  const deriveAlphabetKey = (entry) => {
    const mode = deriveBrowseMode();
    let source = (extractAlphabetSource(entry) || '').trim();
    if (!source) {
      return '';
    }
    if (mode === 'author') {
      if (source.includes(',')) {
        source = source.split(',')[0];
      } else {
        const parts = source.split(/\s+/);
        if (parts.length > 1) {
          source = parts[parts.length - 1];
        }
      }
    } else if (mode === 'title') {
      source = stripLeadingArticle(source);
    }
    source = source.replace(/^[^\p{L}\p{N}]+/u, '');
    return source;
  };

  const deriveAlphabetLetter = (entry) => {
    const key = deriveAlphabetKey(entry);
    if (!key) {
      return LETTER_NUMERIC;
    }
    const initial = key.charAt(0).toUpperCase();
    if (initial >= 'A' && initial <= 'Z') {
      return initial;
    }
    return LETTER_NUMERIC;
  };

  const collectAlphabetCounts = (entries) => {
    const counts = new Map();
    if (!Array.isArray(entries)) {
      return counts;
    }
    entries.forEach((entry) => {
      const letter = deriveAlphabetLetter(entry);
      counts.set(letter, (counts.get(letter) || 0) + 1);
    });
    return counts;
  };

  const detectEntryType = (entry, navigationLink) => {
    if (!entry) {
      return EntryTypes.OTHER;
    }
    const downloadLink = entry.download && entry.download.href ? entry.download.href : null;
    if (downloadLink) {
      return EntryTypes.BOOK;
    }
    const navLink = navigationLink === undefined ? findNavigationLink(entry) : navigationLink;
    if (navLink && navLink.href) {
      return EntryTypes.NAVIGATION;
    }
    return EntryTypes.OTHER;
  };

  const computeEntryStats = (entries) => {
    const stats = {
      [EntryTypes.BOOK]: 0,
      [EntryTypes.NAVIGATION]: 0,
      [EntryTypes.OTHER]: 0,
    };
    if (!Array.isArray(entries)) {
      return stats;
    }
    entries.forEach((entry) => {
      const type = detectEntryType(entry);
      stats[type] += 1;
    });
    return stats;
  };

  const shouldShowAlphabetPicker = (entries, stats) => {
    if (!alphaPickerEl || state.query) {
      return false;
    }
    if (!Array.isArray(entries) || entries.length === 0) {
      return false;
    }
    return true;
  };

  const refreshAlphabetActiveState = () => {
    if (!alphaPickerEl) {
      return;
    }
    const buttons = alphaPickerEl.querySelectorAll('button[data-letter]');
    buttons.forEach((button) => {
      const value = button.dataset.letter || LETTER_ALL;
      const isActive = value === state.activeLetter;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  };

  const describeAlphabetLetter = (letter) => {
    if (letter === LETTER_ALL) {
      return 'all entries';
    }
    if (letter === LETTER_NUMERIC) {
      return 'numbers or symbols';
    }
    return `letter ${letter}`;
  };

  const updateAlphabetPicker = (entries, { reset = false, stats = null } = {}) => {
    if (!alphaPickerEl) {
      return;
    }
    const list = Array.isArray(entries) ? entries : [];
    if (reset) {
      state.activeLetter = LETTER_ALL;
    }
    const counts = collectAlphabetCounts(list);
    state.availableLetters = new Set(counts.keys());
    const shouldShow = shouldShowAlphabetPicker(list, stats);
    if (!shouldShow) {
      alphaPickerEl.innerHTML = '';
      alphaPickerEl.hidden = true;
      state.activeLetter = LETTER_ALL;
      return;
    }

    alphaPickerEl.hidden = false;
    alphaPickerEl.innerHTML = '';
    const letters = [LETTER_ALL, ...ALPHABET, LETTER_NUMERIC];
    letters.forEach((letter) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'opds-alpha-picker__button';
      button.dataset.letter = letter;
      button.textContent = letter === LETTER_ALL ? 'All' : letter === LETTER_NUMERIC ? '# / 0-9' : letter;
      const enabledCount = letter === LETTER_ALL ? list.length : counts.get(letter) || 0;
      button.title = `Show entries for ${describeAlphabetLetter(letter)} (${enabledCount} in view)`;
      button.addEventListener('click', () => {
        handleAlphabetSelect(letter).catch((error) => {
          console.error('Alphabet picker failed', error);
        });
      });
      alphaPickerEl.appendChild(button);
    });
    refreshAlphabetActiveState();
  };

  const handleAlphabetSelect = async (letter) => {
    const normalized = letter || LETTER_ALL;
    if (normalized === LETTER_ALL) {
      state.activeLetter = LETTER_ALL;
      refreshAlphabetActiveState();
      const startLink = resolveRelLink(state.currentLinks, 'start') || resolveRelLink(state.currentLinks, '/start');
      const upLink = resolveRelLink(state.currentLinks, 'up') || resolveRelLink(state.currentLinks, '/up');
      const baseHref = startLink?.href || state.alphabetBaseHref || upLink?.href || state.currentHref || '';
      await loadFeed({ href: baseHref, query: '', letter: '', activeTab: baseHref ? TabIds.CUSTOM : TabIds.ROOT, updateTabs: true });
      return;
    }

    state.activeLetter = normalized;
    refreshAlphabetActiveState();
    const startLink = resolveRelLink(state.currentLinks, 'start') || resolveRelLink(state.currentLinks, '/start');
    const baseHref = startLink?.href || state.alphabetBaseHref || state.currentHref || '';
    await loadFeed({ href: baseHref, query: '', letter: normalized, activeTab: TabIds.CUSTOM, updateTabs: true });
  };

  const applyAlphabetFilter = (entries) => {
    if (!Array.isArray(entries) || !entries.length) {
      return [];
    }
    if (state.activeLetter === LETTER_ALL) {
      return entries.slice();
    }
    return entries.filter((entry) => {
      const letter = deriveAlphabetLetter(entry);
      if (state.activeLetter === LETTER_NUMERIC) {
        return letter === LETTER_NUMERIC;
      }
      return letter === state.activeLetter;
    });
  };

  const setEntries = (entries, { resetAlphabet = false, activeLetter = null } = {}) => {
    const list = Array.isArray(entries) ? entries.slice() : [];
    state.lastEntries = list;
    const totalStats = computeEntryStats(list);
    state.totalStats = totalStats;
    if (resetAlphabet) {
      state.activeLetter = LETTER_ALL;
    } else if (activeLetter && activeLetter !== LETTER_ALL) {
      state.activeLetter = activeLetter;
    }
    const filtered = applyAlphabetFilter(list);
    const filteredStats = renderEntries(filtered);
    state.filteredStats = filteredStats;
    updateAlphabetPicker(list, { reset: resetAlphabet, stats: totalStats });
    return { stats: totalStats, filteredStats };
  };

  const setStatus = (message, level, { persist = false } = {}) => {
    if (!statusEl) {
      return;
    }
    statusEl.textContent = message || '';
    if (level) {
      statusEl.dataset.state = level;
    } else {
      delete statusEl.dataset.state;
    }
    state.status = { message: message || '', level: level || null };
    if (persist) {
      state.baseStatus = { ...state.status };
    }
  };

  const clearStatus = () => setStatus('', null);

  const restoreBaseStatus = () => {
    if (state.baseStatus) {
      setStatus(state.baseStatus.message, state.baseStatus.level);
    } else {
      clearStatus();
    }
  };

  const focusSearch = () => {
    if (!searchInput) {
      return;
    }
    window.requestAnimationFrame(() => {
      try {
        searchInput.focus({ preventScroll: true });
      } catch (error) {
        // Ignore focus issues
      }
    });
  };

  const resolveRelLink = (links, rel) => {
    if (!links) {
      return null;
    }
    if (links[rel]) {
      return links[rel];
    }
    const key = Object.keys(links).find((entry) => entry === rel || entry.endsWith(rel));
    return key ? links[key] : null;
  };

  const findNavigationLink = (entry) => {
    if (!entry || !Array.isArray(entry.links)) {
      return null;
    }
    const candidates = entry.links.filter((link) => link && link.href);
    return (
      candidates.find((link) => {
        const rel = (link.rel || '').toLowerCase();
        const type = (link.type || '').toLowerCase();
        if (!link.href) {
          return false;
        }
        if (rel.includes('acquisition')) {
          return false;
        }
        if (rel === 'self') {
          return false;
        }
        if (type.includes('opds-catalog')) {
          return true;
        }
        if (rel.includes('subsection') || rel.includes('collection')) {
          return true;
        }
        if (rel.startsWith('http://opds-spec.org/sort') || rel.startsWith('http://opds-spec.org/group')) {
          return true;
        }
        return false;
      }) || null
    );
  };

  const resolveTabIdForHref = (href) => {
    if (!href) {
      return TabIds.ROOT;
    }
    const matching = state.tabs.find((tab) => tab.href === href);
    return matching ? matching.id : null;
  };

  const buildTabsFromFeed = (feed) => {
    if (!feed || !Array.isArray(feed.entries)) {
      return;
    }
    const seen = new Set();
    const nextTabs = [];
    feed.entries.forEach((entry) => {
      const navLink = findNavigationLink(entry);
      if (!navLink || !navLink.href) {
        return;
      }
      if (seen.has(navLink.href)) {
        return;
      }
      seen.add(navLink.href);
      const label = entry.title || navLink.title || 'Catalog view';
      nextTabs.push({
        id: navLink.href,
        label,
        href: navLink.href,
      });
    });
    state.tabs = nextTabs;
    state.tabsReady = true;
    renderTabs();
  };

  const renderTabs = () => {
    if (!tabsEl) {
      return;
    }
    tabsEl.innerHTML = '';
    const tabs = [];
    tabs.push({ id: TabIds.ROOT, label: 'Catalog home', href: '' });
    state.tabs.forEach((tab) => tabs.push(tab));
    if (state.activeTab === TabIds.SEARCH && state.query) {
      tabs.push({
        id: TabIds.SEARCH,
        label: `Search: "${truncate(state.query, 32)}"`,
        href: '',
        isSearch: true,
      });
    }
    tabs.forEach((tab) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'opds-tab';
      if (tab.isSearch) {
        button.classList.add('opds-tab--search');
      }
      if (state.activeTab === tab.id || (tab.id !== TabIds.SEARCH && state.activeTab === tab.href)) {
        button.classList.add('is-active');
      }
      button.textContent = tab.label;
      button.addEventListener('click', () => {
        if (tab.id === TabIds.SEARCH) {
          loadFeed({ href: '', query: state.query, activeTab: TabIds.SEARCH });
          return;
        }
        if (tab.id === TabIds.ROOT) {
          loadFeed({ href: '', query: '', activeTab: TabIds.ROOT, updateTabs: true });
          return;
        }
        loadFeed({ href: tab.href, query: '', activeTab: tab.id });
      });
      tabsEl.appendChild(button);
    });
    tabsEl.classList.toggle('is-empty', tabs.length <= 1);
  };

  const renderNav = (links) => {
    const targets = [navEl, navBottomEl].filter(Boolean);
    if (!targets.length) {
      return;
    }
    targets.forEach((el) => {
      el.innerHTML = '';
    });

    const descriptors = [
      { key: 'up', label: 'Up one level' },
      { key: 'previous', label: 'Previous page' },
      { key: 'next', label: 'Next page' },
    ];
    descriptors.forEach(({ key, label }) => {
      if (state.activeLetter !== LETTER_ALL && key !== 'up') {
        return;
      }
      const link = resolveRelLink(links, key) || resolveRelLink(links, `/${key}`);
      const hasLink = Boolean(link && link.href);

      if (!hasLink && key !== 'previous') {
        return;
      }

      targets.forEach((targetEl) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'button button--ghost';
        button.textContent = label;

        if (hasLink) {
          button.addEventListener('click', () => {
            const targetQuery = key === 'up' ? '' : state.query;
            const tabId = resolveTabIdForHref(link.href);
            loadFeed({ href: link.href, query: targetQuery, activeTab: tabId || (targetQuery ? TabIds.SEARCH : TabIds.CUSTOM) });
          });
        } else if (key === 'previous') {
          button.disabled = true;
          button.setAttribute('aria-disabled', 'true');
        }
        targetEl.appendChild(button);
      });
    });

    targets.forEach((el) => {
      el.hidden = !el.childElementCount;
    });
  };

  const createEntry = (entry) => {
    const item = document.createElement('li');
    item.className = 'opds-browser__entry';

    const header = document.createElement('div');
    header.className = 'opds-browser__entry-head';

    const title = document.createElement('h3');
    title.className = 'opds-browser__title';
    const positionLabel = Number.isFinite(entry?.position) ? Number(entry.position) : null;
    const baseTitle = entry.title || 'Untitled';
    title.textContent = positionLabel !== null ? `${positionLabel}. ${baseTitle}` : baseTitle;
    header.appendChild(title);

    const authors = formatAuthors(entry.authors);
    if (authors) {
      const meta = document.createElement('p');
      meta.className = 'opds-browser__meta';
      meta.textContent = authors;
      header.appendChild(meta);
    }

    const seriesMetaText = formatSeriesLabel(entry);
    if (seriesMetaText) {
      const seriesMeta = document.createElement('p');
      seriesMeta.className = 'opds-browser__meta';
      seriesMeta.textContent = seriesMetaText;
      header.appendChild(seriesMeta);
    }

    if (entry.rating !== null && entry.rating !== undefined && entry.rating !== '') {
      const ratingMeta = document.createElement('p');
      ratingMeta.className = 'opds-browser__meta';
      const ratingMax = entry.rating_max ?? entry.ratingMax ?? 5;
      ratingMeta.textContent = `Rating: ${entry.rating}${ratingMax ? ` / ${ratingMax}` : ''}`;
      header.appendChild(ratingMeta);
    }

    if (Array.isArray(entry.tags) && entry.tags.length > 0) {
      const tagsMeta = document.createElement('p');
      tagsMeta.className = 'opds-browser__meta';
      tagsMeta.textContent = `Tags: ${entry.tags.join(', ')}`;
      header.appendChild(tagsMeta);
    }

    item.appendChild(header);

    const summarySource = entry.summary || entry?.alternate?.title || entry?.download?.title || '';
    if (summarySource) {
      const summary = document.createElement('p');
      summary.className = 'opds-browser__summary';
      summary.textContent = truncate(summarySource, 420);
      item.appendChild(summary);
    }

    const actions = document.createElement('div');
    actions.className = 'opds-browser__actions';

    const downloadLink = entry.download && entry.download.href ? entry.download.href : null;
    const alternateLink = entry.alternate && entry.alternate.href ? entry.alternate.href : null;
    const navigationLink = findNavigationLink(entry);
    const entryType = detectEntryType(entry, navigationLink);

    if (entryType === EntryTypes.NAVIGATION && navigationLink) {
      item.classList.add('opds-browser__entry--navigation');
    }

    if (entryType === EntryTypes.BOOK) {
      const queueButton = document.createElement('button');
      queueButton.type = 'button';
      queueButton.className = 'button';
      queueButton.textContent = 'Configure conversion';
      queueButton.addEventListener('click', () => importEntry(entry, queueButton));
      actions.appendChild(queueButton);
    } else if (entryType === EntryTypes.NAVIGATION && navigationLink) {
      const browseButton = document.createElement('button');
      browseButton.type = 'button';
      browseButton.className = 'button button--ghost';
      browseButton.textContent = 'Browse view';
      browseButton.addEventListener('click', () => {
        clearStatus();
        const tabId = resolveTabIdForHref(navigationLink.href);
        loadFeed({ href: navigationLink.href, query: '', activeTab: tabId || TabIds.CUSTOM });
      });
      actions.appendChild(browseButton);
    }

    if (alternateLink && entryType !== EntryTypes.NAVIGATION) {
      const previewLink = document.createElement('a');
      previewLink.className = 'button button--ghost';
      previewLink.href = alternateLink;
      previewLink.target = '_blank';
      previewLink.rel = 'noreferrer';
      previewLink.textContent = 'Open in Calibre';
      actions.appendChild(previewLink);
    }

    if (!actions.childElementCount) {
      const fallback = document.createElement('span');
      fallback.className = 'opds-browser__hint';
      fallback.textContent = 'No downloadable formats exposed.';
      actions.appendChild(fallback);
    }

    item.appendChild(actions);
    return { element: item, type: entryType };
  };

  const renderEntries = (entries) => {
    if (!resultsEl) {
      return { [EntryTypes.BOOK]: 0, [EntryTypes.NAVIGATION]: 0, [EntryTypes.OTHER]: 0 };
    }
    resultsEl.innerHTML = '';
    const list = Array.isArray(entries) ? entries : [];
    if (!list.length) {
      const empty = document.createElement('li');
      empty.className = 'opds-browser__empty';
      if (state.activeLetter !== LETTER_ALL) {
        empty.textContent = `No entries start with ${describeAlphabetLetter(state.activeLetter)}.`;
      } else if (state.query) {
        empty.textContent = 'No results returned for this view yet.';
      } else {
        empty.textContent = 'No catalog entries found here yet.';
      }
      resultsEl.appendChild(empty);
      return { [EntryTypes.BOOK]: 0, [EntryTypes.NAVIGATION]: 0, [EntryTypes.OTHER]: 0 };
    }
    const fragment = document.createDocumentFragment();
    const stats = {
      [EntryTypes.BOOK]: 0,
      [EntryTypes.NAVIGATION]: 0,
      [EntryTypes.OTHER]: 0,
    };
    list.forEach((entry) => {
      const { element, type } = createEntry(entry);
      stats[type] += 1;
      fragment.appendChild(element);
    });
    resultsEl.appendChild(fragment);
    return stats;
  };

  const importEntry = async (entry, trigger) => {
    if (!entry?.download?.href) {
      setStatus('This entry cannot be imported automatically.', 'error');
      return;
    }
    const button = trigger;
    const originalLabel = button ? button.textContent : '';
    if (button) {
      button.disabled = true;
      button.dataset.loading = 'true';
      button.textContent = 'Preparing…';
    }
    setStatus('Downloading book from Calibre. This can take a minute…', 'loading');
    try {
      const requestPayload = {
        href: entry.download.href,
        title: entry.title || '',
      };
      const metadata = {};
      if (entry.series) {
        metadata.series = entry.series;
        metadata.series_name = entry.series;
      }
      const seriesIndex = entry.series_index ?? entry.seriesIndex ?? null;
      if (seriesIndex !== null && seriesIndex !== undefined && seriesIndex !== '') {
        metadata.series_index = seriesIndex;
        metadata.series_position = seriesIndex;
        metadata.book_number = seriesIndex;
      }
      if (Array.isArray(entry.tags) && entry.tags.length > 0) {
        const tagsText = entry.tags.join(', ');
        metadata.tags = tagsText;
        metadata.keywords = tagsText;
        metadata.genre = tagsText;
      }
      if (typeof entry.summary === 'string' && entry.summary.trim()) {
        metadata.description = entry.summary;
        metadata.summary = entry.summary;
      }

      if (Array.isArray(entry.authors) && entry.authors.length > 0) {
        const authorsText = entry.authors.map((name) => String(name || '').trim()).filter(Boolean).join(', ');
        if (authorsText) {
          metadata.authors = authorsText;
          metadata.author = authorsText;
        }
      }

      if (typeof entry.subtitle === 'string' && entry.subtitle.trim()) {
        metadata.subtitle = entry.subtitle.trim();
      }
      if (entry.rating !== null && entry.rating !== undefined && entry.rating !== '') {
        metadata.rating = String(entry.rating);
      }
      if (entry.rating_max !== null && entry.rating_max !== undefined && entry.rating_max !== '') {
        metadata.rating_max = String(entry.rating_max);
      }
      if (entry.published) {
        metadata.published = entry.published;
        metadata.publication_date = entry.published;
        try {
          const publishedDate = new Date(entry.published);
          if (!Number.isNaN(publishedDate.getTime())) {
            const year = String(publishedDate.getUTCFullYear());
            metadata.publication_year = year;
            metadata.year = year;
          }
        } catch (error) {
          // Ignore invalid date parsing issues
        }
      }
      if (Object.keys(metadata).length > 0) {
        requestPayload.metadata = metadata;
      }
      const response = await fetch('/api/integrations/calibre-opds/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestPayload),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || 'Unable to queue this book.');
      }
      setStatus('Preparing the conversion wizard…', 'success');
      closeModal();
      const redirectUrl = payload.redirect_url || '';
      if (redirectUrl) {
        const wizard = window.AbogenWizard;
        if (wizard?.requestStep) {
          try {
            const target = new URL(redirectUrl, window.location.origin);
            if (payload.pending_id && !target.searchParams.has('pending_id')) {
              target.searchParams.set('pending_id', payload.pending_id);
            }
            target.searchParams.set('format', 'json');
            if (!target.searchParams.has('step')) {
              target.searchParams.set('step', 'book');
            }
            await wizard.requestStep(target.toString(), { method: 'GET' });
          } catch (wizardError) {
            console.error('Unable to open wizard via JSON payload', wizardError);
            window.location.assign(redirectUrl);
          }
        } else {
          window.location.assign(redirectUrl);
        }
      }

    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to queue this book.', 'error');
    } finally {
      if (button) {
        button.disabled = false;
        delete button.dataset.loading;
        if (originalLabel) {
          button.textContent = originalLabel;
        }
      }
    }
  };

  const loadFeed = async ({ href = '', query = '', letter = '', activeTab = null, updateTabs = false } = {}) => {
    const params = new URLSearchParams();
    const normalizedHref = href || '';
    const normalizedQuery = (query || '').trim();
    let normalizedLetter = (letter || '').trim();
    if (normalizedLetter === LETTER_ALL) {
      normalizedLetter = '';
    }
    if (normalizedQuery) {
      normalizedLetter = '';
    }
    if (normalizedLetter && normalizedLetter !== LETTER_NUMERIC) {
      normalizedLetter = normalizedLetter.toUpperCase();
    }
    if (normalizedHref) {
      params.set('href', normalizedHref);
    }
    if (normalizedQuery) {
      params.set('q', normalizedQuery);
    }
    if (!normalizedQuery && normalizedLetter) {
      params.set('letter', normalizedLetter);
    }

    const requestId = ++state.requestToken;
    setStatus('Loading catalog…', 'loading');

    try {
      const url = `/api/integrations/calibre-opds/feed${params.toString() ? `?${params.toString()}` : ''}`;
      const response = await fetch(url);
      const payload = await response.json();
      if (requestId !== state.requestToken) {
        return;
      }
      if (!response.ok) {
        throw new Error(payload.error || 'Unable to load the Calibre catalog.');
      }
      const feed = payload.feed || {};
      state.feedTitle = feed.title || '';
      state.currentHref = normalizedHref;
      state.currentLinks = feed.links || {};
      const selfLink = resolveRelLink(state.currentLinks, 'self');
      if (selfLink?.href) {
        state.currentHref = selfLink.href;
      }
      state.query = normalizedLetter ? '' : normalizedQuery;
      if (!normalizedLetter) {
        const startLink = resolveRelLink(state.currentLinks, 'start') || resolveRelLink(state.currentLinks, '/start');
        if (startLink?.href) {
          state.alphabetBaseHref = startLink.href;
        } else if (state.currentHref) {
          state.alphabetBaseHref = state.currentHref;
        }
      }
      if (typeof activeTab === 'string') {
        state.activeTab = activeTab;
      } else if (normalizedQuery) {
        state.activeTab = TabIds.SEARCH;
      } else if (normalizedLetter) {
        state.activeTab = TabIds.CUSTOM;
      } else if (normalizedHref) {
        state.activeTab = resolveTabIdForHref(normalizedHref) || TabIds.CUSTOM;
      } else {
        state.activeTab = TabIds.ROOT;
      }

      if (searchInput) {
        searchInput.value = state.query || '';
      }

      if (updateTabs || !state.tabsReady) {
        buildTabsFromFeed(feed);
      } else {
        renderTabs();
      }

      renderNav(feed.links);
      const { stats } = setEntries(feed.entries || [], {
        resetAlphabet: !normalizedLetter,
        activeLetter: normalizedLetter || null,
      });
      const books = stats?.[EntryTypes.BOOK] || 0;
      const views = stats?.[EntryTypes.NAVIGATION] || 0;

      if (normalizedLetter) {
        const letterDescription = describeAlphabetLetter(normalizedLetter);
        if (books && views) {
          setStatus(
            `Showing ${books} book${books === 1 ? '' : 's'} and ${views} catalog view${views === 1 ? '' : 's'} for ${letterDescription}.`,
            'success',
            { persist: true },
          );
        } else if (books) {
          setStatus(`Found ${books} book${books === 1 ? '' : 's'} for ${letterDescription}.`, 'success', { persist: true });
        } else if (views) {
          setStatus(`Browse ${views} catalog view${views === 1 ? '' : 's'} for ${letterDescription}.`, 'info', { persist: true });
        } else {
          setStatus(`No catalog entries found for ${letterDescription}.`, 'info', { persist: true });
        }
        return;
      }

      if (normalizedQuery) {
        if (books) {
          setStatus(`Found ${books} book${books === 1 ? '' : 's'} for "${normalizedQuery}".`, 'success', { persist: true });
        } else if (views) {
          setStatus(
            `Browse ${views} catalog view${views === 1 ? '' : 's'} related to "${normalizedQuery}".`,
            'info',
            { persist: true },
          );
        } else {
          setStatus(`No results for "${normalizedQuery}".`, 'error', { persist: true });
        }
        return;
      }

      if (books && views) {
        setStatus(`Showing ${books} book${books === 1 ? '' : 's'} and ${views} catalog view${views === 1 ? '' : 's'}.`, 'success', { persist: true });
      } else if (books) {
        setStatus(`Found ${books} book${books === 1 ? '' : 's'} in this view.`, 'success', { persist: true });
      } else if (views) {
        setStatus(`Browse ${views} catalog view${views === 1 ? '' : 's'} to drill deeper.`, 'info', { persist: true });
      } else {
        setStatus('No catalog entries found here yet.', 'info', { persist: true });
      }
    } catch (error) {
      if (requestId !== state.requestToken) {
        return;
      }
      setStatus(error instanceof Error ? error.message : 'Unable to load the Calibre catalog.', 'error', { persist: true });
      setEntries([], { resetAlphabet: true });
      if (navEl) {
        navEl.innerHTML = '';
      }
      state.currentLinks = {};
    }
  };

  const openModal = (trigger) => {
    if (isOpen) {
      focusSearch();
      return;
    }
    isOpen = true;
    lastTrigger = trigger || null;
    modal.hidden = false;
    modal.dataset.open = 'true';
    document.body.classList.add('modal-open');
    focusSearch();
    loadFeed({ href: state.currentHref || '', query: state.query || '', activeTab: state.activeTab || TabIds.ROOT, updateTabs: !state.tabsReady });
  };

  const closeModal = () => {
    if (!isOpen) {
      return;
    }
    isOpen = false;
    modal.hidden = true;
    delete modal.dataset.open;
    document.body.classList.remove('modal-open');
    if (lastTrigger instanceof HTMLElement) {
      lastTrigger.focus({ preventScroll: true });
    }
  };

  const handleKeydown = (event) => {
    if (event.key === 'Escape' && isOpen) {
      event.preventDefault();
      closeModal();
    }
  };

  document.addEventListener('keydown', handleKeydown);

  openButtons.forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      openModal(button);
    });
  });

  closeTargets.forEach((target) => {
    target.addEventListener('click', (event) => {
      event.preventDefault();
      closeModal();
    });
  });

  modal.addEventListener('click', (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  if (searchForm && searchInput) {
    searchForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const query = searchInput.value.trim();
      if (!query) {
        loadFeed({ href: '', query: '', activeTab: TabIds.ROOT, updateTabs: true });
      } else {
        loadFeed({ href: '', query, activeTab: TabIds.SEARCH });
      }
    });
  }

  if (refreshButton && searchInput) {
    refreshButton.addEventListener('click', () => {
      searchInput.value = '';
      loadFeed({ href: '', query: '', activeTab: TabIds.ROOT, updateTabs: true });
    });
  }
}
