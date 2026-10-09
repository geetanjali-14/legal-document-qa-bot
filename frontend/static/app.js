let activeDocumentId = null;
let activeDocumentName = "";
let activeDocumentPages = 0;
let activeDocumentChunks = 0;
let activeConversationId = null;
let chatHistory = [];
let allDocuments = [];

// DOM Elements
const fileInput = document.getElementById("fileInput");
const dropZone = document.getElementById("dropZone");
const uploadStatus = document.getElementById("uploadStatus");
const conversationsList = document.getElementById("conversationsList");
const newChatBtn = document.getElementById("newChatBtn");

const navChatBtn = document.getElementById("navChatBtn");
const navDocsBtn = document.getElementById("navDocsBtn");
const topNavDocCount = document.getElementById("topNavDocCount");
const viewAllDocsBtn = document.getElementById("viewAllDocsBtn");
const backToChatBtn = document.getElementById("backToChatBtn");
const qaWorkspace = document.getElementById("qaWorkspace");
const documentsView = document.getElementById("documentsView");
const documentsGrid = document.getElementById("documentsGrid");
const docsViewSearchInput = document.getElementById("docsViewSearchInput");
const docsViewUploadBtn = document.getElementById("docsViewUploadBtn");

// Chat Header & Document Selector
const activeDocName = document.getElementById("activeDocName");
const docSelectorBtn = document.getElementById("docSelectorBtn");
const docSelectorMenu = document.getElementById("docSelectorMenu");
const docFilterInput = document.getElementById("docFilterInput");
const docDropdownOptions = document.getElementById("docDropdownOptions");
const dropdownUploadBtn = document.getElementById("dropdownUploadBtn");
const clearDocContextBtn = document.getElementById("clearDocContextBtn");
const viewActiveDocBtn = document.getElementById("viewActiveDocBtn");

// Chat Content & Input
const chatMessages = document.getElementById("chatMessages");
const emptyState = document.getElementById("emptyState");
const emptyHeading = document.getElementById("emptyHeading");
const emptySubheading = document.getElementById("emptySubheading");
const emptyDocCard = document.getElementById("emptyDocCard");
const emptyDocTitle = document.getElementById("emptyDocTitle");
const emptyDocMeta = document.getElementById("emptyDocMeta");
const suggestedQuestionsGrid = document.getElementById("suggestedQuestionsGrid");
const chatForm = document.getElementById("chatForm");
const questionInput = document.getElementById("questionInput");
const sendBtn = document.getElementById("sendBtn");
const charCount = document.getElementById("charCount");

// Source Inspector
const sourceInspector = document.getElementById("sourceInspector");
const sourceDocumentName = document.getElementById("sourceDocumentName");
const sourceLocation = document.getElementById("sourceLocation");
const sourceExcerpt = document.getElementById("sourceExcerpt");
const sourceInspectorClose = document.getElementById("sourceInspectorClose");

// Sidebar & Layout
const mainLayout = document.querySelector(".main-layout");
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const uploadDialog = document.getElementById("uploadDialog");
const uploadOpenBtn = document.getElementById("uploadOpenBtn");
const uploadDialogCloseBtn = document.getElementById("uploadDialogCloseBtn");

// Modals
const pdfModal = document.getElementById("pdfModal");
const pdfModalTitle = document.getElementById("pdfModalTitle");
const pdfFrame = document.getElementById("pdfFrame");
const pdfModalCloseBtn = document.getElementById("pdfModalCloseBtn");

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

const citationRecords = new WeakMap();

// ==========================================
// Initialization
// ==========================================
document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await fetchDocuments();
  await fetchConversations();

  // Check saved conversation
  const savedActiveConv = localStorage.getItem("legal_qa_active_conv");
  if (savedActiveConv) {
    activeConversationId = savedActiveConv;
    await loadSavedConversation(savedActiveConv);
  } else {
    initNewChatState(null);
  }
});

