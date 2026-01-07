const prepareState = (window.AbogenPrepareState = window.AbogenPrepareState || {
  modalEventsBound: false,
});

const initPrepare = (root = document) => {
  const rootEl = root instanceof HTMLElement ? root : document;
  const form = rootEl.querySelector(".prepare-form") || document.querySelector(".prepare-form");
  if (!form) return;
  if (form.dataset.prepareInitialized === "true") {
    return;
  }
  form.dataset.prepareInitialized = "true";

  const wizardModal = document.querySelector('[data-role="wizard-modal"]');
  const uploadModal =
    document.querySelector('[data-role="new-job-modal"]') ||
    document.querySelector('[data-role="upload-modal"]');
  const openUploadTriggers = Array.from(document.querySelectorAll('[data-role="open-upload-modal"]'));

  const showWizardModal = () => {
    if (!wizardModal) return;
    wizardModal.hidden = false;
    wizardModal.dataset.open = "true";
    wizardModal.removeAttribute("aria-hidden");
    document.body.classList.add("modal-open");
  };

  const hideWizardModal = () => {
    if (!wizardModal) return;
    wizardModal.hidden = true;
    delete wizardModal.dataset.open;
    wizardModal.setAttribute("aria-hidden", "true");
  };

  const triggerUploadModal = () => {
    const existingTrigger = openUploadTriggers.find((button) => button !== null);
    if (existingTrigger) {
      existingTrigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      return;
    }
    if (!uploadModal) return;
    uploadModal.hidden = false;
    uploadModal.dataset.open = "true";
    document.body.classList.add("modal-open");
    const focusTarget = uploadModal.querySelector("#source_file") || uploadModal.querySelector("#source_text") || uploadModal;
    if (focusTarget instanceof HTMLElement) {
      focusTarget.focus({ preventScroll: true });
    }
  };

  showWizardModal();

  if (!prepareState.modalEventsBound) {
    prepareState.modalEventsBound = true;
    document.addEventListener("upload-modal:open", hideWizardModal);
    document.addEventListener("upload-modal:close", showWizardModal);
  }

  const parseJSONScript = (id) => {
    const el = document.getElementById(id);
    if (!el) return null;
    try {
      const content = el.textContent || "";
      return content ? JSON.parse(content) : null;
    } catch (error) {
      console.warn(`Failed to parse JSON script for ${id}`, error);
      return null;
    }
  };

  const voiceCatalog = parseJSONScript("voice-catalog-data") || [];
  const languageMap = parseJSONScript("voice-language-map") || {};
  const voiceCatalogMap = new Map(voiceCatalog.map((voice) => [voice.id, voice]));

  const sampleIndexState = new WeakMap();
  const speakerHints = new Map();

  const canonicalizeEntityKey = (value) => (value || "").toLowerCase().replace(/\s+/g, " ").trim();

  const readSpeakerSamples = (speakerItem) => {
    if (!speakerItem) return [];
    const template = speakerItem.querySelector('template[data-role="speaker-samples"]');
    if (!template) return [];
    let parsed = [];
    try {
      const raw = template.innerHTML || "[]";
      const data = JSON.parse(raw);
      if (Array.isArray(data)) {
        parsed = data;
      }
    } catch (error) {
      console.warn("Unable to parse speaker samples", error);
      return [];
    }

    const seen = new Set();
    const normalised = [];
    for (const entry of parsed) {
      let excerpt = "";
      let genderHint = "";
      if (typeof entry === "string") {
        excerpt = entry;
      } else if (entry && typeof entry === "object") {
        excerpt = String(entry.excerpt || "");
        genderHint = typeof entry.gender_hint === "string" ? entry.gender_hint : "";
      }
      const key = excerpt.trim();
      if (!key || seen.has(key)) {
        continue;
      }
      seen.add(key);
      normalised.push({ excerpt: key, genderHint });
    }
    return normalised;
  };

  const registerSpeakerHintFromNode = (node) => {
    if (!node) return;
    const nameNode = node.querySelector(".speaker-list__name");
    const label = nameNode?.textContent || "";
    const key = canonicalizeEntityKey(label);
    if (!key) return;
    const genderInput = node.querySelector('[data-role="gender-input"]');
    const voiceSelect = node.querySelector('[data-role="speaker-voice"]');
    const formulaInput = node.querySelector('[data-role="speaker-formula"]');
    let resolvedVoice = "";
    if (voiceSelect) {
      const selectedValue = voiceSelect.value || voiceSelect.dataset.prevManual || "";
      if (selectedValue && selectedValue !== "__custom_mix") {
        resolvedVoice = selectedValue;
      } else if (voiceSelect.dataset.defaultVoice) {
        resolvedVoice = voiceSelect.dataset.defaultVoice;
      } else if (form.dataset.baseVoice) {
        resolvedVoice = form.dataset.baseVoice;
      }
    } else if (form.dataset.baseVoice) {
      resolvedVoice = form.dataset.baseVoice;
    }
    if (!resolvedVoice && formulaInput?.value?.trim()) {
      const formula = formulaInput.value.trim();
      const firstTerm = formula.split("+")[0] || "";
      const [voiceId] = firstTerm.split("*");
      if (voiceId) {
        resolvedVoice = voiceId.trim();
      }
    }
    speakerHints.set(key, {
      gender: (genderInput?.value || "unknown").toLowerCase(),
      voice: resolvedVoice,
    });
  };

  const rebuildSpeakerHints = () => {
    speakerHints.clear();
    form.querySelectorAll(".speaker-list__item").forEach((item) => registerSpeakerHintFromNode(item));
  };

  const getPronunciationText = (container) => {
    if (!container) return "";
    const input = container.querySelector('[data-role="speaker-pronunciation"]');
    const raw = input?.value?.trim();
    if (raw) {
      return raw;
    }
    return (container.dataset.defaultPronunciation || "").trim();
  };

  const syncPronunciationPreview = (container) => {
    if (!container) return;
    const text = getPronunciationText(container);
    const previewButtons = container.querySelectorAll('[data-role="speaker-preview"][data-preview-source]');
    previewButtons.forEach((button) => {
      const source = button.dataset.previewSource;
      if (["pronunciation", "generated", "mix"].includes(source)) {
        button.dataset.previewText = text;
      }
    });
  };

  const setSpeakerSample = (speakerItem, index) => {
    if (!speakerItem) return;
    const samples = readSpeakerSamples(speakerItem);
    if (!samples.length) return;
    const maxIndex = samples.length;
    const normalisedIndex = ((index % maxIndex) + maxIndex) % maxIndex;
    sampleIndexState.set(speakerItem, normalisedIndex);
    const sample = samples[normalisedIndex];
    const article = speakerItem.querySelector('[data-role="speaker-sample"]');
    if (!article) return;
    const textNode = article.querySelector('[data-role="sample-text"]');
    const hintNode = article.querySelector('[data-role="sample-hint"]');
    if (textNode) {
      textNode.textContent = sample.excerpt;
    }
    if (hintNode) {
      if (sample.genderHint) {
        hintNode.hidden = false;
        hintNode.textContent = sample.genderHint;
      } else {
        hintNode.hidden = true;
        hintNode.textContent = "";
      }
    }
    const previewButton = article.querySelector('[data-role="speaker-preview"][data-preview-source="sample"]');
    if (previewButton) {
      previewButton.dataset.previewText = sample.excerpt;
    }
    const voiceBrowserButton = article.querySelector('[data-role="open-voice-browser"]');
    if (voiceBrowserButton) {
      voiceBrowserButton.dataset.sampleIndex = String(normalisedIndex);
    }
  };

  const initialiseSpeakerItem = (speakerItem) => {
    syncPronunciationPreview(speakerItem);
    const samples = readSpeakerSamples(speakerItem);
    if (samples.length) {
      setSpeakerSample(speakerItem, 0);
      const nextButton = speakerItem.querySelector('[data-role="speaker-next-sample"]');
      if (nextButton) {
        nextButton.disabled = samples.length <= 1;
      }
    }
  };

  const formatCustomMixLabel = (formula) => {
    if (!formula) return "Custom mix";
    const segments = formula
      .split("+")
      .map((segment) => segment.trim())
      .filter((segment) => segment.length);
    if (!segments.length) {
      return "Custom mix";
    }
    const parts = segments.map((segment) => {
      const [voiceIdRaw, weightRaw] = segment.split("*").map((token) => token.trim());
      const voiceId = voiceIdRaw || "";
      const voiceMeta = voiceCatalogMap.get(voiceId);
      const displayName = voiceMeta?.display_name || voiceId || "Voice";
      const weight = Number.parseFloat(weightRaw || "");
      if (!Number.isNaN(weight)) {
        return `${displayName} ${(weight * 100).toFixed(0)}%`;
      }
      return displayName;
    });
    return parts.join(" + ");
  };

  const ensureCustomMixOption = (select) => {
    if (!select) return null;
    let option = select.querySelector('option[data-role="custom-mix-option"]');
    if (!option) {
      option = document.createElement("option");
      option.value = "__custom_mix";
      option.dataset.role = "custom-mix-option";
      option.hidden = true;
      option.disabled = true;
      option.textContent = "Custom mix";
      const firstOptGroup = select.querySelector("optgroup");
      if (firstOptGroup) {
        select.insertBefore(option, firstOptGroup);
      } else {
        select.appendChild(option);
      }
    }
    return option;
  };

  const updateCustomMixOption = (select, formula) => {
    const option = ensureCustomMixOption(select);
    if (!option) return;
    if (formula) {
      option.hidden = false;
      option.disabled = false;
      option.textContent = formatCustomMixLabel(formula);
    } else {
      option.hidden = true;
      option.disabled = true;
      option.textContent = "Custom mix";
    }
  };

  const chapterRows = Array.from(form.querySelectorAll("[data-role=chapter-row]"));

  const setRowExpansion = (row, expanded) => {
    if (!row) return;
    const details = row.querySelector('[data-role="chapter-details"]');
    const toggle = row.querySelector('[data-role="chapter-toggle"]');
    const isExpanded = Boolean(expanded);
    row.dataset.expanded = isExpanded ? "true" : "false";
    if (details) {
      details.hidden = !isExpanded;
      details.setAttribute("aria-hidden", isExpanded ? "false" : "true");
    }
    if (toggle) {
      toggle.setAttribute("aria-expanded", isExpanded ? "true" : "false");
      toggle.setAttribute("aria-label", isExpanded ? "Hide chapter details" : "Show chapter details");
    }
  };

  const toggleRowExpansion = (row, force) => {
    if (!row) return;
    const current = row.dataset.expanded === "true";
    const next = typeof force === "boolean" ? force : !current;
    setRowExpansion(row, next);
  };

  const isRowEnabled = (row) => {
    const checkbox = row?.querySelector('[data-role="chapter-enabled"]');
    return checkbox ? checkbox.checked : true;
  };

  const updateRowState = (row) => {
    const enabled = row.querySelector('[data-role=chapter-enabled]');
  const inputs = Array.from(row.querySelectorAll("input[type=text], select, textarea"));
    const toggle = row.querySelector('[data-role="chapter-toggle"]');
    const isChecked = enabled ? enabled.checked : true;
    row.dataset.disabled = isChecked ? "false" : "true";

    inputs.forEach((input) => {
      if (input === enabled) return;
      input.disabled = !isChecked;
      if (!isChecked) {
        if (input.tagName === "SELECT") {
          input.dataset.prevValue = input.value;
          input.value = "__default";
        }
        if (input.dataset.role === "formula-input") {
          input.value = "";
          input.hidden = true;
          input.setAttribute("aria-hidden", "true");
        }
      } else if (input.tagName === "SELECT" && input.dataset.prevValue) {
        input.value = input.dataset.prevValue;
      }
    });

    const select = row.querySelector("select[data-role=voice-select]");
    toggleFormula(select);

    if (!isChecked) {
      setRowExpansion(row, false);
    }

    if (toggle) {
      toggle.disabled = !isChecked;
      toggle.setAttribute("aria-disabled", isChecked ? "false" : "true");
    }

  };

  const toggleFormula = (select) => {
    if (!select) return;
    const container = select.closest("[data-role=chapter-row]");
    const formulaInput = container.querySelector('[data-role=formula-input]');
    const isFormula = select.value === "formula";
    formulaInput.hidden = !isFormula;
    formulaInput.setAttribute("aria-hidden", isFormula ? "false" : "true");
    if (!isFormula) {
      formulaInput.value = "";
    }
    if (isFormula) {
      formulaInput.required = true;
    } else {
      formulaInput.required = false;
    }
  };

  chapterRows.forEach((row) => {
    setRowExpansion(row, row.dataset.expanded === "true");
    const enabled = row.querySelector('[data-role=chapter-enabled]');
    if (enabled) {
      enabled.addEventListener("change", () => updateRowState(row));
      updateRowState(row);
    }
    const select = row.querySelector("select[data-role=voice-select]");
    if (select) {
      select.addEventListener("change", () => toggleFormula(select));
      toggleFormula(select);
    }
    const toggleButton = row.querySelector('[data-role="chapter-toggle"]');
    if (toggleButton) {
      toggleButton.addEventListener("click", () => {
        if (!isRowEnabled(row)) {
          setRowExpansion(row, false);
          return;
        }
        toggleRowExpansion(row);
      });
    }
  });

  const updatePreviewVoice = (select) => {
    const container = select.closest(".speaker-list__item");
    if (!container) return;
    const previewButtons = container.querySelectorAll('[data-role="speaker-preview"]');
    if (!previewButtons.length) return;

    const formulaInput = container.querySelector('[data-role="speaker-formula"]');
  const mixContainer = container.querySelector('[data-role="speaker-mix"]');
  const mixLabel = container.querySelector('[data-role="speaker-mix-label"]');

    const formulaValue = formulaInput?.value?.trim() || "";
    updateCustomMixOption(select, formulaValue);

    const defaultVoice = select.dataset.defaultVoice || "";
    let assignedVoice = select.value || defaultVoice;
    if (select.value === "__custom_mix" || formulaValue) {
      assignedVoice = formulaValue || defaultVoice;
    }

    if (formulaValue) {
      if (mixContainer) mixContainer.hidden = false;
      if (mixLabel) mixLabel.textContent = formulaValue;
    } else {
      if (mixContainer) mixContainer.hidden = true;
      if (mixLabel) mixLabel.textContent = "";
      if (assignedVoice === "__custom_mix" || !assignedVoice) {
        assignedVoice = defaultVoice;
      }
    }

    previewButtons.forEach((button) => {
      const kind = button.dataset.previewKind || "";
      if (kind === "generated") {
        button.hidden = !formulaValue;
        button.dataset.voice = assignedVoice;
        return;
      }

      const context = button.dataset.previewContext || "";
      if (context === "mix") {
        button.dataset.voice = formulaValue || assignedVoice;
        return;
      }

      button.dataset.voice = assignedVoice || defaultVoice || button.dataset.voice || "";
    });
  };

  const voiceSelects = Array.from(form.querySelectorAll('[data-role="speaker-voice"]'));
  voiceSelects.forEach((select) => {
    ensureCustomMixOption(select);
    select.addEventListener("change", (event) => {
      const target = event.target;
      const container = target.closest(".speaker-list__item");
      if (!container) return;
      const formulaInput = container.querySelector('[data-role="speaker-formula"]');
      const mixContainer = container.querySelector('[data-role="speaker-mix"]');
      const mixLabel = container.querySelector('[data-role="speaker-mix-label"]');

      if (target.value === "__custom_mix") {
        if (!formulaInput?.value?.trim()) {
          const previous = target.dataset.prevManual || "";
          target.value = previous;
        }
        updatePreviewVoice(target);
        registerSpeakerHintFromNode(container);
        return;
      }

      if (!target.dataset.suppressFormulaClear) {
        if (formulaInput) {
          formulaInput.value = "";
        }
        if (mixLabel) {
          mixLabel.textContent = "";
        }
        if (mixContainer) {
          mixContainer.hidden = true;
        }
        updateCustomMixOption(target, "");
      }

      target.dataset.prevManual = target.value || "";
      updatePreviewVoice(target);
      delete target.dataset.suppressFormulaClear;
      if (container) {
        registerSpeakerHintFromNode(container);
      }
    });
    updatePreviewVoice(select);
  });

    const speakerItems = Array.from(form.querySelectorAll(".speaker-list__item"));
    speakerItems.forEach((item) => {
      initialiseSpeakerItem(item);
      const pronunciationInput = item.querySelector('[data-role="speaker-pronunciation"]');
      if (pronunciationInput) {
        const sync = () => syncPronunciationPreview(item);
        pronunciationInput.addEventListener("input", sync);
        pronunciationInput.addEventListener("change", sync);
      }
    registerSpeakerHintFromNode(item);
    });
  rebuildSpeakerHints();

  const activeStepInput = form.querySelector('[data-role="active-step-input"]');
  const analysisButtons = Array.from(form.querySelectorAll('[data-role="submit-speaker-analysis"]'));
  analysisButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (activeStepInput) {
  activeStepInput.value = "entities";
      }
    });
  });

  const voiceModal = document.querySelector('[data-role="voice-modal"]');
  let activeGenderFilter = "";

  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

  const parseFormula = (formula) => {
    const mix = new Map();
    if (!formula) return mix;
    const parts = formula.split("+");
    parts.forEach((part) => {
      const segment = part.trim();
      if (!segment) return;
      const pieces = segment.split("*");
      const voiceId = pieces[0].trim();
      if (!voiceId) return;
      let weight = 1;
      if (pieces[1]) {
        const parsed = Number.parseFloat(pieces[1].trim());
        if (!Number.isNaN(parsed) && parsed > 0) {
          weight = parsed;
        }
      }
      mix.set(voiceId, clamp(weight, 0.05, 1));
    });
    return mix;
  };

  const normaliseMix = (mix) => {
    const entries = Array.from(mix.entries());
    const total = entries.reduce((sum, [, weight]) => sum + weight, 0);
    if (!total) return mix;
    entries.forEach(([voiceId, weight]) => {
      mix.set(voiceId, weight / total);
    });
    return mix;
  };

  const formatMix = (mix) => {
    const entries = Array.from(mix.entries());
    if (!entries.length) return "";
    let total = entries.reduce((sum, [, weight]) => sum + weight, 0);
    if (total < 0.5) {
      const scale = 0.5 / total;
      entries.forEach(([voiceId, weight]) => {
        mix.set(voiceId, clamp(weight * scale, 0.05, 1));
      });
      total = entries.reduce((sum, [, weight]) => sum + weight, 0);
    }
    return entries
      .map(([voiceId, weight]) => `${voiceId}*${(weight / total).toFixed(2)}`)
      .join("+");
  };

  const genderLabel = (value) => {
    switch ((value || "unknown").toLowerCase()) {
      case "male":
        return "Male";
      case "female":
        return "Female";
      case "either":
        return "Either";
      default:
        return "Unknown";
    }
  };

  const buildRandomMix = (gender, countOverride) => {
    const genderCode = (gender || "unknown").toLowerCase();
    const pool = voiceCatalog.filter((voice) => {
      const code = (voice.gender_code || "").toLowerCase();
      if (genderCode === "female") return code === "f";
      if (genderCode === "male") return code === "m";
      if (genderCode === "either") return code === "f" || code === "m";
      return true;
    });
    if (!pool.length) {
      return null;
    }
    const voices = [...pool];
    for (let i = voices.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [voices[i], voices[j]] = [voices[j], voices[i]];
    }
    const count = clamp(countOverride || Math.floor(Math.random() * 4) + 1, 1, 4);
    const selected = voices.slice(0, count);
    const mix = new Map();
    const rawWeights = selected.map(() => Math.random() + 0.2);
    const total = rawWeights.reduce((sum, weight) => sum + weight, 0);
    selected.forEach((voice, index) => {
      mix.set(voice.id, rawWeights[index] / total);
    });
    return mix;
  };

  const applyFormulaToSpeaker = (speakerItem, formula) => {
    if (!speakerItem) return;
    const select = speakerItem.querySelector('[data-role="speaker-voice"]');
    const formulaInput = speakerItem.querySelector('[data-role="speaker-formula"]');
    const mixLabel = speakerItem.querySelector('[data-role="speaker-mix-label"]');
    const mixContainer = speakerItem.querySelector('[data-role="speaker-mix"]');

    if (formulaInput) {
      formulaInput.value = formula || "";
    }
    if (mixLabel) {
      mixLabel.textContent = formula || "";
    }
    if (mixContainer) {
      mixContainer.hidden = !formula;
    }

    if (!select) {
      return;
    }

    ensureCustomMixOption(select);

    if (formula) {
      if (select.value !== "__custom_mix") {
        select.dataset.prevManual = select.value || select.dataset.prevManual || select.dataset.defaultVoice || "";
      }
      select.dataset.suppressFormulaClear = "1";
      updateCustomMixOption(select, formula);
      select.value = "__custom_mix";
    } else {
      const fallback = select.dataset.prevManual || select.dataset.defaultVoice || "";
      select.dataset.suppressFormulaClear = "1";
      updateCustomMixOption(select, "");
      select.value = fallback;
    }

    updatePreviewVoice(select);
    delete select.dataset.suppressFormulaClear;
    registerSpeakerHintFromNode(speakerItem);
  };

  const hideGenderMenus = () => {
    form.querySelectorAll('[data-role="gender-menu"]').forEach((menu) => {
      menu.hidden = true;
      menu.setAttribute("aria-hidden", "true");
    });
    form.querySelectorAll('[data-role="gender-pill"]').forEach((pill) => {
      pill.classList.remove("is-open");
    });
  };

  const setGenderForSpeaker = (genderContainer, value) => {
    if (!genderContainer) return;
    const normalized = value || "unknown";
    const input = genderContainer.querySelector('[data-role="gender-input"]');
    if (input) {
      input.value = normalized;
    }
    const pill = genderContainer.querySelector('[data-role="gender-pill"]');
    if (pill) {
      pill.dataset.current = normalized;
      pill.textContent = `${genderLabel(normalized)} voice`;
    }
    const options = genderContainer.querySelectorAll('[data-role="gender-option"]');
    options.forEach((option) => {
      if ((option.dataset.value || "unknown") === normalized) {
        option.dataset.state = "active";
      } else {
        option.removeAttribute("data-state");
      }
    });
    const speakerItem = genderContainer.closest(".speaker-list__item");
    registerSpeakerHintFromNode(speakerItem);
  };

  Array.from(form.querySelectorAll('[data-role="speaker-gender"]')).forEach((container) => {
    const input = container.querySelector('[data-role="gender-input"]');
    setGenderForSpeaker(container, input?.value || "unknown");
  });

  const modalState = {
    speakerItem: null,
    samples: [],
    recommended: new Set(),
    mix: new Map(),
    highlighted: "",
    defaultVoice: "",
    previewSettings: { language: "a", speed: "1", useGpu: "true" },
  };

  const resetModalState = () => {
    modalState.speakerItem = null;
    modalState.samples = [];
    modalState.recommended = new Set();
    modalState.mix = new Map();
    modalState.highlighted = "";
    modalState.defaultVoice = "";
    modalState.previewSettings = { language: "a", speed: "1", useGpu: "true" };
  };

  const getMixFormula = () => formatMix(normaliseMix(new Map(modalState.mix)));

  const renderVoiceList = (elements) => {
    if (!elements) return;
    const { list, searchInput, languageSelect } = elements;
    if (!list) return;
    list.innerHTML = "";
    const term = (searchInput?.value || "").trim().toLowerCase();
    const languageFilter = languageSelect?.value || "";
    const filtered = voiceCatalog
      .filter((voice) => {
        if (languageFilter && voice.language !== languageFilter) return false;
        if (activeGenderFilter && voice.gender_code !== activeGenderFilter) return false;
        if (term) {
          const haystacks = [voice.display_name, voice.id, voice.language_label, languageMap[voice.language]]
            .filter(Boolean)
            .map((value) => value.toLowerCase());
          if (!haystacks.some((value) => value.includes(term))) {
            return false;
          }
        }
        return true;
      })
      .sort((a, b) => {
        const aRecommended = modalState.recommended.has(a.id) ? 0 : 1;
        const bRecommended = modalState.recommended.has(b.id) ? 0 : 1;
        if (aRecommended !== bRecommended) {
          return aRecommended - bRecommended;
        }
        return a.display_name.localeCompare(b.display_name);
      });

    if (!filtered.length) {
      const emptyItem = document.createElement("li");
      emptyItem.className = "voice-browser__empty";
      emptyItem.textContent = "No voices matched your filters.";
      list.appendChild(emptyItem);
      return;
    }

    filtered.forEach((voice) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "voice-browser__entry";
      button.dataset.role = "voice-modal-item";
      button.dataset.voiceId = voice.id;
      if (modalState.mix.has(voice.id)) {
        button.dataset.inMix = "true";
      }
      if (modalState.highlighted === voice.id) {
        button.setAttribute("aria-current", "true");
      }
      if (modalState.recommended.has(voice.id)) {
        button.dataset.recommended = "true";
      }
      const nameSpan = document.createElement("span");
      nameSpan.className = "voice-browser__entry-name";
      nameSpan.textContent = voice.display_name;
      const metaSpan = document.createElement("span");
      metaSpan.className = "voice-browser__entry-meta";
      metaSpan.textContent = `${voice.language_label} · ${voice.gender}`;
      button.appendChild(nameSpan);
      button.appendChild(metaSpan);
      item.appendChild(button);
      list.appendChild(item);
    });
  };

  const renderMix = (elements) => {
    const { mixList, mixTotal } = elements;
    if (!mixList) return;
    mixList.innerHTML = "";
    const entries = Array.from(normaliseMix(new Map(modalState.mix)).entries());
    const total = entries.reduce((sum, [, weight]) => sum + weight, 0);
    if (mixTotal) {
      mixTotal.textContent = `Total weight: ${total.toFixed(2)}`;
    }
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "voice-browser__empty";
      empty.textContent = "Add voices from the list to build a blend.";
      mixList.appendChild(empty);
      return;
    }
    entries.forEach(([voiceId, weight]) => {
      const wrapper = document.createElement("div");
      wrapper.className = "voice-browser__mix-item";
      wrapper.dataset.voiceId = voiceId;

      const header = document.createElement("div");
      header.className = "voice-browser__mix-header";
      const voiceMeta = voiceCatalogMap.get(voiceId) || {};
      const title = document.createElement("span");
      title.className = "voice-browser__mix-name";
      title.textContent = voiceMeta.display_name || voiceId;
      const weightLabel = document.createElement("span");
      weightLabel.className = "voice-browser__mix-weight";
      weightLabel.textContent = weight.toFixed(2);
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "voice-browser__mix-remove";
      removeBtn.setAttribute("aria-label", `Remove ${title.textContent} from blend`);
      removeBtn.textContent = "✕";
      removeBtn.addEventListener("click", () => {
        modalState.mix.delete(voiceId);
        if (modalState.highlighted === voiceId) {
          modalState.highlighted = "";
        }
        renderMix(elements);
        renderVoiceList(elements);
        updateModalMeta(elements);
        updateApplyState(elements);
      });
      header.appendChild(title);
      header.appendChild(weightLabel);
      header.appendChild(removeBtn);

      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "5";
      slider.max = "100";
      slider.step = "1";
      slider.value = String(Math.round(weight * 100));
      slider.addEventListener("input", () => {
        const value = clamp(Number.parseInt(slider.value, 10) / 100, 0.05, 1);
        modalState.mix.set(voiceId, value);
        modalState.highlighted = voiceId;
        renderMix(elements);
        updateModalMeta(elements);
        updateApplyState(elements);
      });

      wrapper.appendChild(header);
      wrapper.appendChild(slider);
      mixList.appendChild(wrapper);
    });
  };

  const renderSamples = (elements) => {
    if (!elements) return;
    const { samplesContainer } = elements;
    if (!samplesContainer) return;
    samplesContainer.innerHTML = "";

    if (!modalState.samples.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "No sample paragraphs available yet.";
      samplesContainer.appendChild(empty);
      return;
    }

    const formula = getMixFormula();
    modalState.samples.forEach((text, index) => {
      const sample = document.createElement("article");
      sample.className = "voice-browser__sample";
      sample.dataset.sampleIndex = String(index);
      if (index === 0) {
        sample.dataset.active = "true";
      }

      const paragraph = document.createElement("p");
      paragraph.textContent = text;
      const actions = document.createElement("div");
      actions.className = "voice-browser__sample-actions";

      const previewButton = document.createElement("button");
      previewButton.type = "button";
      previewButton.className = "button button--ghost button--small";
      previewButton.dataset.role = "speaker-preview";
      previewButton.dataset.previewText = text;
      previewButton.dataset.language = modalState.previewSettings.language;
      previewButton.dataset.speed = modalState.previewSettings.speed;
      previewButton.dataset.useGpu = modalState.previewSettings.useGpu;
      previewButton.dataset.voice = formula || modalState.defaultVoice || "";
      previewButton.textContent = "Preview sample";

      actions.appendChild(previewButton);
      sample.appendChild(paragraph);
      sample.appendChild(actions);
      samplesContainer.appendChild(sample);
    });
  };

  const updateModalMeta = (elements) => {
    if (!elements) return;
    const { nameLabel, metaLabel } = elements;
    if (!nameLabel || !metaLabel) return;
    if (!modalState.mix.size) {
      nameLabel.textContent = "Select voices to build a blend";
      metaLabel.textContent = "";
      return;
    }
    const highlight = modalState.highlighted && modalState.mix.has(modalState.highlighted)
      ? modalState.highlighted
      : Array.from(modalState.mix.keys())[0];
    modalState.highlighted = highlight;
    const voice = voiceCatalogMap.get(highlight);
    if (!voice) {
      nameLabel.textContent = highlight;
      metaLabel.textContent = "";
      return;
    }
    nameLabel.textContent = voice.display_name;
    metaLabel.textContent = `${voice.language_label} · ${voice.gender}`;
  };

  const updateApplyState = (elements) => {
    const { applyButton } = elements || {};
    if (!applyButton) return;
    const formula = getMixFormula();
    applyButton.disabled = !formula;
  };

  const refreshModal = (elements) => {
    renderVoiceList(elements);
    renderMix(elements);
    renderSamples(elements);
    updateModalMeta(elements);
    updateApplyState(elements);
  };

  const openVoiceBrowser = (speakerItem, sampleIndex = 0) => {
    if (!voiceModal) return;
    modalState.speakerItem = speakerItem;
    const select = speakerItem.querySelector('[data-role="speaker-voice"]');
  const previewTrigger = speakerItem.querySelector('[data-role="speaker-preview"][data-preview-source="pronunciation"]');
    const formulaInput = speakerItem.querySelector('[data-role="speaker-formula"]');
    modalState.defaultVoice = select?.dataset.defaultVoice || previewTrigger?.dataset.voice || "";
    modalState.mix = formulaInput?.value ? parseFormula(formulaInput.value) : new Map();
    if (!modalState.mix.size && select && select.value) {
      modalState.mix.set(select.value, 1);
    }
    modalState.mix = normaliseMix(modalState.mix);

    modalState.previewSettings = {
      language: previewTrigger?.dataset.language || "a",
      speed: previewTrigger?.dataset.speed || "1",
      useGpu: previewTrigger?.dataset.useGpu || "true",
    };

    const samples = readSpeakerSamples(speakerItem);
    let excerpts = samples.map((sample) => sample.excerpt);
    const storedIndex = sampleIndexState.get(speakerItem) || 0;
    let effectiveIndex = Number.isFinite(sampleIndex) ? sampleIndex : 0;
    if (!Number.isFinite(effectiveIndex) || effectiveIndex < 0 || effectiveIndex >= excerpts.length) {
      effectiveIndex = storedIndex;
    }
    if (excerpts.length && effectiveIndex > 0 && effectiveIndex < excerpts.length) {
      const [selected] = excerpts.splice(effectiveIndex, 1);
      excerpts.unshift(selected);
    }
    if (!excerpts.length) {
      const sampleButton = speakerItem.querySelector('[data-role="speaker-preview"][data-preview-source="sample"]');
      const previewText = sampleButton?.dataset.previewText?.trim();
      if (previewText) {
        excerpts = [previewText];
      }
    }
    modalState.samples = Array.from(new Set(excerpts));
    modalState.recommended = new Set(
      Array.from(speakerItem.querySelectorAll('[data-role="recommended-voice"]')).map((btn) => btn.dataset.voice).filter(Boolean)
    );
    activeGenderFilter = "";

    const elements = {
      list: voiceModal.querySelector('[data-role="voice-modal-list"]'),
      searchInput: voiceModal.querySelector('[data-role="voice-modal-search"]'),
      languageSelect: voiceModal.querySelector('[data-role="voice-modal-language"]'),
      genderButtons: Array.from(voiceModal.querySelectorAll('[data-role="voice-modal-gender"]')),
      mixList: voiceModal.querySelector('[data-role="voice-modal-mix-list"]'),
      mixTotal: voiceModal.querySelector('[data-role="voice-modal-mix-total"]'),
      samplesContainer: voiceModal.querySelector('[data-role="voice-modal-samples"]'),
      applyButton: voiceModal.querySelector('[data-role="voice-modal-apply"]'),
      nameLabel: voiceModal.querySelector('[data-role="voice-modal-selected-name"]'),
      metaLabel: voiceModal.querySelector('[data-role="voice-modal-selected-meta"]'),
    };

    if (elements.searchInput) elements.searchInput.value = "";
    if (elements.languageSelect) elements.languageSelect.value = "";
    elements.genderButtons.forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.value === "" ? "true" : "false");
    });

    refreshModal(elements);

    voiceModal.hidden = false;
    voiceModal.dataset.open = "true";
    document.body.classList.add("modal-open");
    if (elements.searchInput) {
      setTimeout(() => elements.searchInput.focus({ preventScroll: true }), 0);
    }
  };

  const closeVoiceBrowser = () => {
    if (!voiceModal || voiceModal.hidden) return;
    voiceModal.hidden = true;
    voiceModal.removeAttribute("data-open");
    document.body.classList.remove("modal-open");
    resetModalState();
  };

  if (voiceModal) {
    const elements = {
      list: voiceModal.querySelector('[data-role="voice-modal-list"]'),
      searchInput: voiceModal.querySelector('[data-role="voice-modal-search"]'),
      languageSelect: voiceModal.querySelector('[data-role="voice-modal-language"]'),
      genderButtons: Array.from(voiceModal.querySelectorAll('[data-role="voice-modal-gender"]')),
      mixList: voiceModal.querySelector('[data-role="voice-modal-mix-list"]'),
      mixTotal: voiceModal.querySelector('[data-role="voice-modal-mix-total"]'),
      samplesContainer: voiceModal.querySelector('[data-role="voice-modal-samples"]'),
      applyButton: voiceModal.querySelector('[data-role="voice-modal-apply"]'),
      nameLabel: voiceModal.querySelector('[data-role="voice-modal-selected-name"]'),
      metaLabel: voiceModal.querySelector('[data-role="voice-modal-selected-meta"]'),
      randomButton: voiceModal.querySelector('[data-role="voice-modal-random"]'),
      clearButton: voiceModal.querySelector('[data-role="voice-modal-clear"]'),
    };

    if (elements.searchInput) {
      elements.searchInput.addEventListener("input", () => renderVoiceList(elements));
    }
    if (elements.languageSelect) {
      elements.languageSelect.addEventListener("change", () => renderVoiceList(elements));
    }
    elements.genderButtons.forEach((button) => {
      button.addEventListener("click", () => {
        activeGenderFilter = button.dataset.value || "";
        elements.genderButtons.forEach((btn) => btn.setAttribute("aria-pressed", btn === button ? "true" : "false"));
        renderVoiceList(elements);
      });
    });
    if (elements.list) {
      elements.list.addEventListener("click", (event) => {
        const target = event.target.closest('[data-role="voice-modal-item"]');
        if (!target) return;
        event.preventDefault();
        const voiceId = target.dataset.voiceId;
        if (!voiceId) return;
        if (!modalState.mix.has(voiceId)) {
          modalState.mix.set(voiceId, 0.5);
        }
        modalState.highlighted = voiceId;
        renderMix(elements);
        renderVoiceList(elements);
        updateModalMeta(elements);
        updateApplyState(elements);
      });
    }
    if (elements.randomButton) {
      elements.randomButton.addEventListener("click", () => {
        const genderInput = modalState.speakerItem?.querySelector('[data-role="gender-input"]');
        const gender = genderInput?.value || "unknown";
        const mix = buildRandomMix(gender);
        if (mix) {
          modalState.mix = mix;
          modalState.highlighted = Array.from(mix.keys())[0];
          refreshModal(elements);
        }
      });
    }
    if (elements.clearButton) {
      elements.clearButton.addEventListener("click", () => {
        modalState.mix.clear();
        modalState.highlighted = "";
        refreshModal(elements);
      });
    }
    if (elements.applyButton) {
      elements.applyButton.addEventListener("click", (event) => {
        event.preventDefault();
        if (!modalState.speakerItem) return;
        const formula = getMixFormula();
        if (!formula) return;
        applyFormulaToSpeaker(modalState.speakerItem, formula);
        closeVoiceBrowser();
      });
    }
    voiceModal.addEventListener("click", (event) => {
      if (event.target.closest('[data-role="voice-modal-close"]')) {
        event.preventDefault();
        closeVoiceBrowser();
      }
    });
    if (elements.samplesContainer) {
      elements.samplesContainer.addEventListener("click", (event) => {
        const sample = event.target.closest(".voice-browser__sample");
        if (!sample) return;
        elements.samplesContainer
          .querySelectorAll(".voice-browser__sample")
          .forEach((node) => node.removeAttribute("data-active"));
        sample.dataset.active = "true";
      });
    }
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !voiceModal.hidden) {
        closeVoiceBrowser();
      }
    });

    renderVoiceList(elements);
  }

  const entitySummaryData = parseJSONScript("entity-summary-data") || {};
  const entityCacheKeyData = parseJSONScript("entity-cache-key");
  const manualOverridesSeed = parseJSONScript("manual-overrides-data") || [];
  const pronunciationOverridesSeed = parseJSONScript("pronunciation-overrides-data") || [];
  const heteronymOverridesSeed = parseJSONScript("heteronym-overrides-data") || [];

  const entityTabs = form.querySelector('[data-role="entity-tabs"]');
  const entitiesUrl = form.dataset.entitiesUrl || "";
  const manualUpsertUrl = form.dataset.manualUpsertUrl || "";
  const manualDeleteUrlTemplate = form.dataset.manualDeleteUrlTemplate || "";
  const manualSearchUrl = form.dataset.manualSearchUrl || "";
  const baseVoice = form.dataset.baseVoice || form.dataset.voice || "";
  const languageCode = form.dataset.language || "en";
  const defaultSpeed = form.dataset.speed || "1.0";
  const useGpuDefault = form.dataset.useGpu || "true";
  let entitiesEnabled = form.dataset.entitiesEnabled !== "false";

  const entityState = {
    summary: entitySummaryData && typeof entitySummaryData === "object" ? entitySummaryData : {},
    cacheKey: typeof entityCacheKeyData === "string" ? entityCacheKeyData : "",
    manualOverrides: Array.isArray(manualOverridesSeed) ? [...manualOverridesSeed] : [],
    pronunciationOverrides: Array.isArray(pronunciationOverridesSeed) ? [...pronunciationOverridesSeed] : [],
    heteronymOverrides: Array.isArray(heteronymOverridesSeed) ? [...heteronymOverridesSeed] : [],
    filters: {
      people: 0,
      entities: 0,
      entitiesKind: "all",
    },
  };

  let highlightedOverrideId = "";
  let highlightMode = "manual";
  const dirtyOverrideIds = new Set();
  let activeEntityPanel = "";
  let overrideFlushPromise = null;
  let markOverrideDirty = () => {};
  let flushManualOverrides = () => null;
  let hasTriggeredEntitiesRefresh = false;

  if (entityTabs) {
    const tabButtons = Array.from(entityTabs.querySelectorAll('[data-role="entity-tab"]'));
    const tabPanels = new Map(
      Array.from(entityTabs.querySelectorAll('[data-role="entity-panel"]')).map((panel) => [panel.dataset.panel || "", panel])
    );

    const peopleSummaryContainer = entityTabs.querySelector('[data-role="people-summary"]');
    const peopleStatsNode = peopleSummaryContainer?.querySelector('[data-role="people-stats"]');
    const peopleListNode = peopleSummaryContainer?.querySelector('[data-role="entity-list-people"]');
    const peopleFilterNode = peopleSummaryContainer?.querySelector('[data-role="entity-filter-people"]');

    const entitySummaryContainer = entityTabs.querySelector('[data-role="entities-summary"]');
    const entityStatsNode = entitySummaryContainer?.querySelector('[data-role="entity-stats"]');
    const entityListNode = entitySummaryContainer?.querySelector('[data-role="entity-list-entities"]');
    const entitiesFilterNode = entitySummaryContainer?.querySelector('[data-role="entity-filter-entities"]');
    const entitiesKindFilterNode = entitySummaryContainer?.querySelector('[data-role="entity-filter-kind"]');
    const entityRowTemplate = entityTabs.querySelector('template[data-role="entity-row-template"]');
    const entitiesRefreshButton = entitySummaryContainer?.querySelector('[data-role="entities-refresh"]');
    const entitySpinner = entitySummaryContainer?.querySelector('[data-role="entities-spinner"]');
    const globalEntitySpinner = entityTabs.querySelector('[data-role="global-entity-spinner"]');

    const manualOverridesRoot = entityTabs.querySelector('[data-role="manual-overrides"]');
    const manualOverrideList = manualOverridesRoot?.querySelector('[data-role="manual-override-list"]');
    const manualOverrideTemplate = manualOverridesRoot?.querySelector('template[data-role="manual-override-template"]');
    const manualOverrideResultsList = manualOverridesRoot?.querySelector('[data-role="manual-override-results"]');
    const manualOverrideQueryInput = manualOverridesRoot?.querySelector('[data-role="manual-override-query"]');
    const manualOverrideSearchButton = manualOverridesRoot?.querySelector('[data-role="manual-override-search"]');
    const manualOverrideAddCustomButton = manualOverridesRoot?.querySelector('[data-role="manual-override-add-custom"]');
    const manualOverridesEmpty = manualOverridesRoot?.querySelector('[data-role="manual-overrides-empty"]');
    const manualOverrideSaveButton = manualOverridesRoot?.querySelector('[data-role="manual-override-save-all"]');
    const manualOverrideStatusNode = manualOverridesRoot?.querySelector('[data-role="manual-override-status"]');
    const heteronymOverridesRoot = manualOverridesRoot?.querySelector('[data-role="heteronym-overrides"]');
    const heteronymOverrideList = heteronymOverridesRoot?.querySelector('[data-role="heteronym-override-list"]');
    const heteronymOverrideTemplate = heteronymOverridesRoot?.querySelector('template[data-role="heteronym-override-template"]');
    const heteronymOverridesEmpty = heteronymOverridesRoot?.querySelector('[data-role="heteronym-overrides-empty"]');
    let manualOverrideStatusTimer = null;
    let manualOverrideStatusNonce = 0;

    const setManualOverrideStatus = (message, state = "") => {
      if (!manualOverrideStatusNode) return;
      manualOverrideStatusNonce += 1;
      const nonce = manualOverrideStatusNonce;
      if (manualOverrideStatusTimer) {
        window.clearTimeout(manualOverrideStatusTimer);
        manualOverrideStatusTimer = null;
      }
      manualOverrideStatusNode.textContent = message || "";
      if (state) {
        manualOverrideStatusNode.dataset.state = state;
      } else {
        manualOverrideStatusNode.removeAttribute("data-state");
      }
      if (state === "success" && message) {
        manualOverrideStatusTimer = window.setTimeout(() => {
          if (manualOverrideStatusNonce !== nonce) {
            return;
          }
          manualOverrideStatusNode.textContent = "";
          manualOverrideStatusNode.removeAttribute("data-state");
          manualOverrideStatusTimer = null;
        }, 4000);
      }
    };

    if (entitiesRefreshButton) {
      entitiesRefreshButton.disabled = !entitiesEnabled;
      entitiesRefreshButton.setAttribute("aria-disabled", entitiesEnabled ? "false" : "true");
    }

    const parseThreshold = (value) => {
      const parsed = Number.parseInt(value, 10);
      return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
    };

    if (peopleFilterNode) {
      peopleFilterNode.addEventListener("change", () => {
        entityState.filters.people = parseThreshold(peopleFilterNode.value);
        renderEntitySummary();
      });
    }

    if (entitiesFilterNode) {
      entitiesFilterNode.addEventListener("change", () => {
        entityState.filters.entities = parseThreshold(entitiesFilterNode.value);
        renderEntitySummary();
      });
    }

    if (entitiesKindFilterNode) {
      entitiesKindFilterNode.addEventListener("change", () => {
        const value = (entitiesKindFilterNode.value || "all").trim();
        entityState.filters.entitiesKind = value || "all";
        renderEntitySummary();
      });
    }

    const cloneTemplate = (template) => {
      if (!template) return null;
      if (template.content && template.content.firstElementChild) {
        return template.content.firstElementChild.cloneNode(true);
      }
      return template.cloneNode(true);
    };

    const formatMentions = (value) => {
      const count = Number(value || 0);
      return `${count.toLocaleString()} mention${count === 1 ? "" : "s"}`;
    };

    const formatEntityKindLabel = (value) => {
      if (!value) {
        return "Unknown";
      }
      if (/^[A-Z0-9_]+$/.test(value) && value.length <= 4) {
        return value.replace(/_/g, " ");
      }
      const lowerParts = value.toLowerCase().split("_");
      return lowerParts
        .map((part, index) => {
          if (index > 0 && ["of", "and", "the", "in", "on", "at"].includes(part)) {
            return part;
          }
          return part.charAt(0).toUpperCase() + part.slice(1);
        })
        .join(" ");
    };

    const buildOverrideLookup = () => {
      const map = new Map();
      const register = (entry, origin) => {
        if (!entry || typeof entry !== "object") return;
        const normalizedToken = entry.normalized || entry.token || "";
        const canonical = canonicalizeEntityKey(normalizedToken);
        const tokenLabel = entry.token || entry.normalized || "";
        const pronunciation = entry.pronunciation || "";
        if (!canonical || !tokenLabel) return;
        map.set(canonical, {
          ...entry,
          origin,
          token: tokenLabel,
          normalized: normalizedToken,
          pronunciation,
        });
      };

      const pronunciationOverrides = Array.isArray(entityState.pronunciationOverrides)
        ? entityState.pronunciationOverrides
        : [];
      pronunciationOverrides.forEach((entry) => register(entry, entry?.source || "history"));

      const manualOverrides = Array.isArray(entityState.manualOverrides) ? entityState.manualOverrides : [];
      manualOverrides.forEach((entry) => register(entry, "manual"));

      return map;
    };

    const buildPossessivePreviewSamples = (pronText, tokenLabel) => {
      const samples = new Set();
      const base = (pronText || "").trim();
      const fallback = (tokenLabel || "").trim();
      if (base) {
        samples.add(base);
      } else if (fallback) {
        samples.add(fallback);
      }
      const reference = (fallback || base).trim();
      if (!reference) {
        return Array.from(samples);
      }
      const root = (base || reference).trim();
      if (!root) {
        return Array.from(samples);
      }
      const lowerReference = reference.toLowerCase();
      const lowerRoot = root.toLowerCase();
      const endsWithApostrophe = lowerRoot.endsWith("'") || lowerRoot.endsWith("’");
      const endsWithApostropheS = lowerRoot.endsWith("'s") || lowerRoot.endsWith("’s");
      if (!endsWithApostropheS) {
        const possessive = `${root}'s`;
        const altPossessive = `${root}’s`;
        samples.add(possessive);
        samples.add(altPossessive);
      }
      if ((lowerReference.endsWith("s") || lowerRoot.endsWith("s")) && !endsWithApostrophe) {
        samples.add(`${root}'`);
        samples.add(`${root}’`);
      }
      return Array.from(samples);
    };

    const joinPossessivePreviewSamples = (pronText, tokenLabel) => {
      const variants = buildPossessivePreviewSamples(pronText, tokenLabel);
      return variants.join("\n").trim();
    };

    const setEntitiesLoading = (isLoading) => {
      if (globalEntitySpinner) {
        globalEntitySpinner.hidden = !isLoading;
      }
      if (!entitySummaryContainer) {
        return;
      }
      if (isLoading) {
        entitySummaryContainer.dataset.loading = "true";
      } else {
        delete entitySummaryContainer.dataset.loading;
      }
      if (entitySpinner) {
        entitySpinner.hidden = !isLoading;
        entitySpinner.setAttribute("aria-hidden", isLoading ? "false" : "true");
      }
      if (entitiesRefreshButton) {
        const disabled = isLoading || !entitiesEnabled;
        entitiesRefreshButton.disabled = disabled;
        entitiesRefreshButton.setAttribute("aria-disabled", disabled ? "true" : "false");
      }
      if (entityStatsNode && isLoading) {
        entityStatsNode.textContent = "Updating entity analysis…";
      }
    };

    function triggerEntitiesRefresh(force = false) {
      if (!entitiesEnabled) {
        return;
      }
      if (force) {
        hasTriggeredEntitiesRefresh = true;
        performEntitiesRefresh(true);
        return;
      }
      if (!hasTriggeredEntitiesRefresh) {
        hasTriggeredEntitiesRefresh = true;
        performEntitiesRefresh(true);
      }
    }

    function activateEntityTab(panelKey) {
      if (activeEntityPanel === "manual" && panelKey !== activeEntityPanel) {
        void flushManualOverrides();
      }
      tabButtons.forEach((button) => {
        const isActive = button.dataset.panel === panelKey;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-selected", isActive ? "true" : "false");
      });
      tabPanels.forEach((panel, key) => {
        if (!panel) return;
        const isActive = key === panelKey;
        panel.classList.toggle("is-active", isActive);
        panel.hidden = !isActive;
        panel.setAttribute("aria-hidden", isActive ? "false" : "true");
      });
      activeEntityPanel = panelKey;
      if (panelKey === "entities") {
        triggerEntitiesRefresh();
      }
    }

    function populateVoiceOptions(select, selectedVoice) {
      if (!select) return;
      const narratorLabel = baseVoice ? `Use narrator voice (${baseVoice})` : "Use narrator voice";
      select.innerHTML = "";
      const narratorOption = document.createElement("option");
      narratorOption.value = "";
      narratorOption.textContent = narratorLabel;
      if (!selectedVoice) {
        narratorOption.selected = true;
      }
      select.appendChild(narratorOption);
      voiceCatalog.forEach((voice) => {
        const option = document.createElement("option");
        option.value = voice.id;
        option.textContent = `${voice.display_name} · ${voice.language_label} · ${voice.gender}`;
        if (selectedVoice === voice.id) {
          option.selected = true;
        }
        select.appendChild(option);
      });
      if (selectedVoice) {
        const hasMatch = Array.from(select.options).some((option) => option.value === selectedVoice);
        if (!hasMatch) {
          const fallback = document.createElement("option");
          fallback.value = selectedVoice;
          fallback.textContent = selectedVoice;
          fallback.selected = true;
          select.appendChild(fallback);
        }
      }
    }

    function renderEntitySummary() {
      const summary = entityState.summary || {};
      const stats = summary.stats || {};
      const errors = Array.isArray(summary.errors) ? summary.errors : [];
      const peopleEntries = Array.isArray(summary.people) ? summary.people : [];
      const entityEntries = Array.isArray(summary.entities) ? summary.entities : [];
      const overrideLookup = buildOverrideLookup();
      const peopleThreshold = Number.parseInt(entityState.filters?.people, 10) || 0;
      const entityThreshold = Number.parseInt(entityState.filters?.entities, 10) || 0;
      const entityKindSelection = (entityState.filters?.entitiesKind || "all").toLowerCase();

      const ensureSelectValue = (node, value) => {
        if (!node) return;
        const target = String(value);
        if (node.value !== target) {
          node.value = target;
        }
      };

      ensureSelectValue(peopleFilterNode, peopleThreshold);
      ensureSelectValue(entitiesFilterNode, entityThreshold);
      ensureSelectValue(entitiesKindFilterNode, entityKindSelection || "all");

      if (entitiesKindFilterNode) {
        const seenKinds = new Set();
        const existingValue = entitiesKindFilterNode.value || "all";
        const options = Array.from(entityEntries || [])
          .map((entry) => String(entry?.kind || ""))
          .filter((kind) => kind && kind !== "PERSON");
        entitiesKindFilterNode.innerHTML = "";
        const addOption = (value, label) => {
          if (seenKinds.has(value)) return;
          const opt = document.createElement("option");
          opt.value = value;
          opt.textContent = label;
          entitiesKindFilterNode.appendChild(opt);
          seenKinds.add(value);
        };
        addOption("all", "All");
        addOption("proper_noun", "Proper nouns");
        options.forEach((kind) => {
          const normalized = kind.toLowerCase();
          addOption(normalized, formatEntityKindLabel(kind));
        });
        if (!seenKinds.has(existingValue)) {
          entityState.filters.entitiesKind = "all";
        }
        ensureSelectValue(entitiesKindFilterNode, entityState.filters.entitiesKind || "all");
      }

      const renderDisabled = (listNode, message) => {
        if (!listNode) return;
        listNode.innerHTML = "";
        const emptyItem = document.createElement("li");
        emptyItem.className = "entity-summary__empty";
        emptyItem.textContent = message;
        listNode.appendChild(emptyItem);
      };

      if (!entitiesEnabled) {
        const disabledMessage = "Entity recognition is turned off in Settings.";
        if (entityStatsNode) {
          entityStatsNode.textContent = disabledMessage;
        }
        if (peopleStatsNode) {
          peopleStatsNode.textContent = disabledMessage;
        }
        if (peopleFilterNode) {
          peopleFilterNode.disabled = true;
        }
        if (entitiesFilterNode) {
          entitiesFilterNode.disabled = true;
        }
        if (entitiesKindFilterNode) {
          entitiesKindFilterNode.disabled = true;
          entitiesKindFilterNode.value = "all";
        }
        renderDisabled(peopleListNode, disabledMessage);
        renderDisabled(entityListNode, "Enable entity recognition to populate detected entities.");
        return;
      }

      if (peopleFilterNode) {
        peopleFilterNode.disabled = false;
      }
      if (entitiesFilterNode) {
        entitiesFilterNode.disabled = false;
      }
      if (entitiesKindFilterNode) {
        entitiesKindFilterNode.disabled = false;
      }

      if (entityStatsNode) {
        if (errors.length) {
          entityStatsNode.textContent = errors.join(" · ");
        } else if (stats.processed) {
          const parts = [];
          if (typeof stats.chapters === "number") {
            parts.push(`${stats.chapters} chapter${stats.chapters === 1 ? "" : "s"}`);
          }
          if (typeof stats.tokens === "number") {
            parts.push(`${stats.tokens.toLocaleString()} tokens processed`);
          }
          if (typeof stats.people === "number") {
            parts.push(`${stats.people} character${stats.people === 1 ? "" : "s"}`);
          }
          if (typeof stats.entities === "number") {
            parts.push(`${stats.entities} ${stats.entities === 1 ? "entity" : "entities"}`);
          }
          entityStatsNode.textContent = parts.length ? parts.join(" · ") : "Entity analysis up to date.";
        } else {
          entityStatsNode.textContent = "Entity analysis will populate once you continue from chapters.";
        }
      }

      const renderGroup = (listNode, entries, threshold, options) => {
        if (!listNode) {
          return { visible: 0, total: entries.length };
        }
        listNode.innerHTML = "";
        let filtered = entries.filter((entry) => Number(entry?.count || 0) >= threshold);
        if (options.kindFilter) {
          filtered = filtered.filter((entry) => options.kindFilter(entry));
        }
        if (!filtered.length) {
          const emptyItem = document.createElement("li");
          emptyItem.className = "entity-summary__empty";
          emptyItem.textContent = entries.length ? options.filteredEmptyText : options.emptyText;
          listNode.appendChild(emptyItem);
          return { visible: 0, total: entries.length };
        }
        filtered.forEach((entity) => {
          const item = cloneTemplate(entityRowTemplate);
          if (!item) return;
          const normalized = entity.normalized || entity.label || entity.token || "";
          const tokenLabel = entity.label || entity.token || normalized || "Untitled entity";
          item.dataset.entityId = entity.id || normalized || tokenLabel;
          item.dataset.entityCategory = options.groupKey;
          item.dataset.normalized = normalized.toLowerCase();
          if (entity.kind) {
            item.dataset.entityKind = entity.kind;
          }

          const labelEl = item.querySelector('[data-role="entity-label"]');
          if (labelEl) {
            labelEl.textContent = tokenLabel;
          }

          const kindEl = item.querySelector('[data-role="entity-kind"]');
          if (kindEl) {
            const kind = entity.kind || entity.category || "";
            if (options.hideKind || !kind) {
              kindEl.textContent = "";
              kindEl.hidden = true;
            } else {
              kindEl.hidden = false;
              kindEl.textContent = formatEntityKindLabel(kind);
            }
          }

          const countEl = item.querySelector('[data-role="entity-count"]');
          if (countEl) {
            countEl.textContent = formatMentions(entity.count);
          }

          const samplesContainer = item.querySelector('[data-role="entity-samples"]');
          if (samplesContainer) {
            samplesContainer.innerHTML = "";
            const samples = Array.isArray(entity.samples) ? entity.samples : [];
            if (!samples.length) {
              const hint = document.createElement("p");
              hint.className = "hint";
              hint.textContent = "No sample sentences captured yet.";
              samplesContainer.appendChild(hint);
            } else {
              const list = document.createElement("ul");
              list.className = "entity-summary__samples-list";
              samples.slice(0, 3).forEach((sample) => {
                const text = typeof sample === "string" ? sample : sample?.excerpt;
                if (!text) return;
                const entry = document.createElement("li");
                entry.textContent = text;
                list.appendChild(entry);
              });
              samplesContainer.appendChild(list);
            }
          }

          const normalizedKey = canonicalizeEntityKey(normalized || tokenLabel);
          const overrideMeta = normalizedKey ? overrideLookup.get(normalizedKey) : null;

          const overrideButton = item.querySelector('[data-role="entity-add-override"]');
          if (overrideButton) {
            overrideButton.dataset.entityToken = entity.label || entity.token || "";
            overrideButton.dataset.entityNormalized = normalized;
            overrideButton.dataset.entityCategory = options.groupKey;
            overrideButton.dataset.entityCount = String(entity.count || 0);
            const sampleContext = Array.isArray(entity.samples) && entity.samples.length
              ? typeof entity.samples[0] === "string"
                ? entity.samples[0]
                : entity.samples[0]?.excerpt || ""
              : "";
            if (sampleContext) {
              overrideButton.dataset.entityContext = sampleContext;
            }
            if (entity.kind) {
              overrideButton.dataset.entityKind = entity.kind;
            }
            overrideButton.textContent = overrideMeta
              ? overrideMeta.origin === "manual"
                ? "Edit manual override"
                : "Edit pronunciation override"
              : "Add manual override";
            if (overrideMeta) {
              item.dataset.hasOverride = "true";
            } else {
              delete item.dataset.hasOverride;
            }
          }

          const inlineOverride = item.querySelector('[data-role="inline-override"]');
          if (inlineOverride) {
            const override = overrideMeta;
            if (override) {
              inlineOverride.hidden = false;
              item.dataset.hasOverride = "true";
              item.dataset.overrideId = override.id || override.normalized || override.token || "";
              if (override.origin) {
                item.dataset.overrideSource = override.origin;
              } else {
                delete item.dataset.overrideSource;
              }
              inlineOverride.dataset.pendingToken = override.token || tokenLabel;
              inlineOverride.dataset.pendingNormalized = override.normalized || normalized;
              inlineOverride.dataset.pendingContext = override.context || inlineOverride.dataset.pendingContext || "";
              inlineOverride.dataset.pendingCategory = options.groupKey;
              inlineOverride.dataset.pendingKind = entity.kind || "";
              const pronInput = inlineOverride.querySelector('[data-role="manual-override-pronunciation"]');
              if (pronInput) {
                pronInput.value = override.pronunciation || "";
                pronInput.placeholder = override.token || tokenLabel;
              }
              const voiceSelect = inlineOverride.querySelector('[data-role="manual-override-voice"]');
              if (voiceSelect) {
                populateVoiceOptions(voiceSelect, override.voice || "");
              }
              const previewButton = inlineOverride.querySelector('[data-role="speaker-preview"]');
              if (previewButton) {
                const previewValue = joinPossessivePreviewSamples(override.pronunciation, override.token || tokenLabel);
                previewButton.dataset.previewText = previewValue || override.token || tokenLabel;
                previewButton.dataset.voice = override.voice || override.voice_profile || baseVoice || "";
                previewButton.dataset.language = languageCode;
                previewButton.dataset.speed = defaultSpeed;
                previewButton.dataset.useGpu = useGpuDefault;
              }
              if (
                highlightMode === "inline" &&
                highlightedOverrideId &&
                (override.id === highlightedOverrideId || override.normalized === highlightedOverrideId || override.token === highlightedOverrideId)
              ) {
                item.classList.add("is-highlighted");
                inlineOverride.hidden = false;
                setTimeout(() => item.classList.remove("is-highlighted"), 2200);
                highlightedOverrideId = "";
              }
            } else {
              inlineOverride.hidden = true;
              delete item.dataset.overrideId;
              delete item.dataset.overrideSource;
            }
          }

          const previewButton = item.querySelector('[data-entity-preview="true"]');
          if (previewButton) {
            const previewVoice = overrideMeta?.voice || baseVoice || "";
            const previewText = Array.isArray(entity.samples) && entity.samples.length
              ? typeof entity.samples[0] === "string"
                ? entity.samples[0]
                : entity.samples[0]?.excerpt || tokenLabel
              : tokenLabel;
            previewButton.hidden = !previewText;
            if (previewText) {
              previewButton.dataset.previewText = previewText;
              previewButton.dataset.voice = previewVoice;
              previewButton.dataset.language = languageCode;
              previewButton.dataset.speed = defaultSpeed;
              previewButton.dataset.useGpu = useGpuDefault;
              previewButton.dataset.previewSource = "entity";
            }
          }

          listNode.appendChild(item);
        });
        return { visible: filtered.length, total: entries.length };
      };

      const peopleRender = renderGroup(peopleListNode, peopleEntries, peopleThreshold, {
        groupKey: "people",
        hideKind: true,
        emptyText: "No characters detected yet.",
        filteredEmptyText: "No characters match the selected mention filter.",
      });

      if (peopleFilterNode && !peopleEntries.length) {
        peopleFilterNode.value = "0";
      }

      if (peopleStatsNode) {
        if (errors.length) {
          peopleStatsNode.textContent = errors.join(" · ");
        } else if (!peopleEntries.length) {
          peopleStatsNode.textContent = "No characters detected yet.";
        } else if (!peopleRender.visible) {
          peopleStatsNode.textContent = "Adjust the mention filter to see additional characters.";
        } else {
          let label = "all mentions";
          if (peopleThreshold > 1) {
            label = `${peopleThreshold}+ mentions`;
          } else if (peopleThreshold === 1) {
            label = "1+ mention";
          }
          peopleStatsNode.textContent = `Showing ${peopleRender.visible} of ${peopleRender.total} characters (${label}).`;
        }
      }

      const entitiesRender = renderGroup(entityListNode, entityEntries, entityThreshold, {
        groupKey: "entities",
        hideKind: false,
        emptyText: "No entities detected yet.",
        filteredEmptyText: "No entities match the selected mention filter.",
        kindFilter: (entry) => {
          if (!entityKindSelection || entityKindSelection === "all") {
            return true;
          }
          const kind = (entry.kind || "").toLowerCase();
          if (entityKindSelection === "proper_noun") {
            return !kind || kind === "propn" || kind === "noun" || kind === "proper_noun";
          }
          return kind === entityKindSelection;
        },
      });

      if (entitiesFilterNode && !entityEntries.length) {
        entitiesFilterNode.value = "0";
      }

      if (
        entityStatsNode &&
        !errors.length &&
        stats.processed &&
        typeof stats.entities === "number" &&
        entityThreshold > 0 &&
        stats.entities > entitiesRender.visible
      ) {
        const filterLabel = entityThreshold > 1 ? `${entityThreshold}+ mentions` : "1+ mention";
        entityStatsNode.textContent += ` · Filter hiding ${stats.entities - entitiesRender.visible} entries (${filterLabel})`;
      }
    }

    function renderManualOverrides() {
      if (!manualOverrideList) return;
      manualOverrideList.innerHTML = "";
      const overrides = Array.isArray(entityState.manualOverrides) ? entityState.manualOverrides : [];
      if (!overrides.length) {
        if (manualOverridesEmpty) {
          manualOverridesEmpty.hidden = false;
        }
        return;
      }

      if (manualOverridesEmpty) {
        manualOverridesEmpty.hidden = true;
      }

      overrides.forEach((override) => {
        const node = cloneTemplate(manualOverrideTemplate);
        if (!node) return;
        const overrideId = override.id || override.normalized || override.token || "";
        node.dataset.overrideId = overrideId;
        node.dataset.token = override.token || "";
        node.dataset.normalized = override.normalized || "";
        node.dataset.context = override.context || "";

        const labelEl = node.querySelector('[data-role="override-label"]');
        if (labelEl) {
          labelEl.textContent = override.token || override.normalized || "Manual override";
        }

        const notesEl = node.querySelector('[data-role="override-notes"]');
        if (notesEl) {
          const notes = override.notes || override.context || "";
          if (notes) {
            notesEl.textContent = notes;
          } else {
            notesEl.hidden = true;
          }
        }

        const pronInput = node.querySelector('[data-role="manual-override-pronunciation"]');
        if (pronInput) {
          pronInput.value = override.pronunciation || "";
          pronInput.placeholder = override.token || override.normalized || "";
          pronInput.dataset.overrideId = overrideId;
        }

        const voiceSelect = node.querySelector('[data-role="manual-override-voice"]');
        if (voiceSelect) {
          populateVoiceOptions(voiceSelect, override.voice || "");
          voiceSelect.dataset.overrideId = overrideId;
        }

        const previewButton = node.querySelector('[data-role="speaker-preview"]');
        if (previewButton) {
          const previewVoice = override.voice || voiceSelect?.value || baseVoice || "";
          const previewText = joinPossessivePreviewSamples(override.pronunciation, override.token || override.normalized || "");
          previewButton.dataset.overrideId = overrideId;
          previewButton.dataset.previewText = previewText || override.pronunciation || override.token || "";
          previewButton.dataset.voice = previewVoice;
          previewButton.dataset.language = languageCode;
          previewButton.dataset.speed = defaultSpeed;
          previewButton.dataset.useGpu = useGpuDefault;
        }

        const deleteButton = node.querySelector('[data-role="manual-override-delete"]');
        if (deleteButton) {
          deleteButton.dataset.overrideId = overrideId;
        }

        const metaEl = node.querySelector('[data-role="manual-override-meta"]');
        if (metaEl) {
          const parts = [];
          if (override.source) {
            parts.push(`Source: ${override.source}`);
          }
          if (override.updated_at) {
            const timestamp = Number(override.updated_at) * 1000;
            if (!Number.isNaN(timestamp)) {
              parts.push(`Updated ${new Date(timestamp).toLocaleString()}`);
            }
          }
          metaEl.textContent = parts.join(" · ");
        }

        manualOverrideList.appendChild(node);
        if (highlightedOverrideId && highlightedOverrideId === overrideId) {
          node.classList.add("is-highlighted");
          setTimeout(() => node.classList.remove("is-highlighted"), 2400);
          node.scrollIntoView({ behavior: "smooth", block: "center" });
          highlightedOverrideId = "";
        }
      });
    }

    const escapeRegExp = (value) => String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

    const resolveHeteronymTooltip = (entry) => {
      if (!entry || typeof entry !== "object") return "";
      const options = Array.isArray(entry.options) ? entry.options : [];
      if (options.length < 2) return "";
      const parts = [];
      options.slice(0, 2).forEach((opt) => {
        const label = String(opt?.label || "").trim();
        const example = String(opt?.example_sentence || "").trim();
        if (label && example) {
          parts.push(`${label}: ${example}`);
        } else if (example) {
          parts.push(example);
        }
      });
      return parts.join("\n");
    };

    const fillHighlightedSentence = (container, sentence, token, tooltip) => {
      if (!container) return;
      container.textContent = "";
      const rawSentence = String(sentence || "");
      const rawToken = String(token || "");
      if (!rawSentence) {
        return;
      }
      if (!rawToken) {
        container.textContent = rawSentence;
        return;
      }

      const pattern = new RegExp(`\\b${escapeRegExp(rawToken)}\\b`, "i");
      const match = pattern.exec(rawSentence);
      if (!match) {
        container.textContent = rawSentence;
        return;
      }

      const before = rawSentence.slice(0, match.index);
      const hit = rawSentence.slice(match.index, match.index + match[0].length);
      const after = rawSentence.slice(match.index + match[0].length);

      if (before) {
        container.appendChild(document.createTextNode(before));
      }
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = hit;
      if (tooltip) {
        chip.title = tooltip;
      }
      container.appendChild(chip);
      if (after) {
        container.appendChild(document.createTextNode(after));
      }
    };

    function renderHeteronymOverrides() {
      if (!heteronymOverrideList) return;
      heteronymOverrideList.innerHTML = "";
      const entries = Array.isArray(entityState.heteronymOverrides) ? entityState.heteronymOverrides : [];
      if (!entries.length) {
        if (heteronymOverridesEmpty) {
          heteronymOverridesEmpty.hidden = false;
        }
        return;
      }

      if (heteronymOverridesEmpty) {
        heteronymOverridesEmpty.hidden = true;
      }

      entries.forEach((entry) => {
        if (!entry || typeof entry !== "object") return;
        const entryId = String(entry.entry_id || entry.id || "").trim();
        if (!entryId) return;
        const sentence = String(entry.sentence || "").trim();
        if (!sentence) return;
        const token = String(entry.token || "").trim();

        const node = cloneTemplate(heteronymOverrideTemplate);
        if (!node) return;
        node.dataset.entryId = entryId;

        const sentenceEl = node.querySelector('[data-role="heteronym-sentence"]');
        if (sentenceEl) {
          const tooltip = resolveHeteronymTooltip(entry);
          fillHighlightedSentence(sentenceEl, sentence, token, tooltip);
        }

        const notesEl = node.querySelector('[data-role="heteronym-notes"]');
        if (notesEl) {
          const suggested = String(entry.default_choice || "").trim();
          if (suggested) {
            const options = Array.isArray(entry.options) ? entry.options : [];
            const match = options.find((opt) => String(opt?.key || "").trim() === suggested);
            const label = String(match?.label || "").trim();
            notesEl.textContent = label ? `Suggested: ${label}` : "";
            notesEl.hidden = !notesEl.textContent;
          } else {
            notesEl.hidden = true;
          }
        }

        const optionsContainer = node.querySelector('[data-role="heteronym-options"]');
        if (optionsContainer) {
          optionsContainer.innerHTML = "";
          const options = Array.isArray(entry.options) ? entry.options : [];
          const selectedKey = String(entry.choice || entry.default_choice || "").trim();
          options.slice(0, 2).forEach((opt, index) => {
            if (!opt || typeof opt !== "object") return;
            const key = String(opt.key || "").trim();
            const label = String(opt.label || "Option").trim();
            const previewSentence = String(opt.replacement_sentence || sentence).trim();
            if (!key) return;

            const wrapper = document.createElement("div");
            wrapper.className = "entity-inline-override__actions";

            const choiceLabel = document.createElement("label");
            choiceLabel.className = "toggle-pill";
            const input = document.createElement("input");
            input.type = "radio";
            input.name = `heteronym-${entryId}-choice`;
            input.value = key;
            if (selectedKey) {
              input.checked = selectedKey === key;
            } else {
              input.checked = index === 0;
            }
            const span = document.createElement("span");
            span.textContent = label;
            choiceLabel.appendChild(input);
            choiceLabel.appendChild(span);

            const previewButton = document.createElement("button");
            previewButton.type = "button";
            previewButton.className = "button button--ghost button--small";
            previewButton.dataset.role = "speaker-preview";
            previewButton.dataset.previewText = previewSentence;
            previewButton.dataset.voice = baseVoice || "";
            previewButton.dataset.language = languageCode;
            previewButton.dataset.speed = defaultSpeed;
            previewButton.dataset.useGpu = useGpuDefault;
            previewButton.textContent = "Preview";
            previewButton.disabled = !previewButton.dataset.voice;
            previewButton.setAttribute("aria-disabled", previewButton.disabled ? "true" : "false");

            wrapper.appendChild(choiceLabel);
            wrapper.appendChild(previewButton);
            optionsContainer.appendChild(wrapper);
          });
        }

        heteronymOverrideList.appendChild(node);
      });
    }

    function applyEntityPayload(payload, options = {}) {
      if (payload && typeof payload === "object") {
        if (payload.summary) {
          entityState.summary = payload.summary;
        }
        if (Array.isArray(payload.manual_overrides)) {
          entityState.manualOverrides = payload.manual_overrides;
        }
        if (Array.isArray(payload.pronunciation_overrides)) {
          entityState.pronunciationOverrides = payload.pronunciation_overrides;
        }
        if (Array.isArray(payload.heteronym_overrides)) {
          entityState.heteronymOverrides = payload.heteronym_overrides;
        }
        if (typeof payload.cache_key === "string") {
          entityState.cacheKey = payload.cache_key;
        }
        if (Object.prototype.hasOwnProperty.call(payload, "recognition_enabled")) {
          entitiesEnabled = payload.recognition_enabled !== false;
          form.dataset.entitiesEnabled = entitiesEnabled ? "true" : "false";
          if (entitiesRefreshButton) {
            entitiesRefreshButton.disabled = !entitiesEnabled;
            entitiesRefreshButton.setAttribute("aria-disabled", entitiesEnabled ? "false" : "true");
          }
        }
      }
      if (options.highlightId) {
        highlightedOverrideId = options.highlightId;
      }
      renderEntitySummary();
      renderManualOverrides();
      renderHeteronymOverrides();
    }

    const filterVoicesByGender = (voices, genderHint) => {
      const normalized = (genderHint || "unknown").toLowerCase();
      if (normalized === "female") {
        return voices.filter((voice) => (voice.gender_code || "").toLowerCase() === "f");
      }
      if (normalized === "male") {
        return voices.filter((voice) => (voice.gender_code || "").toLowerCase() === "m");
      }
      if (normalized === "either") {
        return voices.filter((voice) => {
          const code = (voice.gender_code || "").toLowerCase();
          return code === "f" || code === "m";
        });
      }
      return voices.slice();
    };

    const pickRandomVoiceForOverride = (genderHint) => {
      if (!Array.isArray(voiceCatalog) || !voiceCatalog.length) {
        return baseVoice || "";
      }
      const normalizedLanguage = (languageCode || "").trim().toLowerCase();
      const languageCandidates = () => {
        const keys = [];
        if (normalizedLanguage) keys.push(normalizedLanguage);
        if (languageCode && languageCode !== normalizedLanguage) {
          keys.push(languageCode);
        }
        for (const key of keys) {
          const mapped = languageMap?.[key];
          if (Array.isArray(mapped) && mapped.length) {
            const lookup = new Set(mapped);
            const matches = voiceCatalog.filter((voice) => lookup.has(voice.id));
            if (matches.length) {
              return matches;
            }
          }
        }
        const direct = voiceCatalog.filter((voice) => (voice.language || "").toLowerCase() === normalizedLanguage);
        return direct;
      };

      const preferred = languageCandidates();
      let pool = filterVoicesByGender(preferred.length ? preferred : voiceCatalog, genderHint);
      if (!pool.length) {
        pool = voiceCatalog.slice();
      }
      if (!pool.length) {
        return baseVoice || "";
      }
      const selected = pool[Math.floor(Math.random() * pool.length)];
      return selected?.id || baseVoice || "";
    };

    const resolveOverrideVoice = (data) => {
      const hasVoiceProp = Boolean(data && Object.prototype.hasOwnProperty.call(data, "voice"));
      const voiceValueRaw = typeof data?.voice === "string" ? data.voice : "";
      const voiceValue = voiceValueRaw.trim();
      if (voiceValue) {
        return voiceValue;
      }
      if (hasVoiceProp) {
        return "";
      }
      const normalizedKey = canonicalizeEntityKey(data.normalized || data.token || "");
      let genderHint = (data.gender || "").toLowerCase();
      if (normalizedKey) {
        const speakerHint = speakerHints.get(normalizedKey);
        if (speakerHint) {
          if (speakerHint.voice) {
            return speakerHint.voice;
          }
          if (!genderHint || genderHint === "unknown") {
            genderHint = speakerHint.gender || genderHint;
          }
        }
      }
      if (!genderHint || genderHint === "unknown") {
        if (data.category === "people" || data.kind === "PERSON") {
          genderHint = "either";
        } else {
          genderHint = "";
        }
      }
      if (baseVoice) {
        return "";
      }
      return pickRandomVoiceForOverride(genderHint);
    };

    function collectOverridePayload(overrideId) {
      if (!overrideId || !manualOverrideList) return null;
      const selectorId = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(overrideId) : overrideId.replace(/["\\]/g, "\\$&");
      const node = manualOverrideList.querySelector(`[data-override-id="${selectorId}"]`);
      if (!node) return null;
      const pronInput = node.querySelector('[data-role="manual-override-pronunciation"]');
      const voiceSelect = node.querySelector('[data-role="manual-override-voice"]');
      return {
        id: overrideId,
        token: node.dataset.token || "",
        normalized: node.dataset.normalized || "",
        pronunciation: pronInput?.value?.trim() || "",
        voice: voiceSelect?.value || "",
        notes: "",
        context: node.dataset.context || "",
      };
    }

    async function saveManualOverride(overrideId) {
      const payload = collectOverridePayload(overrideId);
      if (!payload || !manualUpsertUrl) return false;
      try {
        const response = await fetch(manualUpsertUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          throw new Error(`Override save failed with status ${response.status}`);
        }
        const data = await response.json();
        applyEntityPayload(data, { highlightId: data.override?.id || payload.id });
        return true;
      } catch (error) {
        console.error("Failed to save manual override", error);
        return false;
      }
    }

    markOverrideDirty = (overrideId) => {
      if (!overrideId) return;
      dirtyOverrideIds.add(overrideId);
      setManualOverrideStatus("Unsaved changes", "pending");
    };

    flushManualOverrides = (options = {}) => {
      const { overrideId } = options || {};
      const pendingIds = Array.isArray(overrideId) ? overrideId : overrideId ? [overrideId] : Array.from(dirtyOverrideIds);
      const targetIds = pendingIds.filter((id) => dirtyOverrideIds.has(id));
      if (!targetIds.length) return null;
      setManualOverrideStatus("Saving overrides…", "pending");
      targetIds.forEach((id) => dirtyOverrideIds.delete(id));
      const runFlush = async () => {
        if (overrideFlushPromise) {
          try {
            await overrideFlushPromise;
          } catch (error) {
            console.warn("Previous override flush failed", error);
          }
        }
        const results = await Promise.all(targetIds.map((id) => saveManualOverride(id)));
        let hasFailure = false;
        results.forEach((ok, index) => {
          if (!ok) {
            hasFailure = true;
            dirtyOverrideIds.add(targetIds[index]);
          }
        });
        if (hasFailure) {
          setManualOverrideStatus("Some overrides failed to save.", "error");
        } else {
          setManualOverrideStatus("Overrides saved.", "success");
        }
      };
      overrideFlushPromise = runFlush()
        .catch((error) => {
          console.error("Failed flushing manual overrides", error);
          setManualOverrideStatus("Failed to save overrides.", "error");
        })
        .finally(() => {
          overrideFlushPromise = null;
        });
      return overrideFlushPromise;
    };

    async function deleteManualOverride(overrideId) {
      if (!overrideId || !manualDeleteUrlTemplate) return;
      dirtyOverrideIds.delete(overrideId);
      const targetUrl = manualDeleteUrlTemplate.replace("__OVERRIDE_ID__", encodeURIComponent(overrideId));
      try {
        const response = await fetch(targetUrl, { method: "DELETE" });
        if (!response.ok) {
          throw new Error(`Override delete failed with status ${response.status}`);
        }
        const data = await response.json();
        applyEntityPayload(data);
      } catch (error) {
        console.error("Failed to delete manual override", error);
      }
    }

    async function performEntitiesRefresh(force = false) {
      if (!entitiesUrl) return;
      setEntitiesLoading(true);
      try {
        const url = new URL(entitiesUrl, window.location.origin);
        if (force) {
          url.searchParams.set("refresh", "1");
        }
        if (entityState.cacheKey) {
          url.searchParams.set("cache_key", entityState.cacheKey);
        }
        const response = await fetch(url.toString(), { method: "GET" });
        if (!response.ok) {
          throw new Error(`Entity refresh failed with status ${response.status}`);
        }
        const data = await response.json();
        applyEntityPayload(data);
      } catch (error) {
        console.error("Failed to refresh entity summary", error);
      } finally {
        setEntitiesLoading(false);
      }
    }

    async function performManualOverrideSearch(query) {
      if (!manualSearchUrl || !manualOverrideResultsList) return;
      manualOverrideResultsList.innerHTML = "";
      try {
        const url = new URL(manualSearchUrl, window.location.origin);
        if (query) {
          url.searchParams.set("q", query);
        }
        const response = await fetch(url.toString(), { method: "GET" });
        if (!response.ok) {
          throw new Error(`Search failed with status ${response.status}`);
        }
        const data = await response.json();
        const results = Array.isArray(data.results) ? data.results : [];
        if (!results.length) {
          const emptyItem = document.createElement("li");
          emptyItem.className = "manual-overrides__results-empty";
          emptyItem.textContent = query ? "No matches found." : "Start typing to search tokens.";
          manualOverrideResultsList.appendChild(emptyItem);
          return;
        }
        results.forEach((entry) => {
          const item = document.createElement("li");
          item.className = "manual-overrides__result";
          const button = document.createElement("button");
          button.type = "button";
          button.className = "button button--ghost button--small";
          button.dataset.role = "manual-override-result";
          button.dataset.token = entry.token || entry.normalized || "";
          if (entry.normalized) {
            button.dataset.normalized = entry.normalized;
          }
          if (entry.context) {
            button.dataset.context = entry.context;
          } else if (Array.isArray(entry.samples) && entry.samples.length) {
            const sample = entry.samples[0];
            button.dataset.context = typeof sample === "string" ? sample : sample?.excerpt || "";
          }
          if (entry.pronunciation) {
            button.dataset.pronunciation = entry.pronunciation;
          }
          if (entry.voice) {
            button.dataset.voice = entry.voice;
          }
          button.dataset.source = entry.source || "search";
          button.textContent = entry.token || entry.normalized || "Unnamed token";
          item.appendChild(button);
          manualOverrideResultsList.appendChild(item);
        });
      } catch (error) {
        console.error("Failed to search manual override candidates", error);
      }
    }

    async function createOverrideFromData(data) {
      if (!data || !manualUpsertUrl) return false;
      const token = (data.token || "").trim();
      if (!token) return false;
      const normalized = (data.normalized || "").trim();
      const voiceChoice = resolveOverrideVoice({ ...data, token, normalized });
      const payload = {
        token,
        normalized,
        context: data.context || "",
        pronunciation: data.pronunciation || "",
        voice: voiceChoice || "",
        source: data.source || "manual",
      };
      try {
        const response = await fetch(manualUpsertUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          throw new Error(`Override creation failed with status ${response.status}`);
        }
        const body = await response.json();
        const highlighted = body.override?.id || payload.normalized || payload.token;
        applyEntityPayload(body, { highlightId: highlighted });
        if (highlightMode === "inline") {
          highlightedOverrideId = highlighted;
          const targetPanel = activeEntityPanel || "entities";
          activateEntityTab(targetPanel);
        } else {
          activateEntityTab("manual");
          if (manualOverrideResultsList) {
            manualOverrideResultsList.innerHTML = "";
          }
        }
        return true;
      } catch (error) {
        console.error("Failed to create manual override", error);
        return false;
      }
    }

    tabButtons.forEach((button) => {
      button.addEventListener("click", () => {
        highlightMode = button.dataset.panel === "manual" ? "manual" : "entities";
        activateEntityTab(button.dataset.panel || "people");
      });
    });

    if (entitiesRefreshButton) {
      entitiesRefreshButton.addEventListener("click", () => {
        void flushManualOverrides();
        triggerEntitiesRefresh(true);
      });
    }

    const extractInlineOverrideState = (inlineOverride, row) => {
      if (!inlineOverride || inlineOverride.hidden) {
        return null;
      }
      const container = row || inlineOverride.closest('[data-role="entity-row"]');
      if (!container) {
        return null;
      }
      const tokenLabel = inlineOverride.dataset.pendingToken || container.querySelector('[data-role="entity-label"]')?.textContent || "";
      if (!tokenLabel) {
        return null;
      }
      const normalized = (inlineOverride.dataset.pendingNormalized || container.dataset.normalized || tokenLabel || "").trim();
      const context = (inlineOverride.dataset.pendingContext || "").trim();
      const pronInput = inlineOverride.querySelector('[data-role="manual-override-pronunciation"]');
      const voiceSelect = inlineOverride.querySelector('[data-role="manual-override-voice"]');
      const pronunciationRaw = pronInput?.value ?? "";
      const pronunciation = pronunciationRaw.trim();
      const voiceRaw = voiceSelect?.value ?? "";
      const voice = voiceRaw;
      const previewVoice = voice || baseVoice || "";
      const previewText = pronunciation || tokenLabel;
      return {
        token: tokenLabel,
        normalized,
        context,
        pronunciation,
        voice,
        previewVoice,
        previewText,
        category: inlineOverride.dataset.pendingCategory || container.dataset.entityCategory || "",
        kind: inlineOverride.dataset.pendingKind || container.dataset.entityKind || "",
      };
    };

    const syncInlinePreviewUI = (row, inlineOverride, state, targetButton) => {
      if (!state) {
        return;
      }
      const previewText = state.previewText || state.token;
      const previewVoice = state.previewVoice || baseVoice || "";
      const applyDatasets = (button) => {
        if (!button) return;
        const previewValue = joinPossessivePreviewSamples(previewText, state.token);
        button.dataset.previewText = previewValue || previewText || state.token || "";
        button.dataset.voice = previewVoice;
        button.dataset.language = languageCode;
        button.dataset.speed = defaultSpeed;
        button.dataset.useGpu = useGpuDefault;
        if (!button.dataset.previewSource || button.dataset.previewSource === "entity") {
          button.dataset.previewSource = "manual";
        }
      };

      if (targetButton) {
        applyDatasets(targetButton);
        return;
      }

      if (inlineOverride) {
        applyDatasets(inlineOverride.querySelector('[data-role="speaker-preview"]'));
      }
      if (row) {
        applyDatasets(row.querySelector('[data-entity-preview="true"]'));
      }
    };

    const persistInlineOverrideState = (state) => {
      if (!state) {
        return null;
      }
      highlightMode = "inline";
      setManualOverrideStatus("Saving overrides…", "pending");
      return createOverrideFromData({
        token: state.token,
        normalized: state.normalized,
        context: state.context,
        pronunciation: state.pronunciation,
        voice: state.voice,
        category: state.category,
        kind: state.kind,
        source: "entity-inline",
      })
        .then((ok) => {
          if (ok) {
            setManualOverrideStatus("Overrides saved.", "success");
          } else {
            setManualOverrideStatus("Failed to save overrides.", "error");
          }
          return ok;
        })
        .catch((error) => {
          setManualOverrideStatus("Failed to save overrides.", "error");
          throw error;
        });
    };

  const handleEntityListClick = (event) => {
        const addTrigger = event.target.closest('[data-role="entity-add-override"]');
        if (addTrigger) {
          event.preventDefault();
          const row = addTrigger.closest('[data-role="entity-row"]');
          if (!row) {
            return;
          }
          const inlineOverride = row.querySelector('[data-role="inline-override"]');
          if (!inlineOverride) {
            highlightMode = "manual";
            createOverrideFromData({
              token: addTrigger.dataset.entityToken || "",
              normalized: addTrigger.dataset.entityNormalized || "",
              context: addTrigger.dataset.entityContext || "",
              category: addTrigger.dataset.entityCategory || "",
              kind: addTrigger.dataset.entityKind || "",
              source: "entity",
            });
            return;
          }

          inlineOverride.hidden = false;
          inlineOverride.setAttribute("aria-hidden", "false");
          const pronInput = inlineOverride.querySelector('[data-role="manual-override-pronunciation"]');
          const voiceSelect = inlineOverride.querySelector('[data-role="manual-override-voice"]');
          const previewButton = inlineOverride.querySelector('[data-role="speaker-preview"]');
          const token = addTrigger.dataset.entityToken || row.querySelector('[data-role="entity-label"]')?.textContent || "";
          const normalized = addTrigger.dataset.entityNormalized || row.dataset.normalized || token;
          const context = addTrigger.dataset.entityContext || "";

          if (!row.dataset.hasOverride) {
            if (pronInput) {
              pronInput.value = "";
            }
            if (voiceSelect) {
              populateVoiceOptions(voiceSelect, "");
            }
          }

          inlineOverride.dataset.pendingToken = token;
          inlineOverride.dataset.pendingNormalized = normalized;
          inlineOverride.dataset.pendingContext = context;
          inlineOverride.dataset.pendingCategory = addTrigger.dataset.entityCategory || row.dataset.entityCategory || "";
          inlineOverride.dataset.pendingKind = addTrigger.dataset.entityKind || row.dataset.entityKind || "";

          const inlineState = extractInlineOverrideState(inlineOverride, row);
          syncInlinePreviewUI(row, inlineOverride, inlineState, previewButton);

          highlightMode = "inline";
          highlightedOverrideId = row.dataset.overrideId || "";
          pronInput?.focus({ preventScroll: true });
          return;
        }

        const saveTrigger = event.target.closest('[data-role="inline-override-save"]');
        if (saveTrigger) {
          event.preventDefault();
          const inlineOverride = saveTrigger.closest('[data-role="inline-override"]');
          const row = saveTrigger.closest('[data-role="entity-row"]');
          if (!inlineOverride || !row) {
            return;
          }
          const inlineState = extractInlineOverrideState(inlineOverride, row);
          syncInlinePreviewUI(row, inlineOverride, inlineState);
          void persistInlineOverrideState(inlineState);
          return;
        }

        const removeTrigger = event.target.closest('[data-role="inline-override-remove"]');
        if (removeTrigger) {
          event.preventDefault();
          const row = removeTrigger.closest('[data-role="entity-row"]');
          if (!row) {
            return;
          }
          const overrideId = row.dataset.overrideId;
          if (overrideId) {
            deleteManualOverride(overrideId);
          } else {
            const inlineOverride = removeTrigger.closest('[data-role="inline-override"]');
            if (inlineOverride) {
              inlineOverride.hidden = true;
              inlineOverride.setAttribute("aria-hidden", "true");
            }
          }
        }
    };

    [peopleListNode, entityListNode].forEach((list) => {
      if (!list) return;
      list.addEventListener("click", handleEntityListClick);
    });

    if (manualOverrideSearchButton) {
      manualOverrideSearchButton.addEventListener("click", () => {
        const query = manualOverrideQueryInput?.value?.trim() || "";
        performManualOverrideSearch(query);
      });
    }

    if (manualOverrideQueryInput) {
      manualOverrideQueryInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          performManualOverrideSearch(manualOverrideQueryInput.value.trim());
        }
      });
    }

    if (manualOverrideAddCustomButton) {
      manualOverrideAddCustomButton.addEventListener("click", () => {
        const token = window.prompt("Enter the token to override:");
        if (!token) return;
        highlightMode = "manual";
        createOverrideFromData({ token: token.trim(), source: "manual" });
      });
    }

    if (manualOverrideResultsList) {
      manualOverrideResultsList.addEventListener("click", (event) => {
        const resultButton = event.target.closest('[data-role="manual-override-result"]');
        if (!resultButton) return;
        event.preventDefault();
        highlightMode = "manual";
        createOverrideFromData({
          token: resultButton.dataset.token || "",
          normalized: resultButton.dataset.normalized || "",
          context: resultButton.dataset.context || "",
          pronunciation: resultButton.dataset.pronunciation || "",
          voice: resultButton.dataset.voice || "",
          source: resultButton.dataset.source || "search",
        });
      });
    }

    if (manualOverrideList) {
      manualOverrideList.addEventListener("input", (event) => {
        const input = event.target.closest('[data-role="manual-override-pronunciation"]');
        if (!input) return;
        const overrideId = input.dataset.overrideId || input.closest('[data-override-id]')?.dataset.overrideId;
        const container = input.closest(".manual-override");
        const previewButton = container?.querySelector('[data-role="speaker-preview"]');
        if (previewButton) {
          const fallback = container?.dataset.token || input.placeholder || "";
          const previewValue = joinPossessivePreviewSamples(input.value.trim(), fallback);
          previewButton.dataset.previewText = previewValue || input.value.trim() || fallback;
        }
        if (overrideId) {
          markOverrideDirty(overrideId);
        }
      });

      manualOverrideList.addEventListener("change", (event) => {
        const select = event.target.closest('[data-role="manual-override-voice"]');
        if (!select) return;
        const overrideId = select.dataset.overrideId || select.closest('[data-override-id]')?.dataset.overrideId;
        const container = select.closest(".manual-override");
        const previewButton = container?.querySelector('[data-role="speaker-preview"]');
        if (previewButton) {
          previewButton.dataset.voice = select.value || baseVoice || select.dataset.defaultVoice || "";
        }
        if (overrideId) {
          markOverrideDirty(overrideId);
        }
      });

      manualOverrideList.addEventListener("click", (event) => {
        const previewButton = event.target.closest('[data-role="speaker-preview"]');
        if (previewButton?.dataset.overrideId) {
          void flushManualOverrides({ overrideId: previewButton.dataset.overrideId });
        }
        const deleteButton = event.target.closest('[data-role="manual-override-delete"]');
        if (!deleteButton) return;
        event.preventDefault();
        const overrideId = deleteButton.dataset.overrideId;
        if (!overrideId) return;
        deleteManualOverride(overrideId);
      });
    }

    const initialTab = tabButtons.find((button) => button.classList.contains("is-active"));
    activateEntityTab(initialTab?.dataset.panel || "people");
    renderEntitySummary();
    renderManualOverrides();
    renderHeteronymOverrides();
    triggerEntitiesRefresh();
  }

  const handleDeferredSubmit = (event) => {
    const hasDirty = dirtyOverrideIds.size > 0;
    const hasPendingFlush = Boolean(overrideFlushPromise);
    if (!hasDirty && !hasPendingFlush) return;
    if (form.dataset.skipDirtyFlush === "true") {
      delete form.dataset.skipDirtyFlush;
      return;
    }
    event.preventDefault();
    const submitter = event.submitter || null;
    const resumeSubmission = () => {
      form.dataset.skipDirtyFlush = "true";
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit(submitter || undefined);
      } else if (submitter && typeof submitter.click === "function") {
        submitter.click();
      } else if (typeof form.submit === "function") {
        form.submit();
      }
    };

    const flushPromise = overrideFlushPromise || flushManualOverrides();
    if (!flushPromise) {
      resumeSubmission();
      return;
    }
    flushPromise.finally(resumeSubmission);
  };

  form.addEventListener("submit", handleDeferredSubmit);

  form.addEventListener("click", (event) => {
    const previewFromOverride = event.target.closest('[data-role="speaker-preview"]');
    if (previewFromOverride) {
      const entityRow = previewFromOverride.closest('[data-role="entity-row"]');
      const inlineOverride = entityRow?.querySelector('[data-role="inline-override"]');
      if (inlineOverride && !inlineOverride.hidden) {
        const inlineState = extractInlineOverrideState(inlineOverride, entityRow);
        syncInlinePreviewUI(entityRow, inlineOverride, inlineState, previewFromOverride);
        void persistInlineOverrideState(inlineState);
      }
    }
    if (previewFromOverride?.dataset.overrideId) {
      void flushManualOverrides({ overrideId: previewFromOverride.dataset.overrideId });
    }
    const genderMenu = event.target.closest('[data-role="gender-menu"]');
    const genderPill = event.target.closest('[data-role="gender-pill"]');
    if (!genderMenu && !genderPill) {
      hideGenderMenus();
    }

    if (genderPill) {
      event.preventDefault();
      const menu = genderPill.parentElement?.querySelector('[data-role="gender-menu"]');
      const isOpen = menu && !menu.hidden;
      hideGenderMenus();
      if (menu && !isOpen) {
        menu.hidden = false;
        menu.setAttribute("aria-hidden", "false");
        genderPill.classList.add("is-open");
      }
      return;
    }

    const genderOption = event.target.closest('[data-role="gender-option"]');
    if (genderOption) {
      event.preventDefault();
      const container = genderOption.closest('[data-role="speaker-gender"]');
      setGenderForSpeaker(container, genderOption.dataset.value);
      hideGenderMenus();
      return;
    }

    const nextSampleButton = event.target.closest('[data-role="speaker-next-sample"]');
    if (nextSampleButton) {
      event.preventDefault();
      const container = nextSampleButton.closest(".speaker-list__item");
      if (!container) return;
      const currentIndex = sampleIndexState.get(container) || 0;
      setSpeakerSample(container, currentIndex + 1);
      return;
    }

    const clearMixButton = event.target.closest('[data-role="clear-mix"]');
    if (clearMixButton) {
      event.preventDefault();
      const container = clearMixButton.closest(".speaker-list__item");
      applyFormulaToSpeaker(container, "");
      return;
    }

    const generateButton = event.target.closest('[data-role="generate-voice"]');
    if (generateButton) {
      event.preventDefault();
      const container = generateButton.closest(".speaker-list__item");
      if (!container) return;
      const genderInput = container.querySelector('[data-role="gender-input"]');
      const genderValue = genderInput?.value || "unknown";
      const mix = buildRandomMix(genderValue);
      if (!mix) {
        console.warn("No voices available to generate a mix for", genderValue);
        return;
      }
      const formula = formatMix(normaliseMix(mix));
      applyFormulaToSpeaker(container, formula);
      return;
    }

    const modalTrigger = event.target.closest('[data-role="open-voice-browser"]');
    if (modalTrigger) {
      event.preventDefault();
      const container = modalTrigger.closest(".speaker-list__item");
      if (!container) return;
      const sampleIndex = Number.parseInt(modalTrigger.dataset.sampleIndex || "0", 10);
      openVoiceBrowser(container, Number.isNaN(sampleIndex) ? 0 : sampleIndex);
      return;
    }

    const chip = event.target.closest('[data-role="recommended-voice"]');
    if (!chip) return;
    event.preventDefault();
    const container = chip.closest(".speaker-list__item");
    if (!container) return;
    const select = container.querySelector('[data-role="speaker-voice"]');
    if (!select) return;
    select.value = chip.dataset.voice || "";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    select.dataset.prevManual = select.value || "";
  });

  form.addEventListener("input", (event) => {
    const inlineOverride = event.target.closest('[data-role="inline-override"]');
    if (!inlineOverride || inlineOverride.hidden) {
      return;
    }
    const entityRow = inlineOverride.closest('[data-role="entity-row"]');
    const inlineState = extractInlineOverrideState(inlineOverride, entityRow);
    syncInlinePreviewUI(entityRow, inlineOverride, inlineState);
    if (inlineState) {
      setManualOverrideStatus("Unsaved changes", "pending");
    }
  });

  form.addEventListener("change", (event) => {
    const inlineOverride = event.target.closest('[data-role="inline-override"]');
    if (!inlineOverride || inlineOverride.hidden) {
      return;
    }
    const entityRow = inlineOverride.closest('[data-role="entity-row"]');
    const inlineState = extractInlineOverrideState(inlineOverride, entityRow);
    syncInlinePreviewUI(entityRow, inlineOverride, inlineState);
    if (inlineState) {
      setManualOverrideStatus("Unsaved changes", "pending");
    }
  });

  document.addEventListener("click", (event) => {
    if (!form.contains(event.target)) {
      hideGenderMenus();
    }
  });
};

window.AbogenPrepare = window.AbogenPrepare || {};
window.AbogenPrepare.init = initPrepare;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => initPrepare());
} else {
  initPrepare();
}
