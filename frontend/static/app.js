let activeDocumentId = null;
let chatHistory = [];

const fileInput = document.getElementById("fileInput");
const dropZone = document.getElementById("dropZone");
const uploadStatus = document.getElementById("uploadStatus");
const documentsList = document.getElementById("documentsList");
const refreshDocsBtn = document.getElementById("refreshDocsBtn");

const activeDocName = document.getElementById("activeDocName");
const activeDocStats = document.getElementById("activeDocStats");
const chatMessages = document.getElementById("chatMessages");
const chatForm = document.getElementById("chatForm");
const questionInput = document.getElementById("questionInput");
const sendBtn = document.getElementById("sendBtn");
const charCount = document.getElementById("charCount");
const inputDocName = document.getElementById("inputDocName");
const emptyDocName = document.getElementById("emptyDocName");
const emptyState = document.getElementById("emptyState");
const readinessStatus = document.getElementById("readinessStatus");
const readinessDetails = document.getElementById("readinessDetails");
const readinessPages = document.getElementById("readinessPages");
const readinessChunks = document.getElementById("readinessChunks");
const indexedCount = document.getElementById("indexedCount");
const uploadDialog = document.getElementById("uploadDialog");
const uploadOpenBtn = document.getElementById("uploadOpenBtn");
const sourceInspector = document.getElementById("sourceInspector");
const sourceDocumentName = document.getElementById("sourceDocumentName");
const sourceLocation = document.getElementById("sourceLocation");
const sourceExcerpt = document.getElementById("sourceExcerpt");
const mainLayout = document.querySelector(".main-layout");
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const citationRecords = new WeakMap();

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  fetchDocuments();
});

uploadOpenBtn.addEventListener("click", () => uploadDialog.showModal());

sidebarToggle.addEventListener("click", () => {
  if (mainLayout.classList.contains("sidebar-open")) {
    closeSidebar();
  } else {
    mainLayout.classList.add("sidebar-open");
    sidebarBackdrop.hidden = false;
    sidebarToggle.setAttribute("aria-expanded", "true");
  }
});

sidebarBackdrop.addEventListener("click", closeSidebar);

document.querySelector('.top-nav-link[href="#documentsList"]').addEventListener("click", (event) => {
  if (window.matchMedia("(max-width: 767px)").matches) {
    event.preventDefault();
    mainLayout.classList.add("sidebar-open");
    sidebarBackdrop.hidden = false;
    sidebarToggle.setAttribute("aria-expanded", "true");
  }
});

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragleave", (event) => {
  if (!dropZone.contains(event.relatedTarget)) {
    dropZone.classList.remove("drag-over");
  }
});

dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = event.dataTransfer.files[0];
  if (file) {
    uploadDialog.close();
    handleFileUpload(file);
  }
});

fileInput.addEventListener("change", (e) => {
  if (e.target.files.length > 0) {
    uploadDialog.close();
    handleFileUpload(e.target.files[0]);
  }
});

refreshDocsBtn.addEventListener("click", () => {
  fetchDocuments();
});

questionInput.addEventListener("input", (e) => {
  charCount.textContent = `${e.target.value.length}/1500`;
});

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

document.querySelectorAll(".question-suggestion").forEach((suggestion) => {
  suggestion.addEventListener("click", () => {
    if (!activeDocumentId) return;
    questionInput.value = suggestion.dataset.question;
    charCount.textContent = `${questionInput.value.length}/1500`;
    chatForm.requestSubmit();
  });
});

chatMessages.addEventListener("click", (event) => {
  const citationButton = event.target.closest(".citation-card");
  if (!citationButton) return;
  const citation = citationRecords.get(citationButton);
  if (citation) openSourceInspector(citation);
});