function setupEventListeners() {
  // Navigation between Chat and Documents
  if (navChatBtn) navChatBtn.addEventListener("click", showChatWorkspace);
  if (navDocsBtn) navDocsBtn.addEventListener("click", showDocumentsView);
  if (viewAllDocsBtn) viewAllDocsBtn.addEventListener("click", showDocumentsView);
  if (backToChatBtn) backToChatBtn.addEventListener("click", showChatWorkspace);

  // New Chat
  if (newChatBtn) newChatBtn.addEventListener("click", () => handleStartNewChat());

  // Upload dialog triggers
  if (uploadOpenBtn) uploadOpenBtn.addEventListener("click", () => uploadDialog.showModal());
  if (docsViewUploadBtn) docsViewUploadBtn.addEventListener("click", () => uploadDialog.showModal());
  if (dropdownUploadBtn) {
    dropdownUploadBtn.addEventListener("click", () => {
      closeDocDropdown();
      uploadDialog.showModal();
    });
  }
  if (uploadDialogCloseBtn) {
    uploadDialogCloseBtn.addEventListener("click", () => uploadDialog.close());
  }

  // Document context selector dropdown
  if (docSelectorBtn) {
    docSelectorBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleDocDropdown();
    });
  }

  if (clearDocContextBtn) {
    clearDocContextBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      setDocumentContext(null);
    });
  }

  if (docFilterInput) {
    docFilterInput.addEventListener("input", (e) => {
      filterDropdownOptions(e.target.value);
    });
  }

  document.addEventListener("click", (e) => {
    if (docSelectorMenu && !docSelectorMenu.contains(e.target) && !docSelectorBtn.contains(e.target)) {
      closeDocDropdown();
    }
  });

  // View PDF
  if (viewActiveDocBtn) {
    viewActiveDocBtn.addEventListener("click", () => {
      if (activeDocumentId) openDocumentViewer(activeDocumentId);
    });
  }

  // Mobile sidebar
  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", () => {
      if (mainLayout.classList.contains("sidebar-open")) {
        closeSidebar();
      } else {
        mainLayout.classList.add("sidebar-open");
        sidebarBackdrop.hidden = false;
        sidebarToggle.setAttribute("aria-expanded", "true");
      }
    });
  }
  if (sidebarBackdrop) sidebarBackdrop.addEventListener("click", closeSidebar);

  // File Upload Drag & Drop
  if (dropZone) {
    dropZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropZone.classList.add("drag-over");
    });
    dropZone.addEventListener("dragleave", (e) => {
      if (!dropZone.contains(e.relatedTarget)) {
        dropZone.classList.remove("drag-over");
      }
    });
    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropZone.classList.remove("drag-over");
      const file = e.dataTransfer.files[0];
      if (file) {
        uploadDialog.close();
        handleFileUpload(file);
      }
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", (e) => {
      if (e.target.files.length > 0) {
        uploadDialog.close();
        handleFileUpload(e.target.files[0]);
      }
    });
  }

  // Documents view search
  if (docsViewSearchInput) {
    docsViewSearchInput.addEventListener("input", (e) => {
      renderDocumentsGrid(allDocuments, e.target.value);
    });
  }

  // Chat Form & Input
  if (questionInput) {
    questionInput.addEventListener("input", (e) => {
      charCount.textContent = `${e.target.value.length}/1500`;
    });
    questionInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        chatForm.requestSubmit();
      }
    });
  }

  if (chatForm) {
    chatForm.addEventListener("submit", handleChatSubmit);
  }

  // Citation inspection delegation
  if (chatMessages) {
    chatMessages.addEventListener("click", (e) => {
      const citationButton = e.target.closest(".citation-card");
      if (!citationButton) return;
      const citation = citationRecords.get(citationButton);
      if (citation) openSourceInspector(citation);
    });
  }

  if (sourceInspectorClose) {
    sourceInspectorClose.addEventListener("click", closeSourceInspector);
  }

  // Modals & Dialogs
  if (pdfModalCloseBtn && pdfModal) {
    pdfModalCloseBtn.addEventListener("click", () => {
      pdfModal.close();
      if (pdfFrame) pdfFrame.src = "about:blank";
    });
  }

  if (deleteDocCancelBtn && docDeleteDialog) {
    deleteDocCancelBtn.addEventListener("click", () => {
      pendingDocDeleteId = null;
      docDeleteDialog.close();
    });
  }
  if (deleteDocConfirmBtn) deleteDocConfirmBtn.addEventListener("click", confirmDeleteDocument);

  if (deleteConvCancelBtn && convDeleteDialog) {
    deleteConvCancelBtn.addEventListener("click", () => {
      pendingConvDeleteId = null;
      pendingConvDeleteDocId = null;
      convDeleteDialog.close();
    });
  }
  if (deleteConvConfirmBtn) deleteConvConfirmBtn.addEventListener("click", confirmDeleteConversation);

  if (switchCancelBtn && docSwitchDialog) {
    switchCancelBtn.addEventListener("click", () => {
      pendingSwitchDoc = null;
      docSwitchDialog.close();
    });
  }
  if (switchKeepChatBtn && docSwitchDialog) {
    switchKeepChatBtn.addEventListener("click", () => {
      if (pendingSwitchDoc) {
        // Multi-document continuation in current conversation
        executeSetDocumentContext(pendingSwitchDoc.id, pendingSwitchDoc.name, pendingSwitchDoc.pages, pendingSwitchDoc.chunks, false);
        pendingSwitchDoc = null;
      }
      docSwitchDialog.close();
    });
  }
  if (switchNewChatBtn && docSwitchDialog) {
    switchNewChatBtn.addEventListener("click", () => {
      if (pendingSwitchDoc) {
        executeSetDocumentContext(pendingSwitchDoc.id, pendingSwitchDoc.name, pendingSwitchDoc.pages, pendingSwitchDoc.chunks, true);
        pendingSwitchDoc = null;
      }
      docSwitchDialog.close();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!sourceInspector.hidden) closeSourceInspector();
      if (mainLayout.classList.contains("sidebar-open")) closeSidebar();
      if (docSelectorMenu && !docSelectorMenu.hidden) closeDocDropdown();
    }
  });
}

