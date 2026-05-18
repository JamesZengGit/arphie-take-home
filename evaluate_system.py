#!/usr/bin/env python3
"""
RAGAs Evaluation Pipeline
Uses the ragas-wikiqa benchmark dataset (HuggingFace) to evaluate
RAG system reliability with industry-standard metrics.

Usage: python evaluate_system.py [--n 50] [--save]
"""

import os
import sys
import asyncio
import argparse
import json
from datetime import datetime

from datasets import load_dataset
from ragas.metrics._faithfulness import faithfulness
from ragas.metrics._context_precision import context_precision
from ragas.metrics._context_recall import context_recall
from ragas import evaluate, EvaluationDataset
from ragas.dataset_schema import SingleTurnSample

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
from api.main import _load_openai_key


class EvalPipeline:
    def __init__(self, n_samples: int = 50):
        self.n_samples = n_samples
        openai_key = _load_openai_key()
        if not openai_key:
            raise RuntimeError("OpenAI API key not found. Check align-knowledge/.env")
        os.environ["OPENAI_API_KEY"] = openai_key

    def load_benchmark_samples(self) -> list[SingleTurnSample]:
        """
        Load N samples from ragas-wikiqa benchmark on HuggingFace.
        Fields used:
          question            → user_input
          context             → retrieved_contexts (list of passages)
          generated_with_rag  → response (the RAG-generated answer)
          correct_answer      → reference (ground truth)
        """
        print(f"Step 1: Loading {self.n_samples} samples from ragas-wikiqa benchmark...")
        ds = load_dataset("explodinggradients/ragas-wikiqa", split="train", streaming=True)

        samples = []
        for row in ds:
            if len(samples) >= self.n_samples:
                break

            # Skip rows where RAG answer is missing
            if not row.get("generated_with_rag", "").strip():
                continue

            # context is already a list of passage strings
            contexts = row["context"] if isinstance(row["context"], list) else [row["context"]]

            samples.append(
                SingleTurnSample(
                    user_input=row["question"],
                    retrieved_contexts=contexts,
                    response=row["generated_with_rag"],
                    reference=row["correct_answer"],
                )
            )

        print(f"         {len(samples)} samples loaded")
        return samples

    def run_ragas(self, samples: list[SingleTurnSample]) -> dict:
        """Feed samples into RAGAs evaluate() and return scores."""
        print("Step 2: Running RAGAs evaluation metrics...")
        dataset = EvaluationDataset(samples=samples)
        result = evaluate(
            dataset,
            metrics=[faithfulness, context_precision, context_recall],
        )
        df = result.to_pandas()
        return {col: float(df[col].mean()) for col in ["faithfulness", "context_precision", "context_recall"] if col in df.columns}

    def run(self) -> dict:
        samples = self.load_benchmark_samples()
        scores = self.run_ragas(samples)

        print("\n" + "=" * 55)
        print("  RAG SYSTEM RELIABILITY REPORT  (ragas-wikiqa)")
        print("=" * 55)
        print(f"  Benchmark samples evaluated : {len(samples)}")
        print(f"  Evaluation timestamp        : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print()

        metric_descriptions = {
            "faithfulness":      "answer grounded in context (no hallucination)",
            "context_precision": "retrieved passages are relevant to the question",
            "context_recall":    "right passages were retrieved to answer the question",
        }
        for key, desc in metric_descriptions.items():
            val = scores.get(key, "N/A")
            score_str = f"{val:.3f}" if isinstance(val, float) else str(val)
            print(f"  {key:<22} {score_str}   ({desc})")

        print("=" * 55)

        return {
            "scores": scores,
            "n_samples": len(samples),
            "dataset": "explodinggradients/ragas-wikiqa",
            "timestamp": datetime.now().isoformat(),
        }


def main():
    parser = argparse.ArgumentParser(description="RAGAs evaluation using ragas-wikiqa benchmark")
    parser.add_argument("--n", type=int, default=50, help="Number of benchmark samples to evaluate (default: 50)")
    parser.add_argument("--save", action="store_true", help="Save full results to JSON file")
    args = parser.parse_args()

    pipeline = EvalPipeline(n_samples=args.n)
    results = pipeline.run()

    if args.save:
        filename = f"eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Saved to: {filename}")


if __name__ == "__main__":
    main()
