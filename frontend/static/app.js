let activeDocumentId = null;
let activeConversationId = null;
let chatHistory = [];

const fileInput = document.getElementById("fileInput");
const dropZone = document.getElementById("dropZone");
const uploadStatus = document.getElementById("uploadStatus");
const documentsList = document.getElementById("documentsList");
const refreshDocsBtn = document.getElementById("refreshDocsBtn");
const conversationsList = document.getElementById("conversationsList");
const newChatBtn = document.getElementById("newChatBtn");

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
const viewActiveDocBtn = document.getElementById("viewActiveDocBtn");
const sourceInspector = document.getElementById("sourceInspector");
const sourceDocumentName = document.getElementById("sourceDocumentName");
const sourceLocation = document.getElementById("sourceLocation");
const sourceExcerpt = document.getElementById("sourceExcerpt");
const mainLayout = document.querySelector(".main-layout");
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const citationRecords = new WeakMap();

// Accordion elements
const docsHeader = document.getElementById("docsHeader");
const docsBody = document.getElementById("docsBody");
const convsHeader = document.getElementById("convsHeader");
const convsBody = document.getElementById("convsBody");

// Centered PDF Modal elements
const pdfModal = document.getElementById("pdfModal");
const pdfModalTitle = document.getElementById("pdfModalTitle");
const pdfFrame = document.getElementById("pdfFrame");
const pdfModalCloseBtn = document.getElementById("pdfModalCloseBtn");

// Confirmation Dialogs
const docDeleteDialog = document.getElementById("docDeleteDialog");
const deleteDocName = document.getElementById("deleteDocName");
const deleteDocCancelBtn = document.getElementById("deleteDocCancelBtn");
const deleteDocConfirmBtn = document.getElementById("deleteDocConfirmBtn");
let pendingDocDeleteId = null;

const convDeleteDialog = document.getElementById("convDeleteDialog");
const deleteConvTitle = document.getElementById("deleteConvTitle");
const deleteConvCancelBtn = document.getElementById("deleteConvCancelBtn");
const deleteConvConfirmBtn = document.getElementById("deleteConvConfirmBtn");
let pendingConvDeleteId = null;
let pendingConvDeleteDocId = null;

const docSwitchDialog = document.getElementById("docSwitchDialog");
const switchFromDocName = document.getElementById("switchFromDocName");
const switchToDocName = document.getElementById("switchToDocName");
const switchCancelBtn = document.getElementById("switchCancelBtn");
const switchKeepChatBtn = document.getElementById("switchKeepChatBtn");
const switchNewChatBtn = document.getElementById("switchNewChatBtn");
let pendingSwitchDoc = null;

// Evidence Corpus Search View
const corpusView = document.getElementById("corpusView");
const qaWorkspace = document.getElementById("qaWorkspace");
const closeCorpusViewBtn = document.getElementById("closeCorpusViewBtn");
const corpusSearchInput = document.getElementById("corpusSearchInput");
const corpusSearchBtn = document.getElementById("corpusSearchBtn");
const corpusResults = document.getElementById("corpusResults");
const qaNavTab = document.querySelector('.top-nav-link[href="#qaWorkspace"]');
const corpusNavTab = document.querySelector('.top-nav-link[href="#documentsList"]');

function resetWorkspaceState() {
  activeDocumentId = null;
  activeConversationId = null;
  chatHistory = [];
  chatMessages.replaceChildren(emptyState);
  emptyState.hidden = false;
  closeSourceInspector();
  activeDocName.textContent = "No document selected";
  activeDocStats.textContent = "None selected";
  inputDocName.textContent = "Document context unavailable";
  emptyDocName.textContent = "a selected document";
  readinessStatus.textContent = "Awaiting document";
  readinessStatus.classList.remove("ready");
  readinessDetails.textContent = "Select an indexed document to view its available page and chunk counts.";
  readinessPages.textContent = "—";
  readinessChunks.textContent = "—";
  questionInput.disabled = true;
  sendBtn.disabled = true;
  viewActiveDocBtn.disabled = true;
  questionInput.placeholder = "Select a document first to ask questions...";
  document.querySelectorAll(".question-suggestion").forEach((suggestion) => {
    suggestion.disabled = true;
  });
}

