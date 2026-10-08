import React, { useState, useMemo } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  FileText,
  MessageSquare,
  Search,
  Upload,
  Trash2,
  Eye,
  CheckCircle2,
  Clock,
  Sparkles,
  Send,
  HelpCircle,
  Shield,
  Layers,
  ChevronDown,
  Info,
  Scale
} from 'lucide-react';

export interface DocumentItem {
  id: string;
  name: string;
  pages: number;
  chunks: number;
  type: 'pdf' | 'image';
  uploadedAt: string;
}

export interface ConversationItem {
  id: string;
  title: string;
  documentId: string;
  messageCount: number;
  updatedAt: string;
}

export interface LegalDashboardProps {
  documents?: DocumentItem[];
  conversations?: ConversationItem[];
  onSelectDocument?: (doc: DocumentItem) => void;
  onSelectConversation?: (conv: ConversationItem) => void;
  onUploadDocument?: () => void;
  onViewDocument?: (doc: DocumentItem) => void;
  onDeleteDocument?: (doc: DocumentItem) => void;
  onDeleteConversation?: (conv: ConversationItem) => void;
  onSubmitPrompt?: (prompt: string) => void;
}

export const LegalDashboard: React.FC<LegalDashboardProps> = ({
  documents = [
    {
      id: 'doc_1',
      name: 'Master_Services_Agreement_2026.pdf',
      pages: 14,
      chunks: 42,
      type: 'pdf',
      uploadedAt: '2026-10-08T10:30:00Z'
    },
    {
      id: 'doc_2',
      name: 'Commercial_Lease_Addendum_Final.pdf',
      pages: 6,
      chunks: 18,
      type: 'pdf',
      uploadedAt: '2026-10-07T14:15:00Z'
    },
    {
      id: 'doc_3',
      name: 'Non_Disclosure_Agreement_Mutual.pdf',
      pages: 3,
      chunks: 9,
      type: 'pdf',
      uploadedAt: '2026-10-06T09:20:00Z'
    }
  ],
  conversations = [
    {
      id: 'conv_1',
      title: 'Services Agreement QA',
      documentId: 'doc_1',
      messageCount: 8,
      updatedAt: '2026-10-08T11:45:00Z'
    },
    {
      id: 'conv_2',
      title: 'Lease Holdover Clause Inquiries',
      documentId: 'doc_2',
      messageCount: 4,
      updatedAt: '2026-10-07T16:20:00Z'
    }
  ],
  onSelectDocument,
  onSelectConversation,
  onUploadDocument,
  onViewDocument,
  onDeleteDocument,
  onDeleteConversation,
  onSubmitPrompt
}) => {
  // Layout & Navigation State
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [activeTab, setActiveTab] = useState<'qa' | 'corpus'>('qa');
  const [docsOpen, setDocsOpen] = useState(true);
  const [convsOpen, setConvsOpen] = useState(true);

  // Document & Context State
  const [selectedDocId, setSelectedDocId] = useState<string | null>('doc_1');
  const [selectedConvId, setSelectedConvId] = useState<string | null>('conv_1');
  const [promptText, setPromptText] = useState('');

  const activeDocument = useMemo(
    () => documents.find((d) => d.id === selectedDocId) || null,
    [documents, selectedDocId]
  );

  const starterQuestions = [
    {
      id: 'q1',
      question: 'What obligations does this document describe?',
      kicker: 'CORE OBLIGATIONS',
      icon: Shield
    },
    {
      id: 'q2',
      question: 'What dates, notice periods, or deadlines are stated?',
      kicker: 'TIMELINES & NOTICE',
      icon: Clock
    },
    {
      id: 'q3',
      question: 'Which indemnities and liabilities are capped or excluded?',
      kicker: 'LIABILITY & RISK',
      icon: Scale
    },
    {
      id: 'q4',
      question: 'What happens if a party defaults or fails to perform?',
      kicker: 'TERMINATION & BREACH',
      icon: Layers
    }
  ];

  const handleDocumentClick = (doc: DocumentItem) => {
    setSelectedDocId(doc.id);
    onSelectDocument?.(doc);
  };

  const handleSendPrompt = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!promptText.trim() || !activeDocument) return;
    onSubmitPrompt?.(promptText);
    setPromptText('');
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50 font-sans text-slate-800 antialiased selection:bg-indigo-100 selection:text-indigo-800">
      {/* =========================================================================
          1. TOP APPLICATION HEADER
         ========================================================================= */}
      <header className="fixed top-0 left-0 right-0 z-30 flex h-16 items-center justify-between border-b border-slate-200 bg-white/95 px-5 backdrop-blur-md">
        <div className="flex items-center gap-3">
          {/* Sidebar Toggle Button */}
          <button
            type="button"
            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            title={isSidebarCollapsed ? 'Expand sidebar (280px)' : 'Collapse sidebar (64px)'}
            aria-label="Toggle Navigation Sidebar"
          >
            {isSidebarCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </button>

          {/* Brand Logo & Name */}
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-sm shadow-indigo-600/20">
              <span className="font-serif text-lg font-bold">§</span>
            </div>
            <div className="hidden sm:block">
              <span className="text-xs font-semibold tracking-wider text-slate-400">ENTERPRISE INTELLIGENCE</span>
              <h1 className="text-sm font-bold tracking-tight text-slate-900">Legal Document QA</h1>
            </div>
          </div>
        </div>

        {/* Center: Segmented Navigation Control */}
        <div className="inline-flex items-center rounded-lg border border-slate-200 bg-slate-100/80 p-1">
          <button
            type="button"
            onClick={() => setActiveTab('qa')}
            className={`flex items-center gap-2 rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all ${
              activeTab === 'qa'
                ? 'bg-white text-indigo-700 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span>QA Chat</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('corpus')}
            className={`flex items-center gap-2 rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all ${
              activeTab === 'corpus'
                ? 'bg-white text-indigo-700 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <Layers className="h-3.5 w-3.5" />
            <span>Evidence Corpus</span>
          </button>
        </div>

        {/* Right: Active Document Status Pill Badge */}
        <div className="flex items-center">
          <div
            className={`flex items-center gap-2.5 rounded-full border px-3.5 py-1.5 transition-colors ${
              activeDocument
                ? 'border-emerald-200 bg-emerald-50/70 text-emerald-800'
                : 'border-slate-200 bg-slate-100 text-slate-500'
            }`}
            title={activeDocument ? `Active Document: ${activeDocument.name}` : 'No active document'}
          >
            <span
              className={`h-2 w-2 rounded-full ${
                activeDocument ? 'animate-pulse bg-emerald-500 ring-4 ring-emerald-500/20' : 'bg-slate-400'
              }`}
            />
            <span className="text-[11px] font-bold tracking-wider uppercase text-slate-500">
              {activeDocument ? 'ACTIVE MATTER' : 'NO CONTEXT'}
            </span>
            <span className="max-w-[140px] truncate text-xs font-semibold text-slate-900 sm:max-w-[220px]">
              {activeDocument ? activeDocument.name : 'No document selected'}
            </span>
          </div>
        </div>
      </header>

      {/* =========================================================================
          2. BODY LAYOUT: COLLAPSIBLE SIDEBAR + MAIN WORKSPACE CANVAS
         ========================================================================= */}
      <div className="flex h-full w-full pt-16">
        {/* =========================================================================
            LEFT NAVIGATION PANEL (Collapsible: 280px <-> 64px)
           ========================================================================= */}
        <aside
          className={`relative z-20 flex flex-col border-r border-slate-200 bg-white transition-all duration-300 ease-in-out ${
            isSidebarCollapsed ? 'w-16 items-center' : 'w-70 min-w-[280px] max-w-[280px]'
          }`}
        >
          {/* Upload Button */}
          <div className="p-3 border-b border-slate-100 w-full">
            <button
              type="button"
              onClick={onUploadDocument}
              className={`flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 font-semibold text-white shadow-sm shadow-indigo-600/20 transition-all hover:bg-indigo-700 active:scale-[0.98] ${
                isSidebarCollapsed ? 'h-10 px-0' : 'h-10 px-3.5 text-xs'
              }`}
              title="Upload PDF or Image Document"
            >
              <Upload className="h-4 w-4 shrink-0" />
              {!isSidebarCollapsed && <span>Upload Document</span>}
            </button>
          </div>

          {/* Navigation Accordion Sections */}
          <div className="flex-1 overflow-y-auto px-2 py-3 space-y-4 w-full">
            {/* Section 1: Indexed Documents */}
            <div>
              {!isSidebarCollapsed ? (
                <button
                  type="button"
                  onClick={() => setDocsOpen(!docsOpen)}
                  className="flex w-full items-center justify-between px-2 py-1.5 text-slate-400 hover:text-slate-700"
                >
                  <span className="text-[10px] font-bold tracking-wider uppercase">
                    INDEXED DOCUMENTS ({documents.length})
                  </span>
                  <ChevronDown
                    className={`h-3.5 w-3.5 transition-transform duration-200 ${
                      docsOpen ? 'rotate-0' : '-rotate-90'
                    }`}
                  />
                </button>
              ) : (
                <div className="my-1 flex justify-center text-slate-400" title="Indexed Documents">
                  <FileText className="h-4 w-4" />
                </div>
              )}

              {(docsOpen || isSidebarCollapsed) && (
                <div className="mt-1 space-y-1">
                  {documents.map((doc) => {
                    const isSelected = doc.id === selectedDocId;
                    return (
                      <div
                        key={doc.id}
                        onClick={() => handleDocumentClick(doc)}
                        className={`group relative flex cursor-pointer items-center justify-between rounded-lg px-2.5 py-2 text-xs transition-all ${
                          isSelected
                            ? 'bg-indigo-50/80 text-indigo-900 font-medium'
                            : 'text-slate-700 hover:bg-slate-100 hover:text-slate-900'
                        }`}
                        title={doc.name}
                      >
                        {/* File icon & filename */}
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          <FileText
                            className={`h-4 w-4 shrink-0 transition-colors ${
                              isSelected ? 'text-indigo-600' : 'text-slate-400 group-hover:text-slate-600'
                            }`}
                          />
                          {!isSidebarCollapsed && (
                            <div className="min-w-0 flex-1">
                              <p className="truncate leading-tight text-xs">{doc.name}</p>
                              <p className="text-[10px] text-slate-400 mt-0.5">
                                {doc.pages} pages · {doc.chunks} chunks
                              </p>
                            </div>
                          )}
                        </div>

                        {/* Subtle action buttons visible on hover */}
                        {!isSidebarCollapsed && (
                          <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onViewDocument?.(doc);
                              }}
                              className="rounded p-1 text-slate-400 hover:bg-white hover:text-indigo-600 hover:shadow-xs"
                              title="Inspect Document"
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onDeleteDocument?.(doc);
                              }}
                              className="rounded p-1 text-slate-400 hover:bg-white hover:text-rose-600 hover:shadow-xs"
                              title="Delete Document"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Section 2: Recent Conversations */}
            <div className="pt-2 border-t border-slate-100">
              {!isSidebarCollapsed ? (
                <button
                  type="button"
                  onClick={() => setConvsOpen(!convsOpen)}
                  className="flex w-full items-center justify-between px-2 py-1.5 text-slate-400 hover:text-slate-700"
                >
                  <span className="text-[10px] font-bold tracking-wider uppercase">
                    RECENT THREADS ({conversations.length})
                  </span>
                  <ChevronDown
                    className={`h-3.5 w-3.5 transition-transform duration-200 ${
                      convsOpen ? 'rotate-0' : '-rotate-90'
                    }`}
                  />
                </button>
              ) : (
                <div className="my-1 flex justify-center text-slate-400" title="Recent Conversations">
                  <MessageSquare className="h-4 w-4" />
                </div>
              )}

              {(convsOpen || isSidebarCollapsed) && (
                <div className="mt-1 space-y-1">
                  {conversations.map((conv) => {
                    const isSelected = conv.id === selectedConvId;
                    return (
                      <div
                        key={conv.id}
                        onClick={() => {
                          setSelectedConvId(conv.id);
                          onSelectConversation?.(conv);
                        }}
                        className={`group relative flex cursor-pointer items-center justify-between rounded-lg px-2.5 py-2 text-xs transition-all ${
                          isSelected
                            ? 'bg-slate-100 text-slate-900 font-medium'
                            : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                        }`}
                        title={conv.title}
                      >
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          <MessageSquare
                            className={`h-4 w-4 shrink-0 ${
                              isSelected ? 'text-indigo-600' : 'text-slate-400'
                            }`}
                          />
                          {!isSidebarCollapsed && (
                            <div className="min-w-0 flex-1">
                              <p className="truncate leading-tight text-xs">{conv.title}</p>
                              <p className="text-[10px] text-slate-400 mt-0.5">
                                {conv.messageCount} messages
                              </p>
                            </div>
                          )}
                        </div>

                        {!isSidebarCollapsed && (
                          <div className="flex items-center opacity-0 group-hover:opacity-100">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onDeleteConversation?.(conv);
                              }}
                              className="rounded p-1 text-slate-400 hover:text-rose-600"
                              title="Delete Thread"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* Sidebar Footer */}
          {!isSidebarCollapsed && (
            <div className="border-t border-slate-100 p-3 text-[11px] text-slate-400 flex items-center justify-between">
              <span>Isolated Local Store</span>
              <span className="flex items-center gap-1 font-mono text-[10px] text-emerald-600">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Grounded
              </span>
            </div>
          )}
        </aside>

        {/* =========================================================================
            MAIN CENTRAL WORKSPACE CANVAS
           ========================================================================= */}
        <main className="relative flex flex-1 flex-col overflow-y-auto bg-slate-50">
          {/* Scrollable Container with Generous Padding (p-8 / 32px) */}
          <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col p-8 pb-36">
            {/* Header Intro Bar */}
            <div className="mb-6 flex flex-col gap-1">
              <span className="text-[11px] font-bold tracking-wider uppercase text-indigo-600">
                Grounded Legal Retrieval
              </span>
              <h2 className="text-xl font-bold tracking-tight text-slate-900">
                {activeDocument ? activeDocument.name : 'Document Inquiry Workspace'}
              </h2>
              <p className="text-xs text-slate-500">
                Responses are strictly grounded in retrieved passages with validated citations and page anchors.
              </p>
            </div>

            {/* Container 1: Document Readiness Card */}
            <div className="mb-6 rounded-xl border border-slate-200 bg-white p-5 shadow-xs transition-shadow hover:shadow-sm">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3.5">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
                    <CheckCircle2 className="h-4 w-4" />
                  </div>
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800">
                      Document Readiness & Calibration
                    </h3>
                    <p className="text-[11px] text-slate-400">
                      Authoritative structural indexing and vector embeddings
                    </p>
                  </div>
                </div>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Calibrated
                </span>
              </div>

              {/* Metrics Grid */}
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="rounded-lg bg-slate-50/80 p-3.5 border border-slate-100">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    PDF Document Pages
                  </span>
                  <p className="mt-1 text-lg font-bold text-slate-900">
                    {activeDocument ? activeDocument.pages : '—'}
                  </p>
                </div>
                <div className="rounded-lg bg-slate-50/80 p-3.5 border border-slate-100">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Indexed Vector Chunks
                  </span>
                  <p className="mt-1 text-lg font-bold text-slate-900">
                    {activeDocument ? activeDocument.chunks : '—'}
                  </p>
                </div>
                <div className="rounded-lg bg-slate-50/80 p-3.5 border border-slate-100">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Retrieval Isolation
                  </span>
                  <p className="mt-1 text-xs font-semibold text-emerald-600 flex items-center gap-1">
                    <Shield className="h-3.5 w-3.5" /> Scoped to Single Document
                  </p>
                </div>
              </div>
            </div>

            {/* Container 2: Inquiry Starters (2x2 Grid Cards) */}
            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800">
                    Inquiry Starters
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Select a prompt starter to initiate targeted clause extraction
                  </p>
                </div>
                <Sparkles className="h-4 w-4 text-indigo-500" />
              </div>

              {/* 2x2 Interactive Grid Cards */}
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                {starterQuestions.map((q) => {
                  const Icon = q.icon;
                  return (
                    <button
                      key={q.id}
                      type="button"
                      onClick={() => setPromptText(q.question)}
                      className="group flex flex-col items-start rounded-lg border border-slate-200 bg-slate-50/60 p-4 text-left transition-all hover:border-indigo-500 hover:bg-indigo-50/30 hover:shadow-sm"
                    >
                      <div className="flex w-full items-center justify-between">
                        <span className="text-[10px] font-bold tracking-wider uppercase text-indigo-600">
                          {q.kicker}
                        </span>
                        <Icon className="h-3.5 w-3.5 text-slate-400 transition-colors group-hover:text-indigo-600" />
                      </div>
                      <p className="mt-2 text-xs font-medium text-slate-800 group-hover:text-indigo-900">
                        "{q.question}"
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Legal Safety Notice */}
            <div className="mt-6 flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50/60 p-3.5 text-xs text-amber-800">
              <Info className="h-4 w-4 shrink-0 text-amber-600 mt-0.5" />
              <p className="leading-relaxed text-[11px]">
                <strong>Legal Disclaimer:</strong> This tool extracts and synthesizes factual evidence strictly from the selected uploaded contract. It does not provide formal legal counsel or substitute attorney review.
              </p>
            </div>
          </div>

          {/* =========================================================================
              4. FLOATING STICKY PROMPT INPUT BAR
             ========================================================================= */}
          <div className="pointer-events-none fixed bottom-6 left-0 right-0 z-20 flex justify-center px-6">
            <div
              className={`pointer-events-auto w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-3 shadow-lg shadow-slate-200/50 backdrop-blur-md transition-all ${
                isSidebarCollapsed ? 'sm:ml-16' : 'sm:ml-70'
              }`}
            >
              <form onSubmit={handleSendPrompt} className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <Search className="h-4 w-4 shrink-0 text-slate-400 ml-1.5" />
                  <input
                    type="text"
                    value={promptText}
                    onChange={(e) => setPromptText(e.target.value)}
                    disabled={!activeDocument}
                    placeholder={
                      activeDocument
                        ? `Ask a question about ${activeDocument.name}...`
                        : 'Select a document from the left panel to begin...'
                    }
                    className="flex-1 bg-transparent text-xs text-slate-900 placeholder:text-slate-400 focus:outline-none disabled:cursor-not-allowed"
                  />
                  <button
                    type="submit"
                    disabled={!activeDocument || !promptText.trim()}
                    className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white transition-all hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400"
                    title="Send inquiry"
                  >
                    <Send className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="flex items-center justify-between border-t border-slate-100 pt-2 text-[10px] text-slate-400 px-1.5">
                  <span className="flex items-center gap-1">
                    <span className="font-semibold text-slate-600">Context:</span>{' '}
                    {activeDocument ? activeDocument.name : 'None'}
                  </span>
                  <span>Press Enter to inquire</span>
                </div>
              </form>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};

export default LegalDashboard;