// ==========================================
// Views Switching
// ==========================================
function showChatWorkspace() {
  if (qaWorkspace) qaWorkspace.hidden = false;
  if (documentsView) documentsView.hidden = true;
  if (navChatBtn) navChatBtn.classList.add("active");
  if (navDocsBtn) navDocsBtn.classList.remove("active");
}

function showDocumentsView() {
  closeSourceInspector();
  closeDocDropdown();
  if (qaWorkspace) qaWorkspace.hidden = true;
  if (documentsView) documentsView.hidden = false;
  if (navChatBtn) navChatBtn.classList.remove("active");
  if (navDocsBtn) navDocsBtn.classList.add("active");
  renderDocumentsGrid(allDocuments);
}

function closeSidebar() {
  mainLayout.classList.remove("sidebar-open");
  if (sidebarBackdrop) sidebarBackdrop.hidden = true;
  if (sidebarToggle) sidebarToggle.setAttribute("aria-expanded", "false");
}

// ==========================================
// Document Context & Dropdown
// ==========================================
function toggleDocDropdown() {
  const isHidden = docSelectorMenu.hidden;
  if (isHidden) {
    docSelectorMenu.hidden = false;
    docSelectorBtn.setAttribute("aria-expanded", "true");
    if (docFilterInput) {
      docFilterInput.value = "";
      filterDropdownOptions("");
      docFilterInput.focus();
    }
  } else {
    closeDocDropdown();
  }
}

function closeDocDropdown() {
  if (docSelectorMenu) docSelectorMenu.hidden = true;
  if (docSelectorBtn) docSelectorBtn.setAttribute("aria-expanded", "false");
}

function filterDropdownOptions(filterText) {
  const query = (filterText || "").trim().toLowerCase();
  const options = docDropdownOptions.querySelectorAll(".doc-dropdown-option");
  options.forEach(opt => {
    const text = opt.textContent.toLowerCase();
    opt.style.display = text.includes(query) ? "flex" : "none";
  });
}

