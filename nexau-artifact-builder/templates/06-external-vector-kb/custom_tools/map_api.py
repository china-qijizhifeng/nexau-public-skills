"""MAP vector-KB tool functions exposed to the LLM.

Search-only tools over MAP's vector knowledge bases (/interface/api/kb/*).
Each tool receives credentials via extra_kwargs (see agent.yaml) — none of
them are LLM-visible. The LLM only sees business parameters such as
knowledge_base_id and query.

Return values are JSON-formatted strings, LLM-friendly.

Tool list:
    map_vec_fulltext_search       →  POST /interface/api/kb/full_search_docs
    map_vec_semantic_search       →  POST /interface/api/kb/search_docs
    map_vec_get_chunks_by_file    →  hybrid + client-side filter by file_id
    map_vec_batch_search          →  parallel cross-product of queries × KBs
                                    over /retriever_search_docs (hybrid)
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from typing import Any

from custom_tools._map_client import MapApiError, MapClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dumps(obj: Any) -> str:
    """Compact-ish JSON, Chinese kept readable, sorted-stable."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _err(msg: str) -> str:
    return _dumps({"error": msg})


def _resolve_vector_kb_id(kb_kwarg: str) -> str:
    """Pick the vector knowledge_base_id with this priority:

    1. explicit `knowledge_base_id` kwarg from the LLM
    2. `MAP_VECTOR_KB_ID` env var (operator's default vector KB)
    3. empty string → caller surfaces an error; the LLM is expected to
       resolve the id from the curated mapping in systemprompt or to ask
       the user.
    """
    if kb_kwarg:
        return kb_kwarg
    return (os.environ.get("MAP_VECTOR_KB_ID") or "").strip()


def _resolve_host(host_kwarg: str) -> str:
    """Pick the MAP gateway host with this precedence:

    1. explicit `host` kwarg (used by unit tests / direct calls)
    2. `MAP_HOST` env var (your own MAP gateway)

    ⚠️ There is no step 3. If neither is set, `MapClient.__init__` raises —
    we never fall back to a shared/demo host, because `getSessionToken` POSTs
    `app_secret` and the default TLS mode does not verify certificates
    (see `_map_client.py` module docstring).

    `MAP_HOST` is deliberately read from `os.environ` instead of agent.yaml's
    `${env.*}`: `${env.*}` fails at *load* time for the whole artifact, which
    would be a worse failure mode than a clear per-call error. It is still
    effectively **required** — see TEMPLATE.md「复制后必须改的地方」.
    """
    if host_kwarg:
        return host_kwarg
    return (os.environ.get("MAP_HOST") or "").strip()


