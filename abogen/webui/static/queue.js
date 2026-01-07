import { initReaderUI } from "./reader.js";

const queueState = (window.AbogenQueueState = window.AbogenQueueState || {
  boundOverwritePrompt: false,
});

const handleOverwritePrompt = (event) => {
  const detail = event?.detail || {};
  const title = detail.title || "this item";
  const message = detail.message || `Audiobookshelf already has "${title}". Overwrite?`;
  if (!window.confirm(message)) {
    return;
  }

  const url = detail.url;
  if (!url || typeof htmx === "undefined") {
    return;
  }

  const target = detail.target || "#jobs-panel";
  const values = { overwrite: "true" };
  if (detail.values && typeof detail.values === "object") {
    Object.assign(values, detail.values);
  }

  htmx.ajax("POST", url, {
    target,
    swap: "innerHTML",
    values,
  });
};

const initQueuePage = () => {
  initReaderUI();
  if (!queueState.boundOverwritePrompt) {
    queueState.boundOverwritePrompt = true;
    document.addEventListener("audiobookshelf-overwrite-prompt", handleOverwritePrompt);
  }
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initQueuePage, { once: true });
} else {
  initQueuePage();
}