function renderDropdownOptions() {
  if (!docDropdownOptions) return;
  docDropdownOptions.innerHTML = "";

  // "No document" default option
  const noDocBtn = document.createElement("button");
  noDocBtn.type = "button";
  noDocBtn.className = `doc-dropdown-option ${!activeDocumentId ? "active" : ""}`;
  noDocBtn.dataset.docId = "";
  noDocBtn.innerHTML = `
    <span class="option-title">No document</span>
    <span class="option-desc">General legal inquiry</span>
  `;
  noDocBtn.addEventListener("click", () => {
    closeDocDropdown();
    setDocumentContext(null);
  });
  docDropdownOptions.appendChild(noDocBtn);

  allDocuments.forEach(doc => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `doc-dropdown-option ${doc.document_id === activeDocumentId ? "active" : ""}`;
    btn.dataset.docId = doc.document_id;
    const name = doc.original_filename || doc.filename;
    btn.innerHTML = `
      <span class="option-title">${escapeHtml(name)}</span>
      <span class="option-desc">${doc.page_count} page${doc.page_count === 1 ? "" : "s"}</span>
    `;
    btn.addEventListener("click", () => {
      closeDocDropdown();
      setDocumentContext(doc);
    });
    docDropdownOptions.appendChild(btn);
  });
}

function setDocumentContext(doc) {
  const nextId = doc ? doc.document_id : null;
  const nextName = doc ? (doc.original_filename || doc.filename) : "";
  const nextPages = doc ? doc.page_count : 0;
  const nextChunks = doc ? doc.chunk_count : 0;

  // If inside an existing conversation with messages and switching document, prompt confirmation
  if (activeDocumentId && nextId !== activeDocumentId && chatHistory.length > 0) {
    pendingSwitchDoc = { id: nextId, name: nextName, pages: nextPages, chunks: nextChunks };
    if (switchFromDocName) switchFromDocName.textContent = activeDocumentName || "Current Document";
    if (switchToDocName) switchToDocName.textContent = nextName || "No Document (General)";
    if (docSwitchDialog) {
      docSwitchDialog.showModal();
      return;
    }
  }

  executeSetDocumentContext(nextId, nextName, nextPages, nextChunks, false);
}

function executeSetDocumentContext(id, name, pages, chunks, startNewChat = false) {
  const previousDocId = activeDocumentId;
  activeDocumentId = id;
  activeDocumentName = name;
  activeDocumentPages = pages;
  activeDocumentChunks = chunks;

  if (startNewChat) {
    initNewChatState(id ? { document_id: id, original_filename: name, page_count: pages, chunk_count: chunks } : null);
  } else {
    // If we changed to a different document and chat is empty or not continuing, ensure stale conv ID is not leaked
    if (previousDocId && id && previousDocId !== id && chatHistory.length === 0) {
      activeConversationId = null;
      localStorage.removeItem("legal_qa_active_conv");
    }
    updateContextDisplay();
    // If empty chat state is shown, refresh the empty state cards & questions
    if (!chatMessages.querySelector(".message")) {
      renderEmptyState();
    }
  }

  renderDropdownOptions();
  renderConversationsListHighlight();
}

function updateContextDisplay() {
  if (activeDocumentId) {
    if (activeDocName) activeDocName.textContent = activeDocumentName;
    if (clearDocContextBtn) clearDocContextBtn.hidden = false;
    if (viewActiveDocBtn) viewActiveDocBtn.disabled = false;
    if (questionInput) questionInput.placeholder = `Ask anything about ${activeDocumentName}...`;
  } else {
    if (activeDocName) activeDocName.textContent = "No document selected";
    if (clearDocContextBtn) clearDocContextBtn.hidden = true;
    if (viewActiveDocBtn) viewActiveDocBtn.disabled = true;
    if (questionInput) questionInput.placeholder = "Ask a legal question or inquiry...";
  }
}

