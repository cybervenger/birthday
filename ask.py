#!/usr/bin/env python3
"""Semantic search / RAG CLI over a company's scraped knowledge base.

Usage:
    python ask.py --company Galderma
    python ask.py --company Galderma "What is Galderma's newest injectable?"
"""
from __future__ import annotations

import argparse
import sys

from embeddings.rag import LocalRAG


def _print_answer(rag: LocalRAG, question: str) -> None:
    result = rag.ask(question)
    print("\n" + result.answer)
    if result.citations:
        print("\nSources:")
        for c in result.citations:
            print(f"  - {c}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask questions against a company's trivia knowledge base.")
    parser.add_argument("--company", required=True, help="Company name, e.g. 'Galderma'.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of facts to retrieve.")
    parser.add_argument("--llm", action="store_true", help="Use LLM synthesis if ANTHROPIC_API_KEY is set.")
    parser.add_argument("question", nargs="*", help="Question text. Omit to enter interactive mode.")
    args = parser.parse_args()

    rag = LocalRAG(args.company, top_k=args.top_k, use_llm=args.llm)

    if args.question:
        _print_answer(rag, " ".join(args.question))
        return

    print(f"Ask Anything about {args.company} (Ctrl+C or 'exit' to quit)\n")
    try:
        while True:
            question = input("Question: ").strip()
            if question.lower() in ("exit", "quit", ""):
                if question == "":
                    continue
                break
            _print_answer(rag, question)
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye.")
        sys.exit(0)


if __name__ == "__main__":
    main()
