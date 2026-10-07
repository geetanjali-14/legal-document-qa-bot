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

// Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  fetchDocuments();
});

fileInput.addEventListener("change", (e) => {
  if (e.target.files.length > 0) {
    handleFileUpload(e.target.files[0]);
  }
});

refreshDocsBtn.addEventListener("click", () => {
  fetchDocuments();
});

questionInput.addEventListener("input", (e) => {
  charCount.textContent = `${e.target.value.length}/1500`;
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question || !activeDocumentId) return;

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

    const { answer, sources, confidence, disclaimer } = result.data;
    appendAssistantMessage(answer, sources, confidence, disclaimer);
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
  if (docs.length === 0) {
    documentsList.innerHTML = `<p class="empty-text">No documents uploaded yet.</p>`;
    return;
  }

  documentsList.innerHTML = docs.map(doc => `
    <div class="doc-item ${doc.document_id === activeDocumentId ? 'active' : ''}" 
         onclick="selectDocument('${doc.document_id}', '${doc.original_filename}', ${doc.page_count}, ${doc.chunk_count})">
      <div>
        <div class="doc-item-title">${doc.original_filename}</div>
        <div class="doc-item-meta">${doc.page_count} pages • ${doc.chunk_count} chunks</div>
      </div>
      <button class="del-btn" onclick="deleteDocument(event, '${doc.document_id}')" title="Delete">🗑️</button>
    </div>
  `).join("");
}

function selectDocument(id, name, pages, chunks) {
  activeDocumentId = id;
  activeDocName.textContent = name;
  activeDocStats.textContent = `${pages} Pages | ${chunks} Chunks`;
  questionInput.disabled = false;
  sendBtn.disabled = false;
  questionInput.placeholder = "Ask a question about this legal document...";
  questionInput.focus();

  // Highlight active
  document.querySelectorAll(".doc-item").forEach(item => item.classList.remove("active"));
  fetchDocuments();
}

async function deleteDocument(event, id) {
  event.stopPropagation();
  if (!confirm("Are you sure you want to delete this document and its indexed vectors?")) return;

  try {
    const res = await fetch(`/api/documents/${id}`, { method: "DELETE" });
    if (res.ok) {
      if (activeDocumentId === id) {
        activeDocumentId = null;
        activeDocName.textContent = "None selected";
        activeDocStats.textContent = "";
        questionInput.disabled = true;
        sendBtn.disabled = true;
        questionInput.placeholder = "Select a document first to ask questions...";
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
  msgEl.innerHTML = `<div class="message-content">${escapeHtml(text)}</div>`;
  chatMessages.appendChild(msgEl);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendAssistantMessage(text, sources = [], confidence = "supported", disclaimer = "") {
  const msgEl = document.createElement("div");
  msgEl.className = "message assistant";

  let sourcesHtml = "";
  if (sources && sources.length > 0) {
    sourcesHtml = `
      <div class="sources-container">
        <div class="sources-header">📄 Document Citations (${sources.length})</div>
        ${sources.map(s => `
          <div class="citation-card">
            <div class="citation-meta">Page ${s.page_number} • Section: ${escapeHtml(s.section)} [Doc: ${escapeHtml(s.document_name)}]</div>
            <div class="citation-snippet">"${escapeHtml(s.snippet)}"</div>
          </div>
        `).join("")}
      </div>
    `;
  }

  msgEl.innerHTML = `
    <div class="message-content">
      <p>${escapeHtml(text)}</p>
      ${sourcesHtml}
    </div>
  `;
  chatMessages.appendChild(msgEl);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function setChatLoading(isLoading) {
  sendBtn.disabled = isLoading;
  questionInput.disabled = isLoading;
  if (isLoading) {
    sendBtn.innerHTML = "<span>...</span>";
  } else {
    sendBtn.innerHTML = "<span>Ask</span> ➔";
    questionInput.focus();
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
