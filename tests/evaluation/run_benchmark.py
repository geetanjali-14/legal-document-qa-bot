"""
Standalone Benchmark Runner Script for Legal RAG Evaluation Suite (OPT-018).

Usage:
  PYTHONPATH=. ./venv/bin/python tests/evaluation/run_benchmark.py [--output-json /path/to/report.json]

Executes all canonical benchmark test cases against the live application using
an isolated temporary vector/upload store, produces a detailed terminal summary,
and optionally saves a machine-readable JSON evaluation report.
"""

import sys
import argparse
import json
from pathlib import Path
import tempfile
from fastapi.testclient import TestClient

from app.main import app, app_state
from app.services.vector_store import VectorStore
from app.services.document_service import DocumentService
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import LLMService
from app.services.citation_service import CitationService
from tests.evaluation.benchmark_dataset import BENCHMARK_CASES
from tests.evaluation.eval_harness import (
    evaluate_case,
    compute_benchmark_summary,
    format_benchmark_report_text
)


def run_evaluation(pdf_path: Path = Path("documents/synthetic_contract.pdf")):
    if not pdf_path.exists():
        raise FileNotFoundError(f"Evaluation PDF not found at {pdf_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        upload_dir = tmp_path / "uploads"
        vector_dir = tmp_path / "vector_store"
        upload_dir.mkdir()
        vector_dir.mkdir()

        with TestClient(app) as client:
            # Configure clean isolated test services
            vs = VectorStore(storage_dir=vector_dir)
            emb = EmbeddingService()
            pdf_s = PDFService()
            chunk_s = ChunkingService()
            doc_s = DocumentService(pdf_s, chunk_s, emb, vs)
            doc_s.upload_dir = upload_dir
            doc_s.metadata_file = upload_dir / "documents_meta.json"
            doc_s.documents = {}
            doc_s._hash_to_id = {}
            ret_s = RetrievalService(emb, vs)
            llm_s = LLMService()
            cite_s = CitationService()

            app_state["vector_store"] = vs
            app_state["embedding_service"] = emb
            app_state["pdf_service"] = pdf_s
            app_state["chunking_service"] = chunk_s
            app_state["document_service"] = doc_s
            app_state["retrieval_service"] = ret_s
            app_state["llm_service"] = llm_s
            app_state["citation_service"] = cite_s

            with open(pdf_path, "rb") as f:
                upload_res = client.post(
                    "/api/documents/upload",
                    files={"file": (pdf_path.name, f, "application/pdf")}
                )
            if upload_res.status_code != 201:
                raise RuntimeError(f"Failed to ingest test document: {upload_res.text}")

            doc_id = upload_res.json()["data"]["document_id"]

            case_results = []
            for case in BENCHMARK_CASES:
                chat_res = client.post(
                    "/api/chat",
                    json={"document_id": doc_id, "question": case.question}
                )
                if chat_res.status_code != 200:
                    raise RuntimeError(f"Chat request failed for case {case.case_id}: {chat_res.text}")

                eval_result = evaluate_case(case, chat_res.json()["data"])
                case_results.append(eval_result)

            summary = compute_benchmark_summary(case_results)
            return summary


def main():
    parser = argparse.ArgumentParser(description="Legal RAG Evaluation Benchmark Suite (OPT-018)")
    parser.add_argument("--output-json", type=str, default="", help="Path to write JSON benchmark report")
    parser.add_argument("--quiet", action="store_true", help="Suppress human-readable summary")
    args = parser.parse_args()

    summary = run_evaluation()

    if not args.quiet:
        print(format_benchmark_report_text(summary))

    if args.output_json:
        out_p = Path(args.output_json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(summary.model_dump(mode="json"), f, indent=2)
        print(f"\nSaved structured benchmark report to: {out_p.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