def _build_client(host: str, app_key: str, app_secret: str, user_id: str) -> MapClient:
    """Validate creds early so missing-env-var errors are clear."""
    missing = []
    if not app_key:
        missing.append("MAP_APP_KEY")
    if not app_secret:
        missing.append("MAP_APP_SECRET")
    if not user_id:
        missing.append("MAP_USER_ID")
    if missing:
        raise MapApiError(
            "Missing required runtime variable(s): " + ", ".join(missing)
        )
    return MapClient(
        host=_resolve_host(host),
        app_key=app_key,
        app_secret=app_secret,
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# Vector-KB tools (/interface/api/kb/*) — search-oriented
# ---------------------------------------------------------------------------


def _slim_search_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Reduce a search-result item to fields the LLM can actually USE.

    Kept (high signal):
      - page_content      real chunk text; the answer
      - title             for citation
      - file_name         for citation; derived from `source` if absent
      - file_id           usable handle for map_vec_get_chunks_by_file
      - segment_position  preserved when present (chunks_by_file uses it for ordering)

    Dropped (no actionable value to the LLM):
      - id, score              Agent reads page_content; no fetch-by-id endpoint
      - business_date, source  almost always null / redundant with file_name
      - metadata (full dict)   noise; useful bits surfaced above
    """
    md = hit.get("metadata") or {}
    src = md.get("source") or ""
    derived_file_name = src.rsplit("/", 1)[-1] if src else ""
    out: dict[str, Any] = {
        "page_content": hit.get("page_content") or "",
        "title": md.get("title") or md.get("file_name") or derived_file_name,
        "file_name": md.get("file_name") or derived_file_name,
        "file_id": md.get("file_id"),
    }
    pos = md.get("segment_position")
    if pos is not None:
        out["segment_position"] = pos
    return out


_HYBRID_ENDPOINT = "/interface/api/kb/retriever_search_docs"
_SEMANTIC_ENDPOINT = "/interface/api/kb/search_docs"
_FULLTEXT_ENDPOINT = "/interface/api/kb/full_search_docs"


def _build_search_body(
    endpoint: str,
    *,
    query: str,
    knowledge_base_id: str,
    top_k: int | None = None,
    score_threshold: float | None = None,
    reranker: str | None = None,
    reranker_score_threshold: float | None = None,
    bm_top_k: int | None = None,                # hybrid only
    weights: list[float] | None = None,         # hybrid only
) -> dict[str, Any]:
    """Build the JSON body specific to each MAP search endpoint.

    ⚠️ /retriever_search_docs (hybrid) REQUIRES retriever_type + a fully
    populated `config` (top_k / bm_top_k / weights / score_threshold) or
    the server silently downgrades the call to plain semantic search —
    a bug we hit in production. The other two endpoints use a flat body.
    """
    if endpoint == _HYBRID_ENDPOINT:
        eff_top_k = int(top_k) if top_k else 5
        config: dict[str, Any] = {
            "top_k": eff_top_k,
            "bm_top_k": int(bm_top_k) if bm_top_k else eff_top_k,
            "weights": list(weights) if weights else [0.5, 0.5],
            "score_threshold": float(score_threshold) if score_threshold is not None else 0,
        }
        if reranker_score_threshold is not None:
            config["reranker_score_threshold"] = float(reranker_score_threshold)
        body: dict[str, Any] = {
            "query": query,
            "knowledge_base_id": knowledge_base_id,
            "retriever_type": "hybrid",
            "config": config,
            "is_cache": False,
        }
        if reranker:
            body["use_reranker"] = True
            body["reranker_model"] = reranker
        return body

    # Semantic (search_docs) or full-text (full_search_docs).
    body = {"query": query, "knowledge_base_id": knowledge_base_id}
    if top_k is not None:
        body["top_k"] = int(top_k)
    if score_threshold is not None:
        body["score_threshold"] = float(score_threshold)
    if endpoint == _SEMANTIC_ENDPOINT and reranker:
        body["use_reranker"] = True
        body["reranker_model"] = reranker
        if reranker_score_threshold is not None:
            body["reranker_score_threshold"] = float(reranker_score_threshold)
    return body


_HYBRID_FALLBACK_TRIGGERS = (
    "'Document' object has no attribute 'id'",  # older Document schema crash
    "不支持全文检索",                              # backend has no BM25 index
)


def _hybrid_should_fallback(error_message: str) -> bool:
    return any(t in error_message for t in _HYBRID_FALLBACK_TRIGGERS)


def _hybrid_call_with_fallback(
    client: MapClient,
    *,
    query: str,
    knowledge_base_id: str,
    top_k: int | None = None,
    score_threshold: float | None = None,
    bm_top_k: int | None = None,
    weights: list[float] | None = None,
    reranker: str | None = None,
    reranker_score_threshold: float | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Run hybrid search; on known-broken KB symptoms, fall back to vector
    (semantic) search transparently. Returns (hits, did_fallback).

    Triggered fallbacks:
      - "'Document' object has no attribute 'id'" — server-side reranker
        crash on KBs whose Documents use an older schema.
      - "不支持全文检索" — backend (e.g. m3e-base + non-ES store) lacks
        BM25 index.

    Caller is expected to stamp `fallback: true` on each hit returned
    when did_fallback is True (replaces the previous verbose
    `fallbacks[]` block at top level).
    """
    body = _build_search_body(
        _HYBRID_ENDPOINT,
        query=query,
        knowledge_base_id=knowledge_base_id,
        top_k=top_k,
        score_threshold=score_threshold,
        bm_top_k=bm_top_k,
        weights=weights,
        reranker=reranker,
        reranker_score_threshold=reranker_score_threshold,
    )
    try:
        data = client.call_json(_HYBRID_ENDPOINT, body)
        return (data if isinstance(data, list) else []), False
    except MapApiError as exc:
        original_msg = str(exc)
        if not _hybrid_should_fallback(original_msg):
            raise

    # Fall back to vector / semantic.
    vec_body = _build_search_body(
        _SEMANTIC_ENDPOINT,
        query=query,
        knowledge_base_id=knowledge_base_id,
        top_k=top_k,
        score_threshold=score_threshold,
        reranker=reranker,
        reranker_score_threshold=reranker_score_threshold,
    )
    try:
        data = client.call_json(_SEMANTIC_ENDPOINT, vec_body)
    except MapApiError as exc2:
        raise MapApiError(
            f"hybrid failed: {original_msg} | vector fallback also failed: {exc2}"
        )

    return (data if isinstance(data, list) else []), True


def _do_search(
    *,
    endpoint: str,
    query: str,
    knowledge_base_id: str,
    host: str,
    app_key: str,
    app_secret: str,
    user_id: str,
    top_k: int | None = None,
    score_threshold: float | None = None,
    reranker: str | None = None,
    reranker_score_threshold: float | None = None,
) -> str:
    if not query or not query.strip():
        return _err("query is required")
    kb = _resolve_vector_kb_id(knowledge_base_id)
    if not kb:
        return _err(
            "No vector knowledge base specified. Either pass knowledge_base_id "
            "explicitly (the LLM should resolve it from the curated KB mapping "
            "in the system prompt, based on the user's question), or set the "
            "MAP_VECTOR_KB_ID runtime variable."
        )
    try:
        client = _build_client(host, app_key, app_secret, user_id)
        body = _build_search_body(
            endpoint,
            query=query.strip(),
            knowledge_base_id=kb,
            top_k=top_k,
            score_threshold=score_threshold,
            reranker=reranker,
            reranker_score_threshold=reranker_score_threshold,
        )
        data = client.call_json(endpoint, body)
    except MapApiError as exc:
        return _err(str(exc))

    if not isinstance(data, list):
        data = []
    hits = [_slim_search_hit(h) for h in data if isinstance(h, dict)]
    out: dict[str, Any] = {
        "knowledge_base_id": kb,
        "query": query.strip(),
        "count": len(hits),
        "hits": hits,
    }
    return _dumps(out)


def map_vec_fulltext_search(
    query: str,
    *,
    knowledge_base_id: str = "",
    top_k: int | None = None,
    score_threshold: float | None = None,
    host: str = "",
    app_key: str = "",
    app_secret: str = "",
    user_id: str = "",
    agent_state: Any = None,  # noqa: ARG001
) -> str:
    """Full-text (BM25-style) search inside a vector knowledge base."""
    return _do_search(
        endpoint=_FULLTEXT_ENDPOINT,
        query=query,
        knowledge_base_id=knowledge_base_id,
        host=host,
        app_key=app_key,
        app_secret=app_secret,
        user_id=user_id,
        top_k=top_k,
        score_threshold=score_threshold,
    )


def map_vec_semantic_search(
    query: str,
    *,
    knowledge_base_id: str = "",
    top_k: int | None = None,
    score_threshold: float | None = None,
    reranker: str | None = None,
    reranker_score_threshold: float | None = None,
    host: str = "",
    app_key: str = "",
    app_secret: str = "",
    user_id: str = "",
    agent_state: Any = None,  # noqa: ARG001
) -> str:
    """Pure semantic / embedding-based search inside a vector KB."""
    return _do_search(
        endpoint=_SEMANTIC_ENDPOINT,
        query=query,
        knowledge_base_id=knowledge_base_id,
        host=host,
        app_key=app_key,
        app_secret=app_secret,
        user_id=user_id,
        top_k=top_k,
        score_threshold=score_threshold,
        reranker=reranker,
        reranker_score_threshold=reranker_score_threshold,
    )


_MAX_BATCH_PAIRS = 30


def map_vec_get_chunks_by_file(
    *,
    knowledge_base_id: str = "",
    file_id: str | None = None,
    source_contains: str | None = None,
    query: str | None = None,
    max_chunks: int = 20,
    over_fetch: int = 5,
    score_threshold: float | None = None,
    weights: list[float] | None = None,
    host: str = "",
    app_key: str = "",
    app_secret: str = "",
    user_id: str = "",
    agent_state: Any = None,  # noqa: ARG001
) -> str:
    """Fetch up to `max_chunks` chunks belonging to a single source file
    inside a vector KB (by file_id or by substring match on `source`).

    Why this exists: MAP's vector KB exposes no "list-all-chunks-by-file"
    endpoint and no server-side `file_id` filter on search. We approximate
    by running a wide hybrid_search with `top_k = max_chunks * over_fetch`
    and client-filtering hits whose metadata matches the requested file.

    Use after a normal search (e.g. `map_vec_batch_search`) returned a hit
    you want to drill into: pass that hit's `file_id` (preferred) or
    `source` fragment, plus an optional `query` to bias relevance within
    the file. If `query` is omitted, a generic non-empty query (`"内容"`)
    is used so the server returns *some* ranking — chunks aren't
    necessarily ordered, but you'll get coverage.

    The vector KB id (`knowledge_base_id`) MUST match the one the
    original hit came from — chunks are scoped per vector KB.
    """
    if not file_id and not source_contains:
        return _err("Provide either `file_id` or `source_contains` (or both).")
    kb = _resolve_vector_kb_id(knowledge_base_id)
    if not kb:
        return _err(
            "knowledge_base_id is required (or set MAP_VECTOR_KB_ID). "
            "Pass the same vector KB id where the original hit came from."
        )

    eff_query = (query or "内容").strip()
    eff_max = max(1, int(max_chunks))
    eff_over = max(1, int(over_fetch))
    fetch_k = min(50, eff_max * eff_over)  # server cap on top_k

    body = _build_search_body(
        _HYBRID_ENDPOINT,
        query=eff_query,
        knowledge_base_id=kb,
        top_k=fetch_k,
        bm_top_k=fetch_k,
        score_threshold=score_threshold,
        weights=weights,
    )
    try:
        client = _build_client(host, app_key, app_secret, user_id)
        data = client.call_json(_HYBRID_ENDPOINT, body)
    except MapApiError as exc:
        return _err(str(exc))

    if not isinstance(data, list):
        data = []

    matched: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for hit in data:
        if not isinstance(hit, dict):
            continue
        md = hit.get("metadata") or {}
        ok = False
        if file_id and md.get("file_id") == file_id:
            ok = True
        elif source_contains and source_contains in (md.get("source") or ""):
            ok = True
        if not ok:
            continue
        hid = hit.get("id") or ""
        if hid and hid in seen_ids:
            continue
        if hid:
            seen_ids.add(hid)
        matched.append(_slim_search_hit(hit))
        if len(matched) >= eff_max:
            break

    # Order by segment_position when available; otherwise keep server order
    # (server hits already arrive score-desc).
    matched.sort(
        key=lambda h: (
            h.get("segment_position")
            if h.get("segment_position") is not None
            else 1_000_000
        )
    )
    return _dumps(
        {
            "knowledge_base_id": kb,
            "file_id": file_id,
            "source_contains": source_contains,
            "query_used": eff_query,
            "fetched": len(data),
            "matched": len(matched),
            "chunks": matched,
            "hint": (
                "Chunks ordered by segment_position when present; "
                "otherwise by score-desc fallback. Increase `max_chunks` "
                "or `over_fetch` if coverage looks incomplete."
            ),
        }
    )


def map_vec_batch_search(
    *,
    queries: list[str] | None = None,
    query: str | None = None,
    knowledge_base_ids: list[str],
    top_k: int | None = None,
    score_threshold: float | None = None,
    bm_top_k: int | None = None,
    weights: list[float] | None = None,
    reranker: str | None = None,
    reranker_score_threshold: float | None = None,
    host: str = "",
    app_key: str = "",
    app_secret: str = "",
    user_id: str = "",
    agent_state: Any = None,  # noqa: ARG001
) -> str:
    """Hybrid-search a CROSS-PRODUCT of `queries` × `knowledge_base_ids` in
    parallel, then merge & dedup the hits.

    Total HTTP calls = len(queries) * len(knowledge_base_ids). Hard-capped
    at 30 pairs to avoid runaway. Each call goes through
    /retriever_search_docs (BM25 + vector + optional rerank) so each hit
    has the same shape as the single-shot search tools.

    Aggregation:
      - Hits are deduped by their `id` (chunk-level identity).
      - When the same chunk is hit by multiple queries (or appears in
        multiple KBs with the same id, which is rare), we keep the max
        score and accumulate all matching queries into `matched_queries`.

    Why the cross-product:
      - One query, several plausible KBs → broaden coverage.
      - Several synonym queries, one KB → robust to wording differences
        (e.g. "政务" + "政府" + "行政" against the same KB).
      - Both axes — when discovery returned several KBs and you also have
        a few synonym candidates.

    Convenience:
      - `query` (singular string) is accepted as sugar for `queries=[query]`.
      - At least one of `query` / `queries` must be provided.
    """
    # Normalize queries (list, dedup, strip).
    raw_queries: list[str] = []
    if queries:
        if not isinstance(queries, list):
            return _err("queries must be a list of strings")
        raw_queries.extend(q for q in queries if isinstance(q, str))
    if query:
        if not isinstance(query, str):
            return _err("query must be a string")
        raw_queries.append(query)

    seen_q: set[str] = set()
    qs: list[str] = []
    for q in raw_queries:
        s = q.strip()
        if s and s not in seen_q:
            seen_q.add(s)
            qs.append(s)
    if not qs:
        return _err(
            "Provide at least one query: pass `queries` (array) or `query` (string)."
        )

    # Normalize KB ids (list, dedup).
    if not isinstance(knowledge_base_ids, list) or not knowledge_base_ids:
        return _err("knowledge_base_ids must be a non-empty list")
    seen_kb: set[str] = set()
    kb_ids: list[str] = []
    for k in knowledge_base_ids:
        if isinstance(k, str) and k and k not in seen_kb:
            seen_kb.add(k)
            kb_ids.append(k)
    if not kb_ids:
        return _err("knowledge_base_ids contained no valid ids")

    pairs: list[tuple[str, str]] = [(q, kb) for q in qs for kb in kb_ids]
    if len(pairs) > _MAX_BATCH_PAIRS:
        return _err(
            f"Too many search pairs ({len(pairs)} = {len(qs)} queries × "
            f"{len(kb_ids)} KBs). Cap is {_MAX_BATCH_PAIRS}. Reduce either side."
        )

    try:
        client = _build_client(host, app_key, app_secret, user_id)
    except MapApiError as exc:
        return _err(str(exc))

    def _one(
        pair: tuple[str, str],
    ) -> tuple[str, str, list[dict[str, Any]], bool, str | None]:
        q, kb = pair
        try:
            data, did_fallback = _hybrid_call_with_fallback(
                client,
                query=q,
                knowledge_base_id=kb,
                top_k=top_k,
                score_threshold=score_threshold,
                bm_top_k=bm_top_k,
                weights=weights,
                reranker=reranker,
                reranker_score_threshold=reranker_score_threshold,
            )
            return q, kb, data, did_fallback, None
        except MapApiError as exc:
            return q, kb, [], False, str(exc)

    # Dedup by raw chunk id (which we strip from output via _slim_search_hit).
    by_id: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    synthetic_counter = 0  # for hits without a usable id

    workers = min(8, len(pairs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for q, kb, data, did_fallback, err in pool.map(_one, pairs):
            if err is not None:
                errors.append({"query": q, "knowledge_base_id": kb, "error": err})
                continue
            for hit in data:
                if not isinstance(hit, dict):
                    continue
                hid = hit.get("id")
                if not hid:
                    synthetic_counter += 1
                    hid = f"_no_id_{synthetic_counter}"
                raw_score = hit.get("score")

                if hid in by_id:
                    existing = by_id[hid]
                    old = existing.get("_internal_score")
                    if raw_score is not None and (old is None or raw_score > old):
                        existing["_internal_score"] = raw_score
                    matched: list[str] = existing.setdefault("matched_queries", [])
                    if q not in matched:
                        matched.append(q)
                else:
                    slim = _slim_search_hit(hit)
                    slim["knowledge_base_id"] = kb
                    slim["matched_queries"] = [q]
                    slim["_internal_score"] = raw_score
                    if did_fallback:
                        slim["fallback"] = True
                    by_id[hid] = slim

    deduped = list(by_id.values())
    deduped.sort(
        key=lambda h: (
            h.get("_internal_score")
            if h.get("_internal_score") is not None
            else -1.0
        ),
        reverse=True,
    )
    cap = int(top_k) if top_k and int(top_k) > 0 else 20
    truncated = deduped[:cap]
    for h in truncated:
        h.pop("_internal_score", None)

    return _dumps(
        {
            "queries": qs,
            "knowledge_base_ids": kb_ids,
            "calls_made": len(pairs),
            "errors": errors,
            "count": len(truncated),
            "hits": truncated,
        }
    )


__all__ = [
    "map_vec_fulltext_search",
    "map_vec_semantic_search",
    "map_vec_batch_search",
    "map_vec_get_chunks_by_file",
]
