const initSpeakerConfigsPage = () => {
  const form = document.getElementById("speaker-config-form");
  if (!form) return;

  const rowsContainer = form.querySelector('[data-role="speaker-rows"]');
  const template = document.getElementById("speaker-row-template");
  const addButtons = form.querySelectorAll('[data-action="add-speaker"]');

  const ensureEmptyState = () => {
    if (!rowsContainer) return;
    const hasRows = rowsContainer.querySelector('[data-role="speaker-row"]');
    let emptyState = rowsContainer.querySelector('[data-role="empty-state"]');
    if (hasRows && emptyState) {
      emptyState.remove();
      emptyState = null;
    }
    if (!hasRows && !emptyState) {
      const placeholder = document.createElement("div");
      placeholder.className = "speaker-config-rows__empty";
      placeholder.dataset.role = "empty-state";
      placeholder.textContent = "No speakers yet. Add your first character.";
      rowsContainer.appendChild(placeholder);
    }
  };

  const hydrateRow = (fragment, key) => {
    const elements = fragment.querySelectorAll("[name], [id], label[for], [data-row-id]");
    elements.forEach((el) => {
      if (el.name) {
        el.name = el.name.replace(/__ROW__/g, key);
      }
      if (el.id) {
        el.id = el.id.replace(/__ROW__/g, key);
      }
      if (el.tagName === "LABEL") {
        const forValue = el.getAttribute("for");
        if (forValue) {
          el.setAttribute("for", forValue.replace(/__ROW__/g, key));
        }
      }
      if (el.dataset && el.dataset.rowId) {
        el.dataset.rowId = key;
      }
    });

    const hiddenId = fragment.querySelector(`input[name="speaker-${key}-id"]`);
    if (hiddenId && !hiddenId.value) {
      hiddenId.value = key;
    }
    const rowMarkers = fragment.querySelectorAll('input[name="speaker_rows"]');
    rowMarkers.forEach((marker) => {
      marker.value = key;
    });
  };

  const addRow = () => {
    if (!template || !rowsContainer) return;
    const key = `row-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    const fragment = template.content.cloneNode(true);
    hydrateRow(fragment, key);
    rowsContainer.appendChild(fragment);
    ensureEmptyState();
    const newRow = rowsContainer.querySelector(`[data-row-id="${key}"]`);
    if (newRow) {
      const input = newRow.querySelector("input[type=text]");
      if (input) {
        input.focus();
      }
    }
  };

  addButtons.forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      addRow();
    });
  });

  rowsContainer?.addEventListener("click", (event) => {
    const removeButton = event.target.closest('[data-action="remove-speaker"]');
    if (!removeButton) return;
    event.preventDefault();
    const row = removeButton.closest('[data-role="speaker-row"]');
    if (row) {
      row.remove();
      ensureEmptyState();
    }
  });

  ensureEmptyState();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initSpeakerConfigsPage, { once: true });
} else {
  initSpeakerConfigsPage();
}
