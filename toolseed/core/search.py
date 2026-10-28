"""Deterministic keyword retrieval (P0-SLIM §8).

Order is fixed: direct id lookup, hard filters, then keyword ranking. At most 5
cards are returned and an empty list is a valid answer.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .applicability import assess_applicability
from .concepts import concepts
from .errors import INVALID_ARGUMENT, error_response
from .evidence import Evidence
from .knowledge import version_structure
from .manifest import CandidateError
from .recall import match_recall, normalize_recall
from .registry import STATUS_READY, Registry
from .storage import Store

_TOKEN = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
DEFAULT_RESULTS = 3
MAX_RESULTS = 5
EXCERPT_CHARS = 160


def tokens(text: str) -> set[str]:
    """ASCII words plus CJK unigrams/bigrams.

    P0 retrieval is deterministic keyword matching. Chinese manifests have no
    spaces, so a plain ``[a-z0-9_]+`` tokenizer would make every Chinese query
    empty. Bigrams keep phrase matches meaningful without a full tokenizer.
    """
    lowered = text.lower()
    found = set(_TOKEN.findall(lowered))
    for match in _CJK_RUN.finditer(lowered):
        run = match.group()
        found.update(run)
        found.update(run[index : index + 2] for index in range(len(run) - 1))
    return found


class Search:
    def __init__(
        self,
        store: Store,
        registry: Registry,
        *,
        max_results: int = DEFAULT_RESULTS,
    ) -> None:
        if (
            not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or not 1 <= max_results <= MAX_RESULTS
        ):
            raise ValueError(f"max_results must be an integer from 1 to {MAX_RESULTS}")
        self.store = store
        self.registry = registry
        self.evidence = Evidence(store)
        self.max_results = max_results

    def search(self, query: Any, context: Any = None) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return error_response(INVALID_ARGUMENT, "query must be a non-empty string")
        if context is not None and not isinstance(context, dict):
            return error_response(INVALID_ARGUMENT, "context must be an object")
        context = context or {}
        try:
            recall = normalize_recall(context.get("recall"), query)
        except CandidateError as exc:
            return error_response(exc.code, exc.message)
        namespaces = self._namespaces(context)

        direct = self._direct_lookup(query.strip()) if recall is None else None
        if direct is not None:
            return {"results": [self._card(*direct, context=context)]}

        wanted = tokens(query) if recall is None else set()
        concept_goal = concepts(query) if recall is None else set()
        scored: list[tuple[float, Any, Any, Any]] = []
        for capability, version in self.registry.deliverable_capabilities(namespaces):
            manifest = json.loads(version["manifest_json"])
            if not self._applicability_compatible(manifest, context):
                continue
            reason = None
            structure = version_structure(version)
            recognition = " ".join([*structure["aliases"], *structure["triggers"]]) if structure else ""
            if recall is not None:
                score, reason = match_recall(query, recall, manifest, version["content"], recognition)
            else:
                score = self._score(wanted, manifest, version["content"])
                score += 2.0 * len(wanted & tokens(recognition))
                score += 2.0 * len(concept_goal & concepts(" ".join([
                    manifest["name"], manifest["description"], manifest["when_to_use"],
                    *manifest["tags"], recognition, version["content"]])))
            if score <= 0:
                continue
            scored.append((score, capability, version, reason))

        scored.sort(key=lambda item: (-item[0], item[1]["name"]))
        return {
            "results": [
                {**self._card(capability, version, context=context),
                 **({"recall_match": reason} if reason is not None else {})}
                for _, capability, version, reason in scored[: min(self.max_results, 2) if recall else self.max_results]
            ]
        }

    # -- internals --------------------------------------------------------
    @staticmethod
    def _namespaces(context: dict[str, Any]) -> tuple[str, ...]:
        current = context.get("namespace") or context.get("workspace")
        if isinstance(current, str) and current.strip():
            namespace = current.strip()
            return ("global",) if namespace == "global" else ("global", namespace)
        return ("global",)

    def _direct_lookup(self, text: str) -> tuple[Any, Any] | None:
        capability = self.registry.get_capability(text)
        if capability is None:
            return None
        if capability["archived_at"] or capability["quarantined_at"]:
            return None
        version = self.registry.current_version(capability)
        if version is None or version["status"] != STATUS_READY:
            return None
        return capability, version

    def _applicability_compatible(self, manifest: dict[str, Any], context: dict[str, Any]) -> bool:
        return assess_applicability(manifest, context)["status"] != "incompatible"

    def _score(self, wanted: set[str], manifest: dict[str, Any], content: str) -> float:
        if not wanted:
            return 0.0
        score = 3.0 * len(wanted & tokens(manifest["name"]))
        tag_tokens: set[str] = set()
        for tag in manifest["tags"]:
            tag_tokens |= tokens(tag)
        score += 2.0 * len(wanted & tag_tokens)
        score += 1.0 * len(wanted & tokens(manifest["description"]))
        score += 1.0 * len(wanted & tokens(manifest["when_to_use"]))
        score += 0.5 * len(wanted & tokens(content))
        return score

    def _card(self, capability: Any, version: Any, *, context: dict[str, Any]) -> dict[str, Any]:
        manifest = json.loads(version["manifest_json"])
        excerpt = " ".join(version["content"].split())[:EXCERPT_CHARS]
        return {
            "capability_id": capability["capability_id"],
            "version_id": version["version_id"],
            "version": version["version_number"],
            "content_hash": version["content_hash"],
            "namespace": capability["namespace"],
            "name": manifest["name"],
            "kind": manifest["kind"],
            "description": manifest["description"],
            "when_to_use": manifest["when_to_use"],
            "not_for": manifest["not_for"],
            "applicability": manifest["applicability"],
            "applicability_check": assess_applicability(manifest, context),
            "verification_summary": self.evidence.verification_summary(version["version_id"]),
            "learning_summary": self.evidence.learning_summary(version["version_id"]),
            "reuse_summary": self.evidence.reuse_summary(version["version_id"]),
            "tags": manifest["tags"],
            "content_excerpt": excerpt,
        }