// ==========================================
// Empty State & Suggested Questions
// ==========================================
function getDocumentSuggestions(docName) {
  const lower = (docName || "").toLowerCase();

  if (lower.includes("lease") || lower.includes("rent") || lower.includes("tenan")) {
    return [
      "What is the lease term and monthly rent?",
      "What are the security deposit and refund conditions?",
      "What notice is required for lease termination?",
      "Who is responsible for maintenance and utilities?"
    ];
  }
  if (lower.includes("nda") || lower.includes("confidential")) {
    return [
      "What is defined as Confidential Information?",
      "What are the standard exclusions from confidentiality?",
      "What is the duration of the confidentiality obligation?",
      "What remedies are specified for breach of confidentiality?"
    ];
  }
  if (lower.includes("employ") || lower.includes("offer") || lower.includes("service")) {
    return [
      "What are the employee's main duties and compensation?",
      "What are the termination provisions and notice periods?",
      "Are there restrictive covenants or non-compete clauses?",
      "How are intellectual property rights assigned?"
    ];
  }
  if (lower.includes("vendor") || lower.includes("master") || lower.includes("sla") || lower.includes("agreement") || lower.includes("contract")) {
    return [
      "What are the key deliverables and payment milestones?",
      "What are the termination rights and cure periods?",
      "What are the limitation of liability and indemnification terms?",
      "Which governing law and dispute resolution mechanism apply?"
    ];
  }
  if (docName) {
    return [
      "What are the primary obligations in this document?",
      "What deadlines, milestones, or dates are specified?",
      "Which parties are named and what are their roles?",
      "What termination or liability provisions are stated?"
    ];
  }
  // No document selected - general legal inquiries
  return [
    "What are standard key clauses in an NDA?",
    "How does a mutual indemnity clause typically work?",
    "What constitutes a material breach in commercial contracts?",
    "What are typical remedies under a force majeure event?"
  ];
}

function renderEmptyState() {
  emptyState.hidden = false;
  chatMessages.replaceChildren(emptyState);

  if (activeDocumentId) {
    emptyHeading.textContent = "New Chat";
    emptySubheading.textContent = `Ask anything about ${activeDocumentName}.`;
    emptyDocCard.hidden = false;
    emptyDocTitle.textContent = activeDocumentName;
    emptyDocMeta.textContent = `${activeDocumentPages} page${activeDocumentPages === 1 ? "" : "s"}`;
  } else {
    emptyHeading.textContent = "New Chat";
    emptySubheading.textContent = "What would you like to ask? Select a document if you want to ask questions about a specific file.";
    emptyDocCard.hidden = true;
  }

  const suggestions = getDocumentSuggestions(activeDocumentName);
  suggestedQuestionsGrid.innerHTML = "";
  suggestions.forEach(q => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "suggested-question-btn";
    btn.textContent = q;
    btn.addEventListener("click", () => {
      questionInput.value = q;
      charCount.textContent = `${q.length}/1500`;
      chatForm.requestSubmit();
    });
    suggestedQuestionsGrid.appendChild(btn);
  });
}

function initNewChatState(doc = null) {
  activeConversationId = null;
  localStorage.removeItem("legal_qa_active_conv");
  chatHistory = [];
  closeSourceInspector();

  if (doc) {
    activeDocumentId = doc.document_id;
    activeDocumentName = doc.original_filename || doc.filename;
    activeDocumentPages = doc.page_count;
    activeDocumentChunks = doc.chunk_count;
  } else {
    activeDocumentId = null;
    activeDocumentName = "";
    activeDocumentPages = 0;
    activeDocumentChunks = 0;
  }

  updateContextDisplay();
  renderEmptyState();
  renderDropdownOptions();
  renderConversationsListHighlight();
  showChatWorkspace();
  questionInput.focus();
}

function handleStartNewChat() {
  initNewChatState(activeDocumentId ? {
    document_id: activeDocumentId,
    original_filename: activeDocumentName,
    page_count: activeDocumentPages,
    chunk_count: activeDocumentChunks
  } : null);
}

