"""Command-line interface for versioned FinTrace evaluations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .embedding import CachedEmbeddingClient
from .e2e import run_end_to_end
from .generation import CachedProgramClient
from .provenance import FINQA_SPLITS, fetch_finqa
from .runner import run_retrieval


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser(
        "fetch-finqa", help="download pinned official FinQA splits"
    )
    fetch.add_argument("--output", type=Path, required=True)
    fetch.add_argument(
        "--splits",
        nargs="+",
        choices=sorted(FINQA_SPLITS),
        default=["dev", "test"],
    )

    retrieval = commands.add_parser(
        "retrieval", help="run a FinQA retrieval experiment"
    )
    retrieval.add_argument("--dataset", type=Path, required=True)
    retrieval.add_argument("--split", choices=("train", "dev", "test"), required=True)
    retrieval.add_argument("--output", type=Path, required=True)
    retrieval.add_argument(
        "--retriever", choices=("bm25", "dense", "rrf"), default="bm25"
    )
    retrieval.add_argument("--k1", type=float, default=1.5)
    retrieval.add_argument("--b", type=float, default=0.75)
    retrieval.add_argument("--rrf-rank-constant", type=int, default=60)
    retrieval.add_argument("--config", type=Path, default=Path(".runtime/config.json"))
    retrieval.add_argument(
        "--embedding-cache",
        type=Path,
        default=Path(".runtime/evaluation/cache/embeddings.sqlite3"),
    )
    retrieval.add_argument("--embedding-dimensions", type=int, default=1024)
    retrieval.add_argument("--embedding-batch-size", type=int, default=10)
    retrieval.add_argument("--max-examples", type=int)

    end_to_end = commands.add_parser(
        "end-to-end", help="run FinQA program synthesis and citation evaluation"
    )
    end_to_end.add_argument("--dataset", type=Path, required=True)
    end_to_end.add_argument("--retrieval-predictions", type=Path, required=True)
    end_to_end.add_argument("--split", choices=("train", "dev", "test"), required=True)
    end_to_end.add_argument("--output", type=Path, required=True)
    end_to_end.add_argument("--top-k", type=int, default=5)
    end_to_end.add_argument("--workers", type=int, default=4)
    end_to_end.add_argument("--verify", action="store_true")
    end_to_end.add_argument("--config", type=Path, default=Path(".runtime/config.json"))
    end_to_end.add_argument(
        "--generation-cache",
        type=Path,
        default=Path(".runtime/evaluation/cache/programs.sqlite3"),
    )
    end_to_end.add_argument("--max-examples", type=int)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    if arguments.command == "fetch-finqa":
        result = fetch_finqa(arguments.output, arguments.splits)
    elif arguments.command == "retrieval":
        embedding_client = None
        if arguments.retriever in {"dense", "rrf"}:
            config = json.loads(arguments.config.read_text(encoding="utf-8"))
            embedding_client = CachedEmbeddingClient(
                base_url=os.environ.get(
                    "FINTRACE_LLM_BASE_URL", config["LLM_BASE_URL"]
                ),
                api_key=os.environ.get("FINTRACE_LLM_API_KEY", config["LLM_API_KEY"]),
                model=os.environ.get(
                    "FINTRACE_EMBEDDING_MODEL", config["EMBEDDING_MODEL"]
                ),
                dimensions=arguments.embedding_dimensions,
                cache_path=arguments.embedding_cache,
                batch_size=arguments.embedding_batch_size,
            )
        try:
            result = run_retrieval(
                arguments.dataset,
                arguments.output,
                split=arguments.split,
                retriever_name=arguments.retriever,
                k1=arguments.k1,
                b=arguments.b,
                rrf_rank_constant=arguments.rrf_rank_constant,
                embedding_client=embedding_client,
                max_examples=arguments.max_examples,
            )
        finally:
            if embedding_client is not None:
                embedding_client.close()
    else:
        config = json.loads(arguments.config.read_text(encoding="utf-8"))
        client = CachedProgramClient(
            base_url=os.environ.get("FINTRACE_LLM_BASE_URL", config["LLM_BASE_URL"]),
            api_key=os.environ.get("FINTRACE_LLM_API_KEY", config["LLM_API_KEY"]),
            model=os.environ.get("FINTRACE_LLM_MODEL", config["LLM_MODEL"]),
            cache_path=arguments.generation_cache,
        )
        try:
            result = run_end_to_end(
                arguments.dataset,
                arguments.retrieval_predictions,
                arguments.output,
                split=arguments.split,
                client=client,
                top_k=arguments.top_k,
                workers=arguments.workers,
                verify=arguments.verify,
                max_examples=arguments.max_examples,
            )
        finally:
            client.close()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
