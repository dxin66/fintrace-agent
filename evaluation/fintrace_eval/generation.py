"""Cached OpenAI-compatible program synthesis for FinQA."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .dataset import EvidenceCandidate, FinQAExample
from .program import parse_program

PROMPT_VERSION = "fintrace-finqa-program-v3"
SYSTEM_PROMPT = """You solve FinQA questions by emitting an executable program and evidence IDs.
Use only the supplied evidence. Return exactly one JSON object with this schema:
{"program":"operation(arg1, arg2), ...","citations":["evidence_id", ...]}
Allowed operations: add, subtract, multiply, divide, exp, greater, table_max, table_min,
table_sum, table_average. Use #0, #1, ... to reference prior steps and const_100-style
constants when needed. For table operations, use the row label as arg1 and none as arg2.
The program value must use exactly the FinQA sequential DSL. Never use assignments, equals signs,
quotes, variable names, or dates as table-operation arguments. Valid examples are
"subtract(120, 100), divide(#0, 100)" and "table_average(revenue, none)".
Each operation must be a separate flat step; nested function calls are invalid. Use exact numeric
literals from the evidence. The evaluator compares the raw execution result, so a percentage ratio
computed with divide normally remains a fraction; do not multiply by 100 merely because the
question or displayed answer uses percent formatting.
Do not include prose, Markdown, an answer field, or evidence IDs that were not supplied."""


@dataclass(frozen=True)
class ProgramPrediction:
    program: str
    citations: tuple[str, ...]
    raw_content: str
    cache_hit: bool
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    parse_error: str | None


def build_user_prompt(example: FinQAExample, evidence: list[EvidenceCandidate]) -> str:
    lines = [f"Question: {example.question}", "Evidence:"]
    lines.extend(f"[{item.evidence_id}] {item.text}" for item in evidence)
    return "\n".join(lines)


def _extract_prediction(content: str) -> tuple[str, tuple[str, ...]]:
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response does not contain a JSON object")
    payload = json.loads(content[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model response must be a JSON object")
    program = payload.get("program")
    citations = payload.get("citations")
    if not isinstance(program, str):
        raise ValueError("model response has no string program")
    if not isinstance(citations, list) or not all(
        isinstance(item, str) for item in citations
    ):
        raise ValueError("model response citations must be a string array")
    return program, tuple(dict.fromkeys(citations))


class CachedProgramClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        cache_path: str | Path,
        timeout_seconds: float = 120,
    ) -> None:
        if not api_key:
            raise ValueError("model API key is empty")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.cache_path, check_same_thread=False)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS program_predictions (
                cache_key TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                prompt_sha256 TEXT NOT NULL,
                response_json TEXT NOT NULL
            )
            """
        )
        self.connection.commit()
        self.lock = threading.Lock()
        self.request_count = 0
        self.cache_hits = 0

    def close(self) -> None:
        self.connection.close()

    def _key(self, user_prompt: str) -> tuple[str, str]:
        prompt_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()
        material = f"{self.model}\0{PROMPT_VERSION}\0{prompt_hash}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest(), prompt_hash

    def _cached(self, key: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT response_json FROM program_predictions WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                self.cache_hits += 1
                return json.loads(row[0])
        return None

    def predict(self, user_prompt: str) -> ProgramPrediction:
        key, prompt_hash = self._key(user_prompt)
        cached = self._cached(key)
        if cached is not None:
            return self._decode(cached, cache_hit=True)

        started = time.perf_counter()
        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "temperature": 0,
                        "max_tokens": 300,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                    timeout=self.timeout_seconds,
                )
                if response.status_code != 429 and response.status_code < 500:
                    response.raise_for_status()
                    break
                response.raise_for_status()
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                retryable = isinstance(error, httpx.TransportError) or (
                    error.response.status_code == 429
                    or error.response.status_code >= 500
                )
                if not retryable or attempt == 2:
                    raise
                time.sleep(2**attempt)
        if response is None:
            raise RuntimeError("model request completed without a response")
        latency_ms = (time.perf_counter() - started) * 1000
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        parse_error = None
        try:
            program, citations = _extract_prediction(content)
            parse_program(program)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            program = ""
            citations = ()
            parse_error = str(error)
        usage = body.get("usage", {})
        stored = {
            "program": program,
            "citations": list(citations),
            "raw_content": content,
            "latency_ms": latency_ms,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
            "parse_error": parse_error,
        }
        with self.lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO program_predictions VALUES (?, ?, ?, ?, ?)",
                (key, self.model, PROMPT_VERSION, prompt_hash, json.dumps(stored)),
            )
            self.connection.commit()
            self.request_count += 1
        return self._decode(stored, cache_hit=False)

    @staticmethod
    def _decode(stored: dict[str, Any], *, cache_hit: bool) -> ProgramPrediction:
        return ProgramPrediction(
            program=stored["program"],
            citations=tuple(stored["citations"]),
            raw_content=stored["raw_content"],
            cache_hit=cache_hit,
            latency_ms=float(stored["latency_ms"]),
            prompt_tokens=int(stored["prompt_tokens"]),
            completion_tokens=int(stored["completion_tokens"]),
            total_tokens=int(stored["total_tokens"]),
            parse_error=stored.get("parse_error"),
        )

    def stats(self) -> dict[str, int | str]:
        return {
            "model": self.model,
            "prompt_version": PROMPT_VERSION,
            "request_count": self.request_count,
            "cache_hits": self.cache_hits,
        }
