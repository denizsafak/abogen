(function () {
  const root = document.querySelector('[data-override-root]');
  if (!root) {
    return;
  }

  const previewUrl = root.dataset.previewUrl || "";
  const defaultLanguage = root.dataset.language || "a";
  const table = root.querySelector('[data-role="override-table"]');
  const rows = table ? Array.from(table.querySelectorAll('[data-role="override-row"]')) : [];
  const filterInput = root.querySelector('[data-role="override-filter"]');
  const filterClearButton = root.querySelector('[data-role="override-filter-clear"]');
  const filterEmptyMessage = root.querySelector('[data-role="filter-empty"]');

  function base64ToBlob(base64, mimeType) {
    const binary = atob(base64);
    const length = binary.length;
    const bytes = new Uint8Array(length);
    for (let index = 0; index < length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Blob([bytes], { type: mimeType });
  }

  function getControl(form, selector) {
    if (!form) {
      return null;
    }
    const direct = form.querySelector(selector);
    if (direct) {
      return direct;
    }
    if (!form.id) {
      return null;
    }
    return root.querySelector(`${selector}[form="${form.id}"]`) || document.querySelector(`${selector}[form="${form.id}"]`);
  }

  function resetPreview(container) {
    if (!container) {
      return;
    }
    const messageEl = container.querySelector('[data-role="preview-message"]');
    const audioEl = container.querySelector('[data-role="preview-audio"]');
    if (messageEl) {
      messageEl.textContent = "";
      messageEl.removeAttribute('data-state');
    }
    if (audioEl) {
      const priorUrl = audioEl.dataset.objectUrl;
      if (priorUrl) {
        URL.revokeObjectURL(priorUrl);
        delete audioEl.dataset.objectUrl;
      }
      audioEl.pause();
      audioEl.removeAttribute('src');
      audioEl.hidden = true;
    }
  }

  function buildPreviewPayload(form) {
    if (!form) {
      return null;
    }
    const tokenInput = getControl(form, 'input[name="token"]');
    const pronunciationInput = getControl(form, 'input[name="pronunciation"]');
    const voiceSelect = getControl(form, 'select[name="voice"]');
    const languageInput = getControl(form, 'input[name="lang"]');

    const token = tokenInput && 'value' in tokenInput ? tokenInput.value.trim() : "";
    const pronunciation = pronunciationInput && 'value' in pronunciationInput ? pronunciationInput.value.trim() : "";
    const voice = voiceSelect && 'value' in voiceSelect ? voiceSelect.value.trim() : "";
    const language = languageInput && 'value' in languageInput ? languageInput.value.trim() : defaultLanguage;

    if (!token && !pronunciation) {
      return null;
    }
    return {
      token,
      pronunciation,
      voice,
      language,
    };
  }

  async function requestPreview(button) {
    if (!previewUrl) {
      return;
    }
    const formId = button.dataset.formId || "";
    const form = formId ? document.getElementById(formId) : button.closest('form');
    const container = button.closest('[data-role="preview-container"]');
    const messageEl = container ? container.querySelector('[data-role="preview-message"]') : null;
    const audioEl = container ? container.querySelector('[data-role="preview-audio"]') : null;

    resetPreview(container);

    const payload = buildPreviewPayload(form);
    if (!payload) {
      if (messageEl) {
        messageEl.textContent = "Enter a token or pronunciation first.";
        messageEl.dataset.state = "error";
      }
      return;
    }

    button.disabled = true;
    button.setAttribute('data-loading', 'true');

    try {
      const response = await fetch(previewUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const contentType = response.headers.get('Content-Type') || '';
      let data = null;
      if (contentType.includes('application/json')) {
        try {
          data = await response.json();
        } catch (parseError) {
          if (!response.ok) {
            throw new Error('Preview failed.');
          }
          throw parseError instanceof Error ? parseError : new Error('Preview failed.');
        }
      } else {
        if (!response.ok) {
          const fallback = await response.text().catch(() => '');
          throw new Error(fallback || 'Preview failed.');
        }
        throw new Error('Preview failed.');
      }

      if (!response.ok || (data && data.error)) {
        throw new Error((data && data.error) || 'Preview failed.');
      }
      if (!data || typeof data !== 'object') {
        throw new Error('Preview failed.');
      }
      if (!data.audio_base64) {
        throw new Error('Preview did not return audio.');
      }

      if (audioEl) {
        const blob = base64ToBlob(data.audio_base64, 'audio/wav');
        const objectUrl = URL.createObjectURL(blob);
        audioEl.src = objectUrl;
        audioEl.dataset.objectUrl = objectUrl;
        audioEl.hidden = false;
        audioEl.load();
        audioEl.play().catch(() => {
          /* playback might require user interaction; ignore */
        });
      }

      if (messageEl) {
        messageEl.textContent = data.normalized_text || data.text || 'Preview ready.';
        messageEl.dataset.state = "success";
      }
    } catch (error) {
      if (messageEl) {
        messageEl.textContent = error instanceof Error ? error.message : 'Preview failed.';
        messageEl.dataset.state = "error";
      }
    } finally {
      button.disabled = false;
      button.removeAttribute('data-loading');
    }
  }

  function attachPreviewHandlers() {
    const previewButtons = root.querySelectorAll('[data-role="preview-button"]');
    previewButtons.forEach((button) => {
      button.addEventListener('click', () => {
        requestPreview(button);
      });
    });
  }

  function applyFilter() {
    if (!filterInput || rows.length === 0) {
      return;
    }
    const term = filterInput.value.trim().toLowerCase();
    let visibleCount = 0;
    rows.forEach((row) => {
      const token = row.dataset.token || "";
      const pronunciationInput = row.querySelector('input[name="pronunciation"]');
      const voiceSelect = row.querySelector('select[name="voice"]');

      const pronunciationValue = pronunciationInput && 'value' in pronunciationInput
        ? pronunciationInput.value.trim().toLowerCase()
        : "";
      const voiceOption = voiceSelect && 'selectedIndex' in voiceSelect && voiceSelect.selectedIndex >= 0
        ? voiceSelect.options[voiceSelect.selectedIndex]
        : null;
      const voiceValue = voiceOption && voiceOption.textContent
        ? voiceOption.textContent.trim().toLowerCase()
        : "";

      if (!term || token.includes(term) || pronunciationValue.includes(term) || voiceValue.includes(term)) {
        row.hidden = false;
        visibleCount += 1;
      } else {
        row.hidden = true;
      }
    });

    if (filterEmptyMessage) {
      filterEmptyMessage.hidden = visibleCount !== 0;
    }
  }

  if (filterInput) {
    filterInput.addEventListener('input', applyFilter);
  }

  if (filterClearButton && filterInput) {
    filterClearButton.addEventListener('click', () => {
      filterInput.value = "";
      applyFilter();
      filterInput.focus();
    });
  }

  if (table) {
    table.addEventListener('input', (event) => {
      const target = event.target;
      if (target && (target.matches('input[name="pronunciation"]') || target.matches('select[name="voice"]'))) {
        applyFilter();
      }
    });
    table.addEventListener('change', (event) => {
      const target = event.target;
      if (target && target.matches('select[name="voice"]')) {
        applyFilter();
      }
    });
  }

  attachPreviewHandlers();
  applyFilter();
})();
