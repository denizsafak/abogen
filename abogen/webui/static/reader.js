const readerButtonRegistry = new WeakSet();
let initialized = false;
let readerModal = null;
let readerFrame = null;
let readerHint = null;
let readerTitle = null;
let readerTrigger = null;
let defaultReaderHint = "";

const resolveEventMatch = (event, selector) => {
  const target = event.target;
  if (target instanceof Element) {
    const match = target.closest(selector);
    if (match) {
      return match;
    }
  }
  const path = typeof event.composedPath === "function" ? event.composedPath() : [];
  for (const node of path) {
    if (node instanceof Element) {
      if (node.matches(selector)) {
        return node;
      }
      const match = node.closest(selector);
      if (match) {
        return match;
      }
    }
  }
  return null;
};

const closeReaderModal = () => {
  if (!readerModal) {
    return;
  }
  if (readerModal.hidden) {
    return;
  }
  readerModal.hidden = true;
  readerModal.removeAttribute("data-open");
  document.body.classList.remove("modal-open");
  if (readerFrame) {
    const frameWindow = readerFrame.contentWindow;
    if (frameWindow) {
      try {
        frameWindow.postMessage({ type: "abogen:reader:pause", currentTime: 0 }, window.location.origin);
      } catch (error) {
        // Ignore cross-origin messaging errors.
      }
    }
    window.setTimeout(() => {
      readerFrame.src = "about:blank";
    }, 75);
  }
  if (readerHint && defaultReaderHint) {
    readerHint.textContent = defaultReaderHint;
  }
  if (readerTitle) {
    readerTitle.textContent = "Read & listen";
  }
  if (readerTrigger instanceof HTMLElement) {
    try {
      readerTrigger.focus({ preventScroll: true });
    } catch (error) {
      // Ignore focus errors.
    }
  }
  readerTrigger = null;
};

const createBindReaderButtons = (openReaderModal) => {
  return (root) => {
    const context = root instanceof Element ? root : document;
    const buttons = context.querySelectorAll('[data-role="open-reader"]');
    buttons.forEach((button) => {
      if (!(button instanceof HTMLElement)) {
        return;
      }
      if (readerButtonRegistry.has(button)) {
        return;
      }
      button.addEventListener("click", (event) => {
        event.preventDefault();
        openReaderModal(button);
      });
      readerButtonRegistry.add(button);
    });
  };
};

export const initReaderUI = (options = {}) => {
  if (initialized) {
    return {
      bindReaderButtons: createBindReaderButtons((trigger) => {
        if (typeof options.onBeforeOpen === "function") {
          options.onBeforeOpen();
        }
        openReader(trigger, options);
      }),
      closeReaderModal,
    };
  }

  readerModal = document.querySelector('[data-role="reader-modal"]');
  readerFrame = readerModal?.querySelector('[data-role="reader-frame"]') || null;
  readerHint = readerModal?.querySelector('[data-role="reader-modal-hint"]') || null;
  readerTitle = readerModal?.querySelector('#reader-modal-title') || null;
  defaultReaderHint = readerHint?.textContent || "";

  const openReaderModal = (trigger) => {
    if (typeof options.onBeforeOpen === "function") {
      options.onBeforeOpen();
    }
    if (!(trigger instanceof HTMLElement)) {
      return;
    }
    const url = trigger.dataset.readerUrl || "";
    if (!url) {
      return;
    }
    if (!readerModal || !readerFrame) {
      window.open(url, "_blank", "noopener,noreferrer");
      return;
    }
    readerTrigger = trigger;
    const bookTitle = trigger.dataset.bookTitle || "";
    if (readerTitle) {
      readerTitle.textContent = bookTitle ? `${bookTitle} · reader` : "Read & listen";
    }
    if (readerHint) {
      readerHint.textContent = bookTitle
        ? `Preview ${bookTitle} directly in your browser.`
        : defaultReaderHint;
    }
    readerModal.hidden = false;
    readerModal.dataset.open = "true";
    document.body.classList.add("modal-open");
    readerFrame.src = url;
    try {
      readerFrame.focus({ preventScroll: true });
    } catch (error) {
      // Ignore focus errors.
    }
  };

  const bindReaderButtons = createBindReaderButtons(openReaderModal);
  bindReaderButtons();

  document.addEventListener("click", (event) => {
    const closeButton = resolveEventMatch(event, '[data-role="reader-modal-close"]');
    if (closeButton) {
      event.preventDefault();
      closeReaderModal();
      return;
    }
    const trigger = resolveEventMatch(event, '[data-role="open-reader"]');
    if (trigger instanceof HTMLElement) {
      event.preventDefault();
      openReaderModal(trigger);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeReaderModal();
    }
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    const fragment = event?.detail?.target;
    if (fragment instanceof Element) {
      bindReaderButtons(fragment);
    } else {
      bindReaderButtons();
    }
  });

  initialized = true;

  return {
    bindReaderButtons,
    closeReaderModal,
  };
};

const openReader = (trigger, options) => {
  if (typeof options.onBeforeOpen === "function") {
    options.onBeforeOpen();
  }
  if (!(trigger instanceof HTMLElement)) {
    return;
  }
  const url = trigger.dataset.readerUrl || "";
  if (!url) {
    return;
  }
  if (!readerModal || !readerFrame) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  readerTrigger = trigger;
  const bookTitle = trigger.dataset.bookTitle || "";
  if (readerTitle) {
    readerTitle.textContent = bookTitle ? `${bookTitle} · reader` : "Read & listen";
  }
  if (readerHint) {
    readerHint.textContent = bookTitle
      ? `Preview ${bookTitle} directly in your browser.`
      : defaultReaderHint;
  }
  readerModal.hidden = false;
  readerModal.dataset.open = "true";
  document.body.classList.add("modal-open");
  readerFrame.src = url;
  try {
    readerFrame.focus({ preventScroll: true });
  } catch (error) {
    // Ignore focus errors.
  }
};
