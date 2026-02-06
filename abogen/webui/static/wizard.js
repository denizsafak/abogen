const STEP_ORDER = ["book", "chapters", "entities"];
const STEP_META = {
  book: {
    index: 1,
    title: "Book parameters",
    hint: "Choose your source file or paste text, then set the defaults used for chapter analysis and speaker casting.",
  },
  chapters: {
    index: 2,
    title: "Select chapters",
    hint: "Choose which chapters to convert. We'll analyse entities automatically when you continue.",
  },
  entities: {
    index: 3,
    title: "Review entities",
    hint: "Assign pronunciations, voices, and manual overrides before queueing the conversion.",
  },
};

const wizardState = (window.AbogenWizardState = window.AbogenWizardState || {
  initialized: false,
  modal: null,
  stage: null,
  submitting: false,
  initialStep: "book",
  initialStageMarkup: "",
});

const normalizeStep = (step) => {
  let value = (step || "book").toLowerCase();
  if (value === "speakers") {
    value = "entities";
  }
  if (value === "settings" || value === "upload" || value === "") {
    value = "book";
  }
  if (!STEP_ORDER.includes(value)) {
    return "book";
  }
  return value;
};

const setButtonLoading = (button, isLoading) => {
  if (!button) {
    return;
  }
  if (isLoading) {
    if (!button.dataset.originalDisabled) {
      button.dataset.originalDisabled = button.disabled ? "true" : "false";
    }
    button.disabled = true;
    button.dataset.loading = "true";
    button.setAttribute("aria-busy", "true");
  } else {
    if (button.dataset.loading) {
      delete button.dataset.loading;
    }
    button.removeAttribute("aria-busy");
    const original = button.dataset.originalDisabled;
    if (original !== undefined) {
      button.disabled = original === "true";
      delete button.dataset.originalDisabled;
    } else {
      button.disabled = false;
    }
  }
};

const setSubmitting = (modal, isSubmitting, button) => {
  if (!modal) return;
  wizardState.submitting = isSubmitting;
  if (isSubmitting) {
    modal.dataset.submitting = "true";
    modal.setAttribute("aria-busy", "true");
  } else {
    delete modal.dataset.submitting;
    modal.removeAttribute("aria-busy");
  }
  setButtonLoading(button, isSubmitting);
};

const resetWizardToInitial = () => {
  const modal = ensureModalRef();
  if (!modal) return;
  wizardState.submitting = false;
  delete modal.dataset.submitting;
  modal.removeAttribute("aria-busy");
  modal.dataset.pendingId = "";
  const step = normalizeStep(wizardState.initialStep || modal.dataset.step || "book");
  modal.dataset.step = step;
  updateHeaderCopy(modal, step);
  updateFilenameLabel(modal, "");
  const stage = modal.querySelector('[data-role="wizard-stage"]');
  if (stage) {
    wizardState.stage = stage;
    destroyTransientAlerts(stage);
    if (typeof wizardState.initialStageMarkup === "string" && wizardState.initialStageMarkup) {
      stage.innerHTML = wizardState.initialStageMarkup;
      reinitializeStageModules(stage);
    }
  }
};

const findModal = () => document.querySelector('[data-role="new-job-modal"]');

const ensureModalRef = () => {
  if (wizardState.modal && wizardState.modal.isConnected) {
    return wizardState.modal;
  }
  wizardState.modal = findModal();
  return wizardState.modal;
};

const dispatchWizardEvent = (modal, type, detail = {}) => {
  if (!modal) return;
  const event = new CustomEvent(`wizard:${type}`, { bubbles: true, detail });
  modal.dispatchEvent(event);
};

const destroyTransientAlerts = (stage) => {
  if (!stage) {
    return;
  }
  const alerts = stage.querySelectorAll('[data-role="wizard-error"]');
  alerts.forEach((alert) => alert.remove());
};