// Event Listeners
document.addEventListener("DOMContentLoaded", async () => {
  resetWorkspaceState();
  await fetchDocuments();
  await fetchConversations();

  // Restore saved active conversation on page reload if present
  const savedActiveConv = localStorage.getItem("legal_qa_active_conv");
  if (savedActiveConv) {
    activeConversationId = savedActiveConv;
    await loadSavedConversation(savedActiveConv);
  }
});

// Accordion Collapsible Sections Logic (Mutually Exclusive, Start Collapsed)
if (docsHeader && docsBody) {
  docsHeader.addEventListener("click", () => {
    const isExpanded = docsHeader.getAttribute("aria-expanded") === "true";
    if (isExpanded) {
      docsBody.hidden = true;
      docsHeader.setAttribute("aria-expanded", "false");
    } else {
      docsBody.hidden = false;
      docsHeader.setAttribute("aria-expanded", "true");
      // Close conversations section
      if (convsBody && convsHeader) {
        convsBody.hidden = true;
        convsHeader.setAttribute("aria-expanded", "false");
      }
    }
  });
}

if (convsHeader && convsBody) {
  convsHeader.addEventListener("click", () => {
    const isExpanded = convsHeader.getAttribute("aria-expanded") === "true";
    if (isExpanded) {
      convsBody.hidden = true;
      convsHeader.setAttribute("aria-expanded", "false");
    } else {
      convsBody.hidden = false;
      convsHeader.setAttribute("aria-expanded", "true");
      // Close documents section
      if (docsBody && docsHeader) {
        docsBody.hidden = true;
        docsHeader.setAttribute("aria-expanded", "false");
      }
    }
  });
}

// PDF Modal Controls
if (pdfModalCloseBtn && pdfModal) {
  pdfModalCloseBtn.addEventListener("click", () => {
    pdfModal.close();
    if (pdfFrame) pdfFrame.src = "about:blank";
  });
}

// Document Delete Dialog Controls
if (deleteDocCancelBtn && docDeleteDialog) {
  deleteDocCancelBtn.addEventListener("click", () => {
    pendingDocDeleteId = null;
    docDeleteDialog.close();
  });
}
if (deleteDocConfirmBtn) {
  deleteDocConfirmBtn.addEventListener("click", confirmDeleteDocument);
}

// Conversation Delete Dialog Controls
if (deleteConvCancelBtn && convDeleteDialog) {
  deleteConvCancelBtn.addEventListener("click", () => {
    pendingConvDeleteId = null;
    pendingConvDeleteDocId = null;
    convDeleteDialog.close();
  });
}
if (deleteConvConfirmBtn) {
  deleteConvConfirmBtn.addEventListener("click", confirmDeleteConversation);
}

// Document Switch Dialog Controls
if (switchCancelBtn && docSwitchDialog) {
  switchCancelBtn.addEventListener("click", () => {
    pendingSwitchDoc = null;
    docSwitchDialog.close();
  });
}
if (switchKeepChatBtn && docSwitchDialog) {
  switchKeepChatBtn.addEventListener("click", () => {
    if (pendingSwitchDoc) {
      executeSelectDocument(pendingSwitchDoc.id, pendingSwitchDoc.name, pendingSwitchDoc.pages, pendingSwitchDoc.chunks, false);
      pendingSwitchDoc = null;
    }
    docSwitchDialog.close();
  });
}
if (switchNewChatBtn && docSwitchDialog) {
  switchNewChatBtn.addEventListener("click", () => {
    if (pendingSwitchDoc) {
      executeSelectDocument(pendingSwitchDoc.id, pendingSwitchDoc.name, pendingSwitchDoc.pages, pendingSwitchDoc.chunks, true);
      pendingSwitchDoc = null;
    }
    docSwitchDialog.close();
  });
}

// Top Navbar Navigation: QA Chat vs Evidence Corpus
if (qaNavTab) {
  qaNavTab.addEventListener("click", (e) => {
    e.preventDefault();
    showQaWorkspace();
  });
}
if (corpusNavTab) {
  corpusNavTab.addEventListener("click", (e) => {
    e.preventDefault();
    showCorpusView();
  });
}
if (closeCorpusViewBtn) {
  closeCorpusViewBtn.addEventListener("click", showQaWorkspace);
}