document.getElementById("sourceInspectorClose").addEventListener("click", closeSourceInspector);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!sourceInspector.hidden) closeSourceInspector();
    if (mainLayout.classList.contains("sidebar-open")) closeSidebar();
  }
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question || !activeDocumentId) return;

  emptyState.hidden = true;
  appendUserMessage(question);
  questionInput.value = "";
  charCount.textContent = "0/1500";
  setChatLoading(true);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: activeDocumentId,
        question: question,
        history: chatHistory
      })
    });

    const result = await res.json();
    if (!res.ok) {
      throw new Error(result.detail || "Error querying legal document.");
    }

    const { answer, sources, confidence, disclaimer, telemetry } = result.data;
    appendAssistantMessage(answer, sources, confidence, disclaimer, telemetry);
    chatHistory.push({ role: "user", content: question });
    chatHistory.push({ role: "assistant", content: answer });

  } catch (err) {
    appendAssistantMessage(`Error: ${err.message}`, [], "error");
  } finally {
    setChatLoading(false);
  }
});

// Document Upload
async function handleFileUpload(file) {
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    showStatus("Only PDF files are supported.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  showStatus(`Uploading and indexing "${file.name}"...`, "loading");

  try {
    const res = await fetch("/api/documents/upload", {
      method: "POST",
      body: formData
    });

    const result = await res.json();
    if (!res.ok) {
      throw new Error(result.detail || "Failed to process PDF.");
    }

    showStatus(`Successfully indexed "${result.data.original_filename}"!`, "success");
    await fetchDocuments();
    selectDocument(result.data.document_id, result.data.original_filename, result.data.page_count, result.data.chunk_count);
  } catch (err) {
    showStatus(err.message, "error");
  }
}
function showStatus(msg, type) {
  uploadStatus.textContent = msg;
  uploadStatus.className = `status-box ${type}`;
}

// Fetch and List Documents
async function fetchDocuments() {
  try {
    const res = await fetch("/api/documents");
    const result = await res.json();
    if (!res.ok) return;

    const docs = result.data || [];
    renderDocumentsList(docs);
  } catch (err) {
    console.error("Error fetching documents:", err);
  }
}

function renderDocumentsList(docs) {
  indexedCount.textContent = String(docs.length);
  if (docs.length === 0) {
    const emptyMessage = document.createElement("p");
    emptyMessage.className = "empty-text";
    emptyMessage.textContent = "No documents in this corpus yet.";
    documentsList.replaceChildren(emptyMessage);
    return;
  }

  const documentItems = docs.map((doc) => {
    const item = document.createElement("div");
    item.className = `doc-item ${doc.document_id === activeDocumentId ? "active" : ""}`;

    const details = document.createElement("div");
    details.className = "doc-item-details";
    const title = document.createElement("div");
    title.className = "doc-item-title";
    title.textContent = doc.original_filename || doc.filename;
    const meta = document.createElement("div");
    meta.className = "doc-item-meta";
    meta.textContent = `${doc.page_count} pages · ${doc.chunk_count} chunks`;
    details.append(title, meta);

    const selectButton = document.createElement("button");
    selectButton.className = "doc-select";
    selectButton.type = "button";
    selectButton.setAttribute("aria-pressed", String(doc.document_id === activeDocumentId));
    const select = () => selectDocument(
      doc.document_id,
      doc.original_filename || doc.filename,
      doc.page_count,
      doc.chunk_count
    );
    selectButton.addEventListener("click", select);
    selectButton.appendChild(details);

    const deleteButton = document.createElement("button");
    deleteButton.className = "del-btn";
    deleteButton.type = "button";
    deleteButton.title = "Delete document";
    deleteButton.setAttribute("aria-label", `Delete ${doc.original_filename || doc.filename}`);
    deleteButton.textContent = "×";
    deleteButton.addEventListener("click", (event) => deleteDocument(event, doc.document_id));

    item.append(selectButton, deleteButton);
    return item;
  });
  documentsList.replaceChildren(...documentItems);
}

function selectDocument(id, name, pages, chunks) {
  if (activeDocumentId !== id) {
    chatHistory = [];
    chatMessages.replaceChildren(emptyState);
    emptyState.hidden = false;
    closeSourceInspector();
  }
  activeDocumentId = id;
  activeDocName.textContent = name;
  activeDocStats.textContent = `${pages} Pages | ${chunks} Chunks`;
  inputDocName.textContent = name;
  emptyDocName.textContent = name;
  readinessStatus.textContent = "Indexed";
  readinessStatus.classList.add("ready");
  readinessDetails.textContent = "This document is available as the active context for questions.";
  readinessPages.textContent = String(pages);
  readinessChunks.textContent = String(chunks);
  questionInput.disabled = false;
  sendBtn.disabled = false;
  questionInput.placeholder = "Ask a question about this legal document...";
  document.querySelectorAll(".question-suggestion").forEach((suggestion) => {
    suggestion.disabled = false;
  });
  questionInput.focus();

  // Highlight active
  document.querySelectorAll(".doc-item").forEach(item => item.classList.remove("active"));
  closeSidebar();
  fetchDocuments();
}

function closeSidebar() {
  mainLayout.classList.remove("sidebar-open");
  sidebarBackdrop.hidden = true;
  sidebarToggle.setAttribute("aria-expanded", "false");
}

async function deleteDocument(event, id) {
  event.stopPropagation();
  if (!confirm("Are you sure you want to delete this document and its indexed vectors?")) return;

  try {
    const res = await fetch(`/api/documents/${id}`, { method: "DELETE" });
    if (res.ok) {
      if (activeDocumentId === id) {
        activeDocumentId = null;
        chatHistory = [];
        chatMessages.replaceChildren(emptyState);
        emptyState.hidden = false;
        closeSourceInspector();
        activeDocName.textContent = "None selected";
        activeDocStats.textContent = "";
        inputDocName.textContent = "Document context unavailable";
        emptyDocName.textContent = "a selected document";
        readinessStatus.textContent = "Awaiting document";
        readinessStatus.classList.remove("ready");
        readinessDetails.textContent = "Select an indexed document to view its available page and chunk counts.";
        readinessPages.textContent = "—";
        readinessChunks.textContent = "—";
        questionInput.disabled = true;
        sendBtn.disabled = true;
        questionInput.placeholder = "Select a document first to ask questions...";
        document.querySelectorAll(".question-suggestion").forEach((suggestion) => {
          suggestion.disabled = true;
        });
      }
      fetchDocuments();
    }
  } catch (err) {
    alert("Failed to delete document: " + err.message);
  }
}

// Chat UI Appends
function appendUserMessage(text) {
  const msgEl = document.createElement("div");
  msgEl.className = "message user";
  const content = document.createElement("div");
  content.className = "message-content";
  const question = document.createElement("p");
  question.textContent = text;
  content.appendChild(question);
  msgEl.appendChild(content);
  chatMessages.appendChild(msgEl);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendAssistantMessage(text, sources = [], confidence = "supported", disclaimer = "", telemetry = null) {
  const msgEl = document.createElement("div");
  msgEl.className = "message assistant";
  msgEl.dataset.confidence = confidence;
  const content = document.createElement("div");
  content.className = "message-content";

  const answerStatus = document.createElement("div");
  answerStatus.className = `answer-status ${getConfidenceClass(confidence)}`;
  answerStatus.textContent = getConfidenceLabel(confidence);
  content.appendChild(answerStatus);

  const answer = document.createElement("p");
  answer.textContent = text;
  content.appendChild(answer);

  if (confidence === "insufficient_context") {
    const guidance = document.createElement("div");
    guidance.className = "refusal-guidance";
    guidance.textContent = "Try narrowing the inquiry to a specific party, obligation, date, or clause in the selected document.";
    content.appendChild(guidance);

    const telemetryDetails = [];
    if (Number.isFinite(telemetry?.retrieved_chunks_count)) {
      telemetryDetails.push(`${telemetry.retrieved_chunks_count} retrieved passages`);
    }
    if (Number.isFinite(telemetry?.retrieval_latency_ms)) {
      telemetryDetails.push(`${Math.round(telemetry.retrieval_latency_ms)} ms retrieval`);
    }
    if (telemetryDetails.length) {
      const telemetryLine = document.createElement("div");
      telemetryLine.className = "refusal-telemetry";
      telemetryLine.textContent = `Retrieval record · ${telemetryDetails.join(" · ")}`;
      content.appendChild(telemetryLine);
    }
  }

  if (sources?.length) {
    const sourcesContainer = document.createElement("section");
    sourcesContainer.className = "sources-container";
    const sourcesHeader = document.createElement("div");
    sourcesHeader.className = "sources-header";
    sourcesHeader.textContent = `Verified evidentiary sources · ${sources.length} citation${sources.length === 1 ? "" : "s"}`;
    sourcesContainer.appendChild(sourcesHeader);

    sources.forEach((citation) => {
      const citationButton = document.createElement("button");
      citationButton.type = "button";
      citationButton.className = "citation-card";
      citationButton.setAttribute("aria-label", `Inspect ${citation.document_name}, page ${citation.page_number}`);
      citationRecords.set(citationButton, citation);

      const documentName = document.createElement("strong");
      documentName.className = "citation-document";
      documentName.textContent = citation.document_name || "Source document";
      const citationMeta = document.createElement("span");
      citationMeta.className = "citation-meta";
      citationMeta.textContent = `Page ${citation.page_number} · Section ${citation.section || "General"}`;
      const snippet = document.createElement("span");
      snippet.className = "citation-snippet";
      snippet.textContent = `“${citation.snippet || "No excerpt returned."}”`;
      const inspectLabel = document.createElement("span");
      inspectLabel.className = "citation-open";
      inspectLabel.textContent = "Inspect source excerpt →";
      citationButton.append(documentName, citationMeta, snippet, inspectLabel);
      sourcesContainer.appendChild(citationButton);
    });
    content.appendChild(sourcesContainer);
  }

  if (disclaimer) {
    const disclaimerLine = document.createElement("div");
    disclaimerLine.className = "response-disclaimer";
    disclaimerLine.textContent = disclaimer;
    content.appendChild(disclaimerLine);
  }

  msgEl.appendChild(content);
  chatMessages.appendChild(msgEl);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function getConfidenceClass(confidence) {
  if (confidence === "partially_supported") return "partial";
  if (confidence === "insufficient_context") return "insufficient";
  if (confidence === "low_confidence") return "low";
  if (confidence === "error") return "error";
  return "supported";
}

function getConfidenceLabel(confidence) {
  const labels = {
    supported: "Supported by retrieved evidence",
    partially_supported: "Partially supported by document",
    insufficient_context: "Insufficient context",
    low_confidence: "Low confidence",
    error: "Request could not be completed"
  };
  return labels[confidence] || "Response status unavailable";
}

function openSourceInspector(citation) {
  sourceDocumentName.textContent = citation.document_name || "Source document";
  sourceLocation.textContent = `Page ${citation.page_number} · Section ${citation.section || "General"}`;
  sourceExcerpt.textContent = citation.snippet || "No source excerpt was returned for this citation.";
  sourceInspector.hidden = false;
  sourceInspector.setAttribute("aria-hidden", "false");
  mainLayout.classList.add("inspector-open");
  document.getElementById("sourceInspectorClose").focus();
}

function closeSourceInspector() {
  sourceInspector.hidden = true;
  sourceInspector.setAttribute("aria-hidden", "true");
  mainLayout.classList.remove("inspector-open");
}

function setChatLoading(isLoading) {
  sendBtn.disabled = isLoading;
  questionInput.disabled = isLoading || !activeDocumentId;
  if (isLoading) {
    sendBtn.innerHTML = "<span>...</span>";
  } else {
    sendBtn.innerHTML = "<span>Ask</span> ➔";
    questionInput.focus();
  }
}
