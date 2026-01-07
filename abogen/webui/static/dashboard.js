import { initReaderUI } from "./reader.js";
import { initWizard } from "./wizard.js";

const dashboardState = (window.AbogenDashboardState = window.AbogenDashboardState || {
  boundKeydown: false,
  boundBeforeUnload: false,
});

const initDashboard = () => {
  const uploadModal =
    document.querySelector('[data-role="new-job-modal"]') ||
    document.querySelector('[data-role="upload-modal"]');
  const openModalButtons = document.querySelectorAll('[data-role="open-upload-modal"]');
  const scope = uploadModal || document;
  const sourceFileInput = scope.querySelector('#source_file');
  const dropzone = document.querySelector('[data-role="upload-dropzone"]');
  const dropzoneFilename = document.querySelector('[data-role="upload-dropzone-filename"]');

  const parseJSONScript = (id) => {
    const element = document.getElementById(id);
    if (!element) return null;
    try {
      const raw = element.textContent || "";
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      console.warn(`Failed to parse JSON script: ${id}`, error);
      return null;
    }
  };

  const profileSelect = scope.querySelector('[data-role="voice-profile"]');
  const voiceField = scope.querySelector('[data-role="voice-field"]');
  const voiceSelect = scope.querySelector('[data-role="voice-select"]');
  const formulaField = scope.querySelector('[data-role="formula-field"]');
  const formulaInput = scope.querySelector('[data-role="voice-formula"]');
  const languageSelect = uploadModal?.querySelector("#language") || document.getElementById("language");
  const speedInput = uploadModal?.querySelector('#speed') || document.getElementById('speed');
  const previewButton = scope.querySelector('[data-role="voice-preview-button"]');
  const previewStatus = scope.querySelector('[data-role="voice-preview-status"]');
  const previewAudio = scope.querySelector('[data-role="voice-preview-audio"]');
  const sampleVoiceTexts = parseJSONScript('voice-sample-texts') || {};

  const setDropzoneStatus = (message, state = "") => {
    if (!dropzoneFilename) return;
    if (!message) {
      dropzoneFilename.hidden = true;
      dropzoneFilename.textContent = "";
      dropzoneFilename.removeAttribute("data-state");
      return;
    }
    dropzoneFilename.hidden = false;
    dropzoneFilename.textContent = message;
    if (state) {
      dropzoneFilename.dataset.state = state;
    } else {
      dropzoneFilename.removeAttribute("data-state");
    }
  };

  const updateDropzoneFilename = () => {
    if (!sourceFileInput) {
      setDropzoneStatus("");
      return;
    }
    const file = sourceFileInput.files && sourceFileInput.files[0];
    if (file) {
      setDropzoneStatus(`Selected: ${file.name}`);
    } else {
      setDropzoneStatus("");
    }
  };

  const assignDroppedFile = (file) => {
    if (!sourceFileInput || !file) {
      return false;
    }
    try {
      if (typeof DataTransfer === "undefined") {
        throw new Error("DataTransfer API unavailable");
      }
      const transfer = new DataTransfer();
      transfer.items.add(file);
      sourceFileInput.files = transfer.files;
      sourceFileInput.dispatchEvent(new Event("change", { bubbles: true }));
      try {
        sourceFileInput.focus({ preventScroll: true });
      } catch (error) {
        // Ignore focus errors
      }
      return true;
    } catch (error) {
      console.warn("Unable to assign dropped file to input", error);
      setDropzoneStatus("Drag & drop isn't supported here. Click to choose a file instead.", "error");
      return false;
    }
  };

  const setDropzoneActive = (isActive) => {
    if (!dropzone) return;
    dropzone.classList.toggle("is-dragging", isActive);
    if (isActive) {
      dropzone.dataset.state = "drag";
    } else {
      delete dropzone.dataset.state;
    }
  };

  let lastTrigger = null;
  let previewAbortController = null;
  let previewObjectUrl = null;
  let suppressPauseStatus = false;

  const dispatchUploadModalEvent = (type, detail = {}) => {
    const eventName = `upload-modal:${type}`;
    if (uploadModal) {
      uploadModal.dispatchEvent(new CustomEvent(eventName, { detail, bubbles: true }));
      return;
    }
    document.dispatchEvent(new CustomEvent(eventName, { detail }));
  };

  const openUploadModal = (trigger) => {
    if (!uploadModal) return;
    lastTrigger = trigger || null;
    uploadModal.hidden = false;
    uploadModal.dataset.open = "true";
    document.body.classList.add("modal-open");
    const focusTarget = uploadModal.querySelector("#source_file") || uploadModal.querySelector("#source_text") || uploadModal;
    if (focusTarget instanceof HTMLElement) {
      focusTarget.focus({ preventScroll: true });
    }
    dispatchUploadModalEvent("open", { trigger: lastTrigger });
  };

  const closeUploadModal = () => {
    if (!uploadModal || uploadModal.hidden) {
      return;
    }
    uploadModal.hidden = true;
    delete uploadModal.dataset.open;
    document.body.classList.remove("modal-open");
    if (lastTrigger && lastTrigger instanceof HTMLElement) {
      lastTrigger.focus({ preventScroll: true });
    }
    dispatchUploadModalEvent("close", { trigger: lastTrigger });
  };

  openModalButtons.forEach((button) => {
    if (!button || button.dataset.dashboardBound === "true") {
      return;
    }
    button.dataset.dashboardBound = "true";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      openUploadModal(button);
    });
  });

  if (uploadModal && uploadModal.dataset.dashboardCloseBound !== "true") {
    uploadModal.dataset.dashboardCloseBound = "true";
    uploadModal.addEventListener("click", (event) => {
      const target = event.target;
      if (
        target instanceof Element &&
        (target.closest('[data-role="new-job-modal-close"]') ||
          target.closest('[data-role="upload-modal-close"]') ||
          target.closest('[data-role="wizard-close"]') ||
          target.closest('[data-role="wizard-cancel"]'))
      ) {
        event.preventDefault();
        closeUploadModal();
      }
    });
  }

  if (!dashboardState.boundKeydown) {
    dashboardState.boundKeydown = true;
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        if (uploadModal && !uploadModal.hidden) {
          closeUploadModal();
          return;
        }
      }
    });
  }

  initReaderUI({ onBeforeOpen: closeUploadModal });

  if (sourceFileInput) {
    if (sourceFileInput.dataset.dashboardChangeBound !== "true") {
      sourceFileInput.dataset.dashboardChangeBound = "true";
      sourceFileInput.addEventListener("change", updateDropzoneFilename);
    }
    updateDropzoneFilename();
  } else {
    setDropzoneStatus("");
  }

  const resolveSampleText = (language) => {
    const fallback = typeof sampleVoiceTexts === "object" && sampleVoiceTexts?.a
      ? sampleVoiceTexts.a
      : "This is a sample of the selected voice.";
    if (!language || typeof sampleVoiceTexts !== "object" || !sampleVoiceTexts) {
      return fallback;
    }
    const normalizedKey = language.toLowerCase();
    if (typeof sampleVoiceTexts[normalizedKey] === "string" && sampleVoiceTexts[normalizedKey].trim()) {
      return sampleVoiceTexts[normalizedKey];
    }
    const baseKey = normalizedKey.split(/[_.-]/)[0];
    if (baseKey && typeof sampleVoiceTexts[baseKey] === "string" && sampleVoiceTexts[baseKey].trim()) {
      return sampleVoiceTexts[baseKey];
    }
    return fallback;
  };

  const getSelectedLanguage = () => {
    const value = languageSelect?.value || "a";
    return (value || "a").trim() || "a";
  };

  const getSelectedSpeed = () => {
    const raw = speedInput?.value || "1";
    const parsed = Number.parseFloat(raw);
    return Number.isFinite(parsed) ? parsed : 1;
  };

  const cancelPreviewRequest = () => {
    if (!previewAbortController) return;
    previewAbortController.abort();
    previewAbortController = null;
  };

  const stopPreviewAudio = () => {
    if (previewAudio) {
      suppressPauseStatus = true;
      try {
        previewAudio.pause();
      } catch (error) {
        // Ignore pause errors
      }
      previewAudio.removeAttribute("src");
      previewAudio.load();
      previewAudio.hidden = true;
      suppressPauseStatus = false;
    }
    if (previewObjectUrl) {
      URL.revokeObjectURL(previewObjectUrl);
      previewObjectUrl = null;
    }
  };

  const setPreviewStatus = (message, state = "") => {
    if (!previewStatus) return;
    if (!message) {
      previewStatus.textContent = "";
      previewStatus.hidden = true;
      previewStatus.removeAttribute("data-state");
      return;
    }
    previewStatus.textContent = message;
    previewStatus.hidden = false;
    if (state) {
      previewStatus.dataset.state = state;
    } else {
      previewStatus.removeAttribute("data-state");
    }
  };

  const setPreviewLoading = (isLoading) => {
    if (!previewButton) return;
    previewButton.disabled = isLoading;
    if (isLoading) {
      previewButton.dataset.loading = "true";
    } else {
      previewButton.removeAttribute("data-loading");
    }
  };

  const buildPreviewRequest = () => {
    const language = getSelectedLanguage();
    const speed = getSelectedSpeed();
    const basePayload = {
      language,
      speed,
      max_seconds: 8,
      text: resolveSampleText(language),
    };

    const profileValue = profileSelect?.value || "__standard";

    if (profileValue && profileValue !== "__standard") {
      if (profileValue === "__formula") {
        const formulaValue = (formulaInput?.value || "").trim();
        if (!formulaValue) {
          return { error: "Enter a custom voice formula to preview." };
        }
        return {
          endpoint: "/api/voice-profiles/preview",
          payload: { ...basePayload, formula: formulaValue },
        };
      }
      return {
        endpoint: "/api/voice-profiles/preview",
        payload: { ...basePayload, profile: profileValue },
      };
    }

    const selectedVoice = (voiceSelect?.value || voiceSelect?.dataset.default || "").trim();
    if (!selectedVoice) {
      return { error: "Select a narrator voice to preview." };
    }
    return {
      endpoint: "/api/speaker-preview",
      payload: { ...basePayload, voice: selectedVoice },
    };
  };

  const resetPreview = () => {
    cancelPreviewRequest();
    stopPreviewAudio();
    setPreviewStatus("", "");
  };

  if (previewAudio) {
    previewAudio.addEventListener("ended", () => {
      setPreviewStatus("Preview finished", "info");
    });
    previewAudio.addEventListener("pause", () => {
      if (suppressPauseStatus || previewAudio.ended || previewAudio.currentTime === 0) {
        return;
      }
      setPreviewStatus("Preview paused", "info");
    });
  }

  const handleVoicePreview = async () => {
    if (!previewButton) return;
    const request = buildPreviewRequest();
    if (!request) {
      return;
    }
    if (request.error) {
      setPreviewStatus(request.error, "error");
      cancelPreviewRequest();
      stopPreviewAudio();
      return;
    }

    cancelPreviewRequest();
    stopPreviewAudio();
    previewAbortController = new AbortController();
    setPreviewLoading(true);
    setPreviewStatus("Generating preview…", "loading");

    try {
      const response = await fetch(request.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request.payload),
        signal: previewAbortController.signal,
      });
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || `Preview failed (status ${response.status})`);
      }
      const blob = await response.blob();
      previewObjectUrl = URL.createObjectURL(blob);
      if (previewAudio) {
        previewAudio.src = previewObjectUrl;
        previewAudio.hidden = false;
        try {
          await previewAudio.play();
          setPreviewStatus("Preview playing", "success");
        } catch (error) {
          setPreviewStatus("Preview ready. Press play to listen.", "success");
        }
      } else {
        setPreviewStatus("Preview ready.", "success");
      }
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }
      console.error("Voice preview failed", error);
      setPreviewStatus(error.message || "Preview failed", "error");
      stopPreviewAudio();
    } finally {
      setPreviewLoading(false);
    }
  };

  if (previewButton && previewButton.dataset.dashboardBound !== "true") {
    previewButton.dataset.dashboardBound = "true";
    previewButton.addEventListener("click", (event) => {
      event.preventDefault();
      handleVoicePreview();
    });
  }

  if (dropzone && dropzone.dataset.dashboardDragBound !== "true") {
    dropzone.dataset.dashboardDragBound = "true";
    let dragDepth = 0;

    dropzone.addEventListener("dragenter", (event) => {
      event.preventDefault();
      dragDepth += 1;
      setDropzoneActive(true);
    });

    dropzone.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "copy";
      }
    });

    const handleDragLeave = (event) => {
      if (event && dropzone.contains(event.relatedTarget)) {
        return;
      }
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) {
        setDropzoneActive(false);
      }
    };

    dropzone.addEventListener("dragleave", (event) => {
      handleDragLeave(event);
    });

    dropzone.addEventListener("dragend", () => {
      dragDepth = 0;
      setDropzoneActive(false);
    });

    dropzone.addEventListener("drop", (event) => {
      event.preventDefault();
      dragDepth = 0;
      setDropzoneActive(false);
      const files = event.dataTransfer && event.dataTransfer.files;
      if (!files || !files.length) {
        return;
      }
      openUploadModal(dropzone);
      assignDroppedFile(files[0]);
    });

    dropzone.addEventListener("click", (event) => {
      if (event.target.closest('[data-role="open-upload-modal"]')) {
        return;
      }
      openUploadModal(dropzone);
    });

    dropzone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openUploadModal(dropzone);
      }
    });
  }

  [voiceSelect, profileSelect, formulaInput, languageSelect, speedInput].forEach((input) => {
    if (!input) return;
    const eventName = input === formulaInput ? "input" : "change";
    input.addEventListener(eventName, () => {
      resetPreview();
    });
  });

  const hydrateDefaultVoice = () => {
    if (!voiceSelect) return;
    const defaultVoice = voiceSelect.dataset.default;
    if (!defaultVoice) return;
    const option = voiceSelect.querySelector(`option[value="${defaultVoice}"]`);
    if (option) {
      voiceSelect.value = defaultVoice;
    }
  };

  const applySavedProfile = (option) => {
    if (!option) return;
    const presetFormula = option.dataset.formula || "";
    const profileLang = option.dataset.language || "";
    if (formulaInput) {
      formulaInput.value = presetFormula;
      formulaInput.readOnly = true;
      formulaInput.dataset.state = "locked";
    }
    if (profileLang && languageSelect) {
      languageSelect.value = profileLang;
    }
  };

  const updateVoiceControls = () => {
    if (!profileSelect) {
      return;
    }
    const value = profileSelect.value || "__standard";
    const isStandard = value === "__standard";
    const isFormula = value === "__formula";
    const isSavedProfile = !isStandard && !isFormula;

    const showVoiceField = isStandard;
    if (voiceField) {
      voiceField.hidden = !showVoiceField;
      voiceField.setAttribute("aria-hidden", showVoiceField ? "false" : "true");
      voiceField.dataset.state = showVoiceField ? "visible" : "hidden";
    }
    if (voiceSelect) {
      voiceSelect.disabled = !isStandard;
      voiceSelect.dataset.state = isStandard ? "editable" : "locked";
      if (isStandard) {
        hydrateDefaultVoice();
      }
    }

    if (isSavedProfile) {
      applySavedProfile(profileSelect.selectedOptions[0] || null);
    } else if (!isFormula && formulaInput) {
      formulaInput.value = "";
    }

    const showFormulaField = isFormula;
    if (formulaField) {
      const shouldShow = showFormulaField;
      formulaField.hidden = !shouldShow;
      formulaField.setAttribute("aria-hidden", shouldShow ? "false" : "true");
      formulaField.dataset.state = shouldShow ? "visible" : "hidden";
    }
    if (formulaInput) {
      if (isFormula) {
        formulaInput.disabled = false;
        formulaInput.readOnly = false;
        formulaInput.dataset.state = "editable";
      } else if (isSavedProfile) {
        formulaInput.disabled = false;
        formulaInput.readOnly = true;
        formulaInput.dataset.state = "locked";
      } else {
        formulaInput.disabled = true;
        formulaInput.readOnly = true;
        formulaInput.value = "";
        formulaInput.dataset.state = "editable";
      }
    }
  };

  if (profileSelect) {
    if (profileSelect.dataset.dashboardBound !== "true") {
      profileSelect.dataset.dashboardBound = "true";
      profileSelect.addEventListener("change", updateVoiceControls);
    }
    updateVoiceControls();
  } else {
    hydrateDefaultVoice();
  }

  if (!dashboardState.boundBeforeUnload) {
    dashboardState.boundBeforeUnload = true;
    window.addEventListener("beforeunload", () => {
      cancelPreviewRequest();
      stopPreviewAudio();
    });
  }
};

window.AbogenDashboard = window.AbogenDashboard || {};
window.AbogenDashboard.init = initDashboard;

const bootDashboard = () => {
  initDashboard();
  initWizard();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootDashboard, { once: true });
} else {
  bootDashboard();
}