function showQaWorkspace() {
  if (qaWorkspace) qaWorkspace.hidden = false;
  if (corpusView) corpusView.hidden = true;
  if (qaNavTab) qaNavTab.classList.add("active");
  if (corpusNavTab) corpusNavTab.classList.remove("active");
}

function showCorpusView() {
  if (qaWorkspace) qaWorkspace.hidden = true;
  if (corpusView) corpusView.hidden = false;
  if (qaNavTab) qaNavTab.classList.remove("active");
  if (corpusNavTab) corpusNavTab.classList.add("active");
  // Expand indexed documents in sidebar if collapsed
  if (docsBody && docsBody.hidden && docsHeader) {
    docsHeader.click();
  }
}

// Evidence Corpus Search Execution
if (corpusSearchBtn && corpusSearchInput) {
  corpusSearchBtn.addEventListener("click", executeCorpusSearch);
  corpusSearchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      executeCorpusSearch();
    }
  });
}

async function executeCorpusSearch() {
  const query = corpusSearchInput.value.trim();
  if (!query) return;
  if (!corpusResults) return;

  corpusResults.innerHTML = "<p class='empty-text'>Searching evidentiary repository...</p>";
  try {
    const docId = activeDocumentId || "";
    // Query chat or search endpoint
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: docId || "all",
        question: `Find all passages concerning: ${query}`
      })
    });
    const result = await res.json();
    const sources = result?.data?.sources || [];
    if (sources.length === 0) {
      corpusResults.innerHTML = `<p class='empty-text'>No matching evidentiary passages found for "${query}".</p>`;
      return;
    }

    corpusResults.innerHTML = "";
    sources.forEach(src => {
      const card = document.createElement("div");
      card.className = "corpus-result-card";
      card.innerHTML = `
        <div class="corpus-result-meta">${src.document_name || "Document"} · Page ${src.page_number} · Section ${src.section || "General"}</div>
        <div class="corpus-result-text">“${src.snippet}”</div>
      `;
      corpusResults.appendChild(card);
    });
  } catch (err) {
    corpusResults.innerHTML = `<p class='empty-text' style='color:#ef4444;'>Search failed: ${err.message}</p>`;
  }
}

if (newChatBtn) {
  newChatBtn.addEventListener("click", startNewConversation);
}

uploadOpenBtn.addEventListener("click", () => uploadDialog.showModal());
viewActiveDocBtn.addEventListener("click", () => {
  if (!activeDocumentId) return;
  openDocumentViewer(activeDocumentId);
});

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
    const payload = {
      document_id: activeDocumentId,
      question: question,
      history: chatHistory
    };
    if (activeConversationId) {
      payload.conversation_id = activeConversationId;
    }

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const result = await res.json();
    if (!res.ok) {
      throw new Error(result.detail || "Error querying legal document.");
    }

    const { answer, sources, confidence, disclaimer, telemetry, conversation_id, audit_trace } = result.data;
    if (conversation_id) {
      activeConversationId = conversation_id;
      localStorage.setItem("legal_qa_active_conv", conversation_id);
      if (activeDocumentId) {
        localStorage.setItem(`legal_qa_conv_${activeDocumentId}`, conversation_id);
      }
      fetchConversations();
    }

    appendAssistantMessage(answer, sources, confidence, disclaimer, telemetry, audit_trace);
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
  const allowed = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff"];
  const lowerName = file.name.toLowerCase();
  const isAllowed = allowed.some(ext => lowerName.endsWith(ext));
  if (!isAllowed) {
    showStatus("Only PDF and image files (.png, .jpg, .jpeg, .webp, .tiff) are supported.", "error");
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

    const actions = document.createElement("div");
    actions.className = "doc-item-actions";

    const viewButton = document.createElement("button");
    viewButton.className = "view-btn";
    viewButton.type = "button";
    viewButton.textContent = "View";
    viewButton.title = "Open document PDF";
    viewButton.addEventListener("click", (event) => {
      event.stopPropagation();
      openDocumentViewer(doc.document_id);
    });

    const deleteButton = document.createElement("button");
    deleteButton.className = "del-btn";
    deleteButton.type = "button";
    deleteButton.title = "Delete document";
    deleteButton.setAttribute("aria-label", `Delete ${doc.original_filename || doc.filename}`);
    deleteButton.textContent = "×";
    deleteButton.addEventListener("click", (event) => deleteDocument(event, doc.document_id));

    actions.append(viewButton, deleteButton);
    item.append(selectButton, actions);
    return item;
  });
  documentsList.replaceChildren(...documentItems);
}