// ==========================================
// Chat Messaging & Submissions
// ==========================================
async function handleChatSubmit(e) {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  emptyState.hidden = true;
  appendUserMessage(question);
  questionInput.value = "";
  charCount.textContent = "0/1500";
  setChatLoading(true);

  try {
    const payload = {
      question: question,
      history: chatHistory
    };

    if (activeDocumentId) {
      payload.document_id = activeDocumentId;
    } else {
      payload.document_id = "none";
    }

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
      throw new Error(result.detail || "Error querying legal information.");
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
}

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

  // Answer status indicator
  const statusRow = document.createElement("div");
  statusRow.className = "status-row";
  const answerStatus = document.createElement("div");
  answerStatus.className = `answer-status ${getConfidenceClass(confidence)}`;
  answerStatus.textContent = getConfidenceLabel(confidence);
  statusRow.appendChild(answerStatus);
  content.appendChild(statusRow);

  const answer = document.createElement("p");
  answer.textContent = text;
  content.appendChild(answer);

  if (confidence === "insufficient_context") {
    const guidance = document.createElement("div");
    guidance.className = "refusal-guidance";
    guidance.textContent = "The answer is not stated in the selected document. Try asking about specific terms, parties, or clauses.";
    content.appendChild(guidance);
  }

  // Citations / Sources on demand
  if (sources && sources.length > 0) {
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
      toggleBtn.innerHTML = `<span>[View Source (${uniqueSources.length})]</span>`;

      const sourcesContainer = document.createElement("section");
      sourcesContainer.className = "sources-container";
      sourcesContainer.style.display = "none";

      const sourcesHeader = document.createElement("div");
      sourcesHeader.className = "sources-header";
      sourcesHeader.textContent = `Sources · ${uniqueSources.length} citation${uniqueSources.length === 1 ? "" : "s"}`;
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
        inspectLabel.textContent = "View excerpt →";

        citationButton.append(documentName, citationMeta, snippet, inspectLabel);
        sourcesContainer.appendChild(citationButton);
      });

      toggleBtn.addEventListener("click", () => {
        const isHidden = sourcesContainer.style.display === "none";
        sourcesContainer.style.display = isHidden ? "flex" : "none";
        toggleBtn.innerHTML = isHidden
          ? `<span>[Hide Source]</span>`
          : `<span>[View Source (${uniqueSources.length})]</span>`;
      });

      content.appendChild(toggleBtn);
      content.appendChild(sourcesContainer);
    }
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
    supported: "Answer",
    partially_supported: "Partially supported",
    insufficient_context: "Not stated in document",
    not_found: "Not found",
    low_confidence: "Low confidence",
    clarification_required: "Clarification required",
    conflicting_evidence: "Conflicting information",
    error: "Error"
  };
  return labels[confidence] || "Answer";
}

function setChatLoading(isLoading) {
  sendBtn.disabled = isLoading;
  questionInput.disabled = isLoading;
  if (isLoading) {
    sendBtn.classList.add("loading");
    sendBtn.setAttribute("aria-label", "Preparing answer...");
    sendBtn.innerHTML = `
      <span class="btn-dots-loader" aria-hidden="true">
        <span class="btn-dot"></span>
        <span class="btn-dot"></span>
        <span class="btn-dot"></span>
      </span>
      <span class="sr-only">Preparing answer...</span>
    `;
  } else {
    sendBtn.classList.remove("loading");
    sendBtn.setAttribute("aria-label", "Send question");
    sendBtn.innerHTML = "<span>Ask</span>";
    questionInput.focus();
  }
}

// ==========================================
// Source Inspector Drawer
// ==========================================
function openSourceInspector(citation) {
  sourceDocumentName.textContent = citation.document_name || "Source document";
  sourceLocation.textContent = `Page ${citation.page_number} · Section ${citation.section || "General"}`;
  sourceExcerpt.textContent = citation.snippet || "No source excerpt was returned for this citation.";
  sourceInspector.hidden = false;
  sourceInspector.setAttribute("aria-hidden", "false");
  mainLayout.classList.add("inspector-open");
  if (sourceInspectorClose) sourceInspectorClose.focus();
}

function closeSourceInspector() {
  sourceInspector.hidden = true;
  sourceInspector.setAttribute("aria-hidden", "true");
  mainLayout.classList.remove("inspector-open");
}