const displayTransientError = (modal, message) => {
  if (!modal) return;
  const stage = modal.querySelector('[data-role="wizard-stage"]');
  if (!stage) return;
  const existing = stage.querySelector('[data-role="wizard-error"]');
  if (existing) {
    existing.textContent = message;
    return;
  }
  const alert = document.createElement("div");
  alert.className = "alert alert--error";
  alert.dataset.role = "wizard-error";
  alert.textContent = message;
  stage.prepend(alert);
};

const updateStepIndicators = (modal, activeStep, payload) => {
  const indicators = modal.querySelectorAll('[data-role="wizard-step-indicator"]');
  const activeIndex = STEP_ORDER.indexOf(activeStep);
  const completedList = Array.isArray(payload?.completed_steps) ? payload.completed_steps : [];
  const completedSet = new Set(completedList.map((step) => normalizeStep(step)));
  indicators.forEach((indicator) => {
    const step = normalizeStep(indicator.dataset.step || "book");
    indicator.classList.remove("is-active", "is-complete");
    const index = STEP_ORDER.indexOf(step);
    const isActive = index === activeIndex;
    const visited = completedSet.has(step);
    const isComplete = !isActive && (visited || (index > -1 && index < activeIndex));
    indicator.classList.toggle("is-complete", isComplete);
    indicator.classList.toggle("is-active", isActive);
    if (indicator instanceof HTMLButtonElement) {
      const clickable = isComplete && !isActive;
      indicator.disabled = !clickable;
      indicator.setAttribute("aria-disabled", clickable ? "false" : "true");
      indicator.setAttribute("aria-current", isActive ? "step" : "false");
      if (clickable) {
        indicator.dataset.state = "clickable";
      } else {
        delete indicator.dataset.state;
      }
    }
  });
};

const updateHeaderCopy = (modal, step, payload) => {
  const meta = STEP_META[step];
  if (!meta) {
    return;
  }
  const titleEl = modal.querySelector("#new-job-modal-title");
  const hintEl = modal.querySelector('[data-role="wizard-hint"]');
  if (titleEl) {
    titleEl.textContent = payload?.title || meta.title;
  }
  if (hintEl) {
    hintEl.textContent = payload?.hint || meta.hint;
  }
  updateStepIndicators(modal, step, payload);
};

const updateFilenameLabel = (modal, filename) => {
  const label = modal.querySelector(".wizard-card__filename");
  if (!label) return;
  if (filename) {
    label.hidden = false;
    label.textContent = filename;
    label.setAttribute("title", filename);
  } else {
    label.hidden = true;
    label.textContent = "";
    label.removeAttribute("title");
  }
};

const reinitializeStageModules = (stage) => {
  if (!stage) return;
  if (window.AbogenDashboard?.init) {
    window.AbogenDashboard.init();
  }
  if (window.AbogenPrepare?.init) {
    window.AbogenPrepare.init(stage);
  }
};

const focusFirstInteractive = (stage) => {
  if (!stage) return;
  const focusable = stage.querySelector(
    'input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])'
  );
  if (focusable instanceof HTMLElement) {
    try {
      focusable.focus({ preventScroll: true });
    } catch (error) {
      // Ignore focus errors, browser may block programmatic focus
    }
  }
};

const applyWizardPayload = (payload) => {
  const modal = ensureModalRef();
  if (!modal) {
    return;
  }
  if (payload.pending_id !== undefined) {
    modal.dataset.pendingId = payload.pending_id || "";
  }
  const step = normalizeStep(payload.step || modal.dataset.step || "book");
  modal.dataset.step = step;
  modal.hidden = false;
  modal.dataset.open = "true";
  document.body.classList.add("modal-open");
  updateHeaderCopy(modal, step, payload);
  updateFilenameLabel(modal, payload.filename);

  const stage = modal.querySelector('[data-role="wizard-stage"]');
  if (stage) {
    destroyTransientAlerts(stage);
    stage.innerHTML = payload.html || "";
    wizardState.stage = stage;
    reinitializeStageModules(stage);
    focusFirstInteractive(stage);
  }

  const stepDetail = {
    step,
    index: STEP_META[step]?.index || STEP_ORDER.indexOf(step) + 1,
    total: STEP_ORDER.length,
    pendingId: modal.dataset.pendingId || "",
    notice: payload.notice || "",
    error: payload.error || "",
  };
  dispatchWizardEvent(modal, "step", stepDetail);
};