function openDocumentViewer(documentId) {
  if (!documentId) return;
  const docTitle = activeDocName?.textContent || "Document Preview";
  if (pdfModalTitle) pdfModalTitle.textContent = docTitle;
  if (pdfFrame) pdfFrame.src = `/api/documents/${documentId}/file`;
  if (pdfModal) pdfModal.showModal();
}

function handleSelectDocumentClick(id, name, pages, chunks) {
  // If inside an existing conversation with messages and switching document, prompt confirmation
  if (activeDocumentId && activeDocumentId !== id && chatHistory.length > 0) {
    pendingSwitchDoc = { id, name, pages, chunks };
    if (switchFromDocName) switchFromDocName.textContent = activeDocName.textContent;
    if (switchToDocName) switchToDocName.textContent = name;
    if (docSwitchDialog) {
      docSwitchDialog.showModal();
      return;
    }
  }
  executeSelectDocument(id, name, pages, chunks, false);
}

function executeSelectDocument(id, name, pages, chunks, startNewChat = false) {
  if (activeDocumentId !== id || startNewChat) {
    chatHistory = [];
    chatMessages.replaceChildren(emptyState);
    emptyState.hidden = false;
    closeSourceInspector();
    if (startNewChat) {
      activeConversationId = null;
    } else {
      activeConversationId = localStorage.getItem(`legal_qa_conv_${id}`) || null;
      if (activeConversationId) {
        loadSavedConversation(activeConversationId);
      }
    }
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
  viewActiveDocBtn.disabled = false;
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

function selectDocument(id, name, pages, chunks) {
  handleSelectDocumentClick(id, name, pages, chunks);
}

function closeSidebar() {
  mainLayout.classList.remove("sidebar-open");
  sidebarBackdrop.hidden = true;
  sidebarToggle.setAttribute("aria-expanded", "false");
}

function deleteDocument(event, id, name = "this document") {
  event.stopPropagation();
  pendingDocDeleteId = id;
  if (deleteDocName) deleteDocName.textContent = name;
  if (docDeleteDialog) docDeleteDialog.showModal();
}

async function confirmDeleteDocument() {
  if (!pendingDocDeleteId) return;
  const id = pendingDocDeleteId;
  pendingDocDeleteId = null;
  if (docDeleteDialog) docDeleteDialog.close();

  try {
    const res = await fetch(`/api/documents/${id}`, { method: "DELETE" });
    if (res.ok) {
      if (activeDocumentId === id) {
        resetWorkspaceState();
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

function appendAssistantMessage(text, sources = [], confidence = "supported", disclaimer = "", telemetry = null, auditTrace = null) {
  const msgEl = document.createElement("div");
  msgEl.className = "message assistant";
  msgEl.dataset.confidence = confidence;
  const content = document.createElement("div");
  content.className = "message-content";

  const statusRow = document.createElement("div");
  statusRow.className = "status-row";
  statusRow.style.display = "flex";
  statusRow.style.alignItems = "center";
  statusRow.style.gap = "8px";
  statusRow.style.flexWrap = "wrap";
  statusRow.style.marginBottom = "8px";

  const answerStatus = document.createElement("div");
  answerStatus.className = `answer-status ${getConfidenceClass(confidence)}`;
  answerStatus.textContent = getConfidenceLabel(confidence);
  statusRow.appendChild(answerStatus);

  if (auditTrace?.selected_tools?.length) {
    const toolBadge = document.createElement("span");
    toolBadge.className = "tool-badge";
    toolBadge.style.fontSize = "11px";
    toolBadge.style.padding = "2px 8px";
    toolBadge.style.borderRadius = "12px";
    toolBadge.style.background = "#e0e7ff";
    toolBadge.style.color = "#3730a3";
    toolBadge.style.fontWeight = "600";
    toolBadge.textContent = `🛠 ${auditTrace.selected_tools.join(", ")}`;
    statusRow.appendChild(toolBadge);
  }

  content.appendChild(statusRow);

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
    // Unique Evidence Deduplication (by document + page + normalized snippet)
    const seenEvidence = new Set();
    const uniqueSources = [];
    for (const c of sources) {
      const normSnippet = (c.snippet || "").trim().toLowerCase().replace(/\s+/g, " ");
      const key = `${c.document_id || c.document_name}_p${c.page_number}_${normSnippet.slice(0, 80)}`;
      if (!seenEvidence.has(key)) {
        seenEvidence.add(key);
        uniqueSources.push(c);
      }
    }

    if (uniqueSources.length > 0) {
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "source-toggle-link";
      toggleBtn.innerHTML = `<span>▤ View Source (${uniqueSources.length} unique citation${uniqueSources.length === 1 ? "" : "s"})</span>`;

      const sourcesContainer = document.createElement("section");
      sourcesContainer.className = "sources-container";
      sourcesContainer.style.display = "none";

      const sourcesHeader = document.createElement("div");
      sourcesHeader.className = "sources-header";
      sourcesHeader.textContent = `Evidentiary sources · ${uniqueSources.length} citation${uniqueSources.length === 1 ? "" : "s"}`;
      sourcesContainer.appendChild(sourcesHeader);

      uniqueSources.forEach((citation) => {
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

      toggleBtn.addEventListener("click", () => {
        const isHidden = sourcesContainer.style.display === "none";
        sourcesContainer.style.display = isHidden ? "flex" : "none";
        toggleBtn.innerHTML = isHidden
          ? `<span>▲ Hide Source (${uniqueSources.length})</span>`
          : `<span>▤ View Source (${uniqueSources.length} unique citation${uniqueSources.length === 1 ? "" : "s"})</span>`;
      });

      content.appendChild(toggleBtn);
      content.appendChild(sourcesContainer);
    }
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
  if (confidence === "insufficient_context" || confidence === "not_found") return "insufficient";
  if (confidence === "low_confidence") return "low";
  if (confidence === "clarification_required") return "partial";
  if (confidence === "conflicting_evidence") return "low";
  if (confidence === "error") return "error";
  return "supported";
}

function getConfidenceLabel(confidence) {
  const labels = {
    supported: "Supported by retrieved evidence",
    partially_supported: "Partially supported by document",
    insufficient_context: "Insufficient context",
    not_found: "Information not found in document",
    low_confidence: "Low confidence",
    clarification_required: "Clarification required",
    conflicting_evidence: "Conflicting evidence identified",
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
    sendBtn.innerHTML = "<span>Ask</span>";
    questionInput.focus();
  }
}

async function fetchConversations() {
  if (!conversationsList) return;
  try {
    const res = await fetch("/api/conversations?limit=30");
    if (!res.ok) return;
    const result = await res.json();
    const convs = result.data || [];
    renderConversationsList(convs);
  } catch (err) {
    console.error("Error fetching conversations:", err);
  }
}

function renderConversationsList(convs) {
  if (!conversationsList) return;
  if (convs.length === 0) {
    const emptyP = document.createElement("p");
    emptyP.className = "empty-text";
    emptyP.textContent = "No active threads.";
    conversationsList.replaceChildren(emptyP);
    return;
  }

  const items = convs.map((conv) => {
    const item = document.createElement("div");
    item.className = `conv-item ${conv.conversation_id === activeConversationId ? "active" : ""}`;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "conv-item-btn";

    const titleSpan = document.createElement("span");
    titleSpan.className = "conv-item-title";
    titleSpan.textContent = conv.title || "Consultation Thread";

    const metaSpan = document.createElement("span");
    metaSpan.className = "conv-item-meta";
    metaSpan.textContent = `${conv.message_count || 0} messages`;

    btn.append(titleSpan, metaSpan);
    btn.addEventListener("click", () => switchConversation(conv.conversation_id));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "conv-del-btn del-btn";
    delBtn.title = "Delete conversation thread";
    delBtn.setAttribute("aria-label", `Delete thread ${conv.title || "Consultation Thread"}`);
    delBtn.textContent = "×";
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openDeleteConversationDialog(conv.conversation_id, conv.document_ids?.[0] || activeDocumentId || "", conv.title || "this conversation");
    });

    item.append(btn, delBtn);
    return item;
  });

  conversationsList.replaceChildren(...items);
}

function openDeleteConversationDialog(convId, docId, title) {
  pendingConvDeleteId = convId;
  pendingConvDeleteDocId = docId;
  if (deleteConvTitle) deleteConvTitle.textContent = title;
  if (convDeleteDialog) convDeleteDialog.showModal();
}

async function confirmDeleteConversation() {
  if (!pendingConvDeleteId) return;
  const convId = pendingConvDeleteId;
  const docId = pendingConvDeleteDocId || activeDocumentId || "";
  pendingConvDeleteId = null;
  pendingConvDeleteDocId = null;
  if (convDeleteDialog) convDeleteDialog.close();

  try {
    const url = `/api/conversations/${convId}?document_id=${encodeURIComponent(docId)}`;
    const res = await fetch(url, { method: "DELETE" });
    if (res.ok) {
      if (activeConversationId === convId) {
        activeConversationId = null;
        localStorage.removeItem("legal_qa_active_conv");
        if (activeDocumentId) localStorage.removeItem(`legal_qa_conv_${activeDocumentId}`);
        chatHistory = [];
        chatMessages.replaceChildren(emptyState);
        emptyState.hidden = false;
        closeSourceInspector();
      }
      fetchConversations();
    }
  } catch (err) {
    console.error("Failed to delete conversation:", err);
  }
}

async function switchConversation(conversationId) {
  if (!conversationId) return;
  activeConversationId = conversationId;
  localStorage.setItem("legal_qa_active_conv", conversationId);
  await loadSavedConversation(conversationId);
  fetchConversations();
}

function generateContextualConvTitle(docName) {
  const cleanName = (docName || "Legal Doc").replace(/\.[^/.]+$/, "");
  const timeStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `${cleanName} — Legal Consultation (${timeStr})`;
}

async function startNewConversation() {
  if (!activeDocumentId) {
    alert("Please select a document first before starting a new conversation.");
    return;
  }
  const title = generateContextualConvTitle(activeDocName.textContent);
  try {
    const res = await fetch("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: activeDocumentId,
        title: title
      })
    });
    if (!res.ok) return;
    const result = await res.json();
    const conv = result.data;
    activeConversationId = conv.conversation_id;
    localStorage.setItem(`legal_qa_conv_${activeDocumentId}`, conv.conversation_id);
    localStorage.setItem("legal_qa_active_conv", conv.conversation_id);
    chatHistory = [];
    chatMessages.replaceChildren(emptyState);
    emptyState.hidden = false;
    closeSourceInspector();
    fetchConversations();
    questionInput.focus();
  } catch (err) {
    console.error("Failed to create new conversation:", err);
  }
}

async function loadSavedConversation(conversationId) {
  try {
    const res = await fetch(`/api/conversations/${conversationId}`);
    if (!res.ok) return;
    const result = await res.json();
    const conv = result.data;
    if (!conv) return;

    // If conversation is bound to a document not yet active, auto-activate if available
    if (conv.document_ids && conv.document_ids.length > 0 && !activeDocumentId) {
      const primaryDocId = conv.document_ids[0];
      const docRes = await fetch(`/api/documents/${primaryDocId}`);
      if (docRes.ok) {
        const docData = (await docRes.json()).data;
        if (docData) {
          selectDocument(docData.document_id, docData.original_filename || docData.filename, docData.page_count, docData.chunk_count);
        }
      }
    }

    if (!conv.messages || conv.messages.length === 0) {
      chatMessages.replaceChildren(emptyState);
      emptyState.hidden = false;
      chatHistory = [];
      return;
    }

    emptyState.hidden = true;
    chatMessages.replaceChildren();
    chatHistory = [];

    for (const msg of conv.messages) {
      if (msg.role === "user") {
        appendUserMessage(msg.content);
        chatHistory.push({ role: "user", content: msg.content });
      } else if (msg.role === "assistant") {
        appendAssistantMessage(
          msg.content,
          msg.sources || [],
          msg.evidence_state || "supported",
          "This tool provides information extracted from uploaded legal documents and is not a substitute for formal legal advice from a qualified attorney.",
          msg.telemetry
        );
        chatHistory.push({ role: "assistant", content: msg.content });
      }
    }
  } catch (err) {
    console.error("Failed to restore saved conversation:", err);
  }
}