// ==========================================
// Conversations Management
// ==========================================
async function fetchConversations() {
  if (!conversationsList) return;
  try {
    const res = await fetch("/api/conversations?limit=50");
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
    conversationsList.innerHTML = "<p class='empty-text'>No chats yet.</p>";
    return;
  }

  conversationsList.innerHTML = "";
  convs.forEach(conv => {
    const item = document.createElement("div");
    item.className = `conv-item ${conv.conversation_id === activeConversationId ? "active" : ""}`;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "conv-item-btn";

    const titleSpan = document.createElement("span");
    titleSpan.className = "conv-item-title";
    titleSpan.textContent = conv.title || "Chat";

    btn.appendChild(titleSpan);
    btn.addEventListener("click", () => switchConversation(conv.conversation_id));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "del-btn";
    delBtn.title = "Delete chat";
    delBtn.setAttribute("aria-label", `Delete chat ${conv.title || "Chat"}`);
    delBtn.textContent = "×";
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openDeleteConversationDialog(conv.conversation_id, conv.document_ids?.[0] || activeDocumentId || "", conv.title || "this chat");
    });

    item.append(btn, delBtn);
    conversationsList.appendChild(item);
  });
}

function renderConversationsListHighlight() {
  if (!conversationsList) return;
  const items = conversationsList.querySelectorAll(".conv-item");
  items.forEach(it => it.classList.remove("active"));
  // Re-highlight if matches activeConversationId
}

async function switchConversation(conversationId) {
  if (!conversationId) return;
  activeConversationId = conversationId;
  localStorage.setItem("legal_qa_active_conv", conversationId);
  await loadSavedConversation(conversationId);
  fetchConversations();
  closeSidebar();
  showChatWorkspace();
}

async function loadSavedConversation(conversationId) {
  try {
    const res = await fetch(`/api/conversations/${conversationId}`);
    if (!res.ok) {
      if (res.status === 404) {
        localStorage.removeItem("legal_qa_active_conv");
        activeConversationId = null;
      }
      return;
    }
    const result = await res.json();
    const conv = result.data;
    if (!conv) return;

    // Synchronize document context from conversation if attached
    if (conv.document_ids && conv.document_ids.length > 0) {
      const primaryDocId = conv.document_ids[0];
      const foundDoc = allDocuments.find(d => d.document_id === primaryDocId);
      if (foundDoc) {
        activeDocumentId = foundDoc.document_id;
        activeDocumentName = foundDoc.original_filename || foundDoc.filename;
        activeDocumentPages = foundDoc.page_count;
        activeDocumentChunks = foundDoc.chunk_count;
      }
    } else {
      activeDocumentId = null;
      activeDocumentName = "";
      activeDocumentPages = 0;
      activeDocumentChunks = 0;
    }
    updateContextDisplay();
    renderDropdownOptions();

    if (!conv.messages || conv.messages.length === 0) {
      renderEmptyState();
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
          msg.evidence_state || "supported"
        );
        chatHistory.push({ role: "assistant", content: msg.content });
      }
    }
  } catch (err) {
    console.error("Failed to restore saved conversation:", err);
  }
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
        initNewChatState(null);
      }
      fetchConversations();
    }
  } catch (err) {
    console.error("Failed to delete conversation:", err);
  }
}

// ==========================================
// Documents Management & Screen
// ==========================================
async function fetchDocuments() {
  try {
    const res = await fetch("/api/documents");
    if (!res.ok) return;
    const result = await res.json();
    allDocuments = result.data || [];
    if (topNavDocCount) topNavDocCount.textContent = String(allDocuments.length);
    renderDropdownOptions();
    renderDocumentsGrid(allDocuments);
  } catch (err) {
    console.error("Error fetching documents:", err);
  }
}