const handleWizardRedirect = (payload) => {
  const modal = ensureModalRef();
  if (!modal) return;
  modal.hidden = true;
  delete modal.dataset.open;
  document.body.classList.remove("modal-open");
  resetWizardToInitial();
  dispatchWizardEvent(modal, "done", { redirectUrl: payload.redirect_url });
  if (payload.redirect_url) {
    window.location.assign(payload.redirect_url);
  }
};

const processResponsePayload = (payload, responseOk) => {
  if (!payload) {
    return;
  }
  if (payload.redirect_url) {
    handleWizardRedirect(payload);
    return;
  }
  if (!payload.html && !responseOk) {
    const modal = ensureModalRef();
    displayTransientError(modal, payload.error || "Something went wrong. Try again.");
    return;
  }
  applyWizardPayload(payload);
};

const requestWizardStep = async (url, { method = "GET", body = undefined } = {}) => {
  const modal = ensureModalRef();
  if (!modal) return;
  try {
    const response = await fetch(url, {
      method,
      body,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    const text = await response.text();
    const payload = text ? JSON.parse(text) : null;
    processResponsePayload(payload, response.ok);
  } catch (error) {
    console.error("Wizard request failed", error);
    displayTransientError(modal, error?.message || "Unable to update the wizard. Try again.");
  }
};

const submitWizardForm = async (form, submitter) => {
  const modal = ensureModalRef();
  if (!modal) return;
  if (wizardState.submitting) {
    return;
  }
  const action = submitter?.getAttribute("formaction") || form.getAttribute("action") || window.location.href;
  const method = (submitter?.getAttribute("formmethod") || form.getAttribute("method") || "GET").toUpperCase();
  const stepTarget = submitter?.dataset?.stepTarget || "";
  const normalizedStepTarget = stepTarget ? stepTarget.toLowerCase() : "";
  if (normalizedStepTarget) {
    const activeInput = form.querySelector('[data-role="active-step-input"]');
    if (activeInput) {
      activeInput.value = normalizedStepTarget;
    }
  }
  const formData = new FormData(form);
  if (normalizedStepTarget) {
    formData.set("active_step", normalizedStepTarget);
    formData.set("next_step", normalizedStepTarget);
  }
  if (submitter && submitter.name && !formData.has(submitter.name)) {
    formData.append(submitter.name, submitter.value ?? "");
  }
  
  // Ensure pending_id is included if available in modal state but missing from form
  if (!formData.get("pending_id") && modal && modal.dataset.pendingId) {
    formData.set("pending_id", modal.dataset.pendingId);
  }

  const allowValidation = !submitter?.hasAttribute("formnovalidate") && !form.noValidate;
  if (allowValidation && typeof form.reportValidity === "function" && !form.reportValidity()) {
    return;
  }

  destroyTransientAlerts(modal.querySelector('[data-role="wizard-stage"]'));
  setSubmitting(modal, true, submitter);
  try {
    const response = await fetch(action, {
      method,
      body: formData,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch (parseError) {
      console.error("Failed to parse wizard response", parseError);
      displayTransientError(modal, "Received an invalid response. Try again.");
      return;
    }
    processResponsePayload(payload, response.ok);
    if (!response.ok && (!payload || !payload.html)) {
      displayTransientError(modal, payload?.error || `Request failed (${response.status})`);
    }
  } catch (networkError) {
    console.error("Wizard submission failed", networkError);
    displayTransientError(modal, networkError?.message || "Unable to submit form. Check your connection and try again.");
  } finally {
    setSubmitting(modal, false, submitter);
  }
};

const handleCancel = async (button) => {
  const modal = ensureModalRef();
  if (!modal) return;
  const pendingId = button?.dataset.pendingId || modal.dataset.pendingId;
  const template = modal.dataset.cancelUrlTemplate || "";
  if (!pendingId || !template) {
    modal.hidden = true;
    delete modal.dataset.open;
    document.body.classList.remove("modal-open");
    dispatchWizardEvent(modal, "cancel", { pendingId });
    return;
  }
  const url = template.replace("__pending__", encodeURIComponent(pendingId));
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (response.ok) {
      const text = await response.text();
      const payload = text ? JSON.parse(text) : null;
      if (payload?.redirect_url) {
        handleWizardRedirect(payload);
        return;
      }
    }
  } catch (error) {
    console.error("Cancel request failed", error);
  }
  modal.hidden = true;
  delete modal.dataset.open;
  document.body.classList.remove("modal-open");
  dispatchWizardEvent(modal, "cancel", { pendingId });
  resetWizardToInitial();
};

const navigateToWizardStep = (targetStep, pendingOverride) => {
  const modal = ensureModalRef();
  if (!modal || wizardState.submitting) {
    return;
  }
  const normalizedTarget = normalizeStep(targetStep || "book");
  const currentStep = modal.dataset.step ? normalizeStep(modal.dataset.step) : "book";
  if (normalizedTarget === currentStep) {
    return;
  }
  const pendingId = pendingOverride || modal.dataset.pendingId || "";
  const template = modal.dataset.prepareUrlTemplate || "";
  if (!pendingId || !template) {
    return;
  }
  const url = new URL(template.replace("__pending__", encodeURIComponent(pendingId)), window.location.origin);
  url.searchParams.set("step", normalizedTarget);
  url.searchParams.set("format", "json");
  requestWizardStep(url.toString(), { method: "GET" });
};

const handleBackToStep = (button) => {
  const targetStep = normalizeStep(button.dataset.targetStep || "book");
  navigateToWizardStep(targetStep, button.dataset.pendingId);
};

const handleWizardClick = (event) => {
  const modal = ensureModalRef();
  if (!modal) return;
  const closeTarget = event.target.closest('[data-role="new-job-modal-close"]');
  if (closeTarget) {
    event.preventDefault();
    event.stopPropagation();
    handleCancel(closeTarget);
    return;
  }
  const cancelButton = event.target.closest('[data-role="wizard-cancel"]');
  if (cancelButton) {
    event.preventDefault();
    event.stopPropagation();
    handleCancel(cancelButton);
    return;
  }
  const backButton = event.target.closest('[data-role="wizard-back"]');
  if (backButton) {
    const targetStep = normalizeStep(backButton.dataset.targetStep || "book");
    event.preventDefault();
    event.stopPropagation();
    handleBackToStep(backButton);
    return;
  }
  const indicator = event.target.closest('[data-role="wizard-step-indicator"]');
  if (indicator instanceof HTMLButtonElement) {
    if (indicator.classList.contains("is-complete")) {
      event.preventDefault();
      event.stopPropagation();
      navigateToWizardStep(indicator.dataset.step || "book");
    }
  }
};

const handleWizardSubmit = (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  if (form.dataset.wizardForm !== "true") {
    return;
  }
  const submitter = event.submitter || form.querySelector('button[type="submit"]');
  if (!submitter) {
    return;
  }
  event.preventDefault();
  submitWizardForm(form, submitter);
};

const initWizard = () => {
  if (wizardState.initialized) {
    return;
  }
  const modal = ensureModalRef();
  if (!modal) {
    return;
  }
  wizardState.initialized = true;
  wizardState.modal = modal;
  wizardState.stage = modal.querySelector('[data-role="wizard-stage"]');
  const initialStep = normalizeStep(modal.dataset.step || "book");
  if (!wizardState.initialStageMarkup && wizardState.stage) {
    wizardState.initialStageMarkup = wizardState.stage.innerHTML;
    wizardState.initialStep = initialStep;
  }
  modal.addEventListener("submit", handleWizardSubmit, true);
  modal.addEventListener("click", handleWizardClick);
};

window.AbogenWizard = window.AbogenWizard || {};
window.AbogenWizard.init = initWizard;
window.AbogenWizard.requestStep = requestWizardStep;
window.AbogenWizard.applyPayload = applyWizardPayload;

export { initWizard };