function renderDocumentsGrid(docs, filterQuery = "") {
  if (!documentsGrid) return;
  const query = (filterQuery || "").trim().toLowerCase();
  const filtered = query
    ? docs.filter(d => (d.original_filename || d.filename || "").toLowerCase().includes(query))
    : docs;

  if (filtered.length === 0) {
    documentsGrid.innerHTML = `
      <div class="empty-docs-placeholder">
        <span class="placeholder-icon">📄</span>
        <h3>${query ? "No matching documents found" : "No documents uploaded yet"}</h3>
        <p>${query ? "Try a different search term" : "Upload contracts, agreements, or briefs to start asking questions."}</p>
        <button type="button" class="primary-btn" onclick="uploadDialog.showModal()">+ Upload Document</button>
      </div>
    `;
    return;
  }

  documentsGrid.innerHTML = "";
  filtered.forEach(doc => {
    const card = document.createElement("div");
    card.className = `doc-card ${doc.document_id === activeDocumentId ? "active" : ""}`;
    const name = doc.original_filename || doc.filename;

    card.innerHTML = `
      <div class="doc-card-header">
        <span class="file-glyph">📄</span>
        <div class="doc-card-info">
          <h3 class="doc-name" title="${escapeHtml(name)}">${escapeHtml(name)}</h3>
          <span class="doc-meta">${doc.page_count} page${doc.page_count === 1 ? "" : "s"}</span>
        </div>
      </div>
      <div class="doc-card-actions">
        <button type="button" class="primary-btn open-chat-action">Open Chat</button>
        <button type="button" class="secondary-btn view-doc-action">View</button>
        <button type="button" class="del-btn-card" title="Delete document" aria-label="Delete ${escapeHtml(name)}">×</button>
      </div>
    `;

    card.querySelector(".open-chat-action").addEventListener("click", () => {
      executeSetDocumentContext(doc.document_id, name, doc.page_count, doc.chunk_count, true);
      showChatWorkspace();
    });

    card.querySelector(".view-doc-action").addEventListener("click", () => {
      openDocumentViewer(doc.document_id, name);
    });

    card.querySelector(".del-btn-card").addEventListener("click", (e) => {
      deleteDocument(e, doc.document_id, name);
    });

    documentsGrid.appendChild(card);
  });
}

function openDocumentViewer(documentId, name) {
  if (!documentId) return;
  const docTitle = name || activeDocumentName || "Document Preview";
  if (pdfModalTitle) pdfModalTitle.textContent = docTitle;
  if (pdfFrame) pdfFrame.src = `/api/documents/${documentId}/file`;
  if (pdfModal) pdfModal.showModal();
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
        initNewChatState(null);
      }
      showStatus("Document deleted successfully", "success", true);
      await fetchDocuments();
    }
  } catch (err) {
    showStatus("Failed to delete document: " + err.message, "error", true);
  }
}

// ==========================================
// Document Upload & Toast Notification
// ==========================================
async function handleFileUpload(file) {
  const allowed = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff"];
  const lowerName = file.name.toLowerCase();
  const isAllowed = allowed.some(ext => lowerName.endsWith(ext));
  if (!isAllowed) {
    showStatus("Only PDF and image files (.png, .jpg, .jpeg, .webp, .tiff) are supported.", "error", true);
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  showStatus(`Processing "${file.name}"...`, "loading");

  try {
    const res = await fetch("/api/documents/upload", {
      method: "POST",
      body: formData
    });

    const result = await res.json();
    if (!res.ok) {
      throw new Error(result.detail || "Failed to process document.");
    }

    showStatus(`Successfully uploaded "${result.data.original_filename}"`, "success", true);
    await fetchDocuments();

    // Set document context and start new chat
    executeSetDocumentContext(
      result.data.document_id,
      result.data.original_filename,
      result.data.page_count,
      result.data.chunk_count,
      true
    );
    showChatWorkspace();
  } catch (err) {
    showStatus(err.message, "error", true);
  }
}

let uploadStatusTimer = null;
function showStatus(msg, type, autoDismiss = false) {
  if (uploadStatusTimer) {
    clearTimeout(uploadStatusTimer);
    uploadStatusTimer = null;
  }
  uploadStatus.textContent = msg;
  uploadStatus.className = `status-box toast ${type}`;
  uploadStatus.classList.remove("hidden");

  if (autoDismiss) {
    uploadStatusTimer = setTimeout(() => {
      uploadStatus.classList.add("hidden");
    }, 4000);
  }
}

// ==========================================
// Utilities
// ==========================================
function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/[&<>"']/g, (m) => {
    switch (m) {
      case "&": return "&amp;";
      case "<": return "&lt;";
      case ">": return "&gt;";
      case '"': return "&quot;";
      case "'": return "&#39;";
      default: return m;
    }
  });
}
