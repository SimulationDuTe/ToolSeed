"""Stable ToolSeed facade. Domain services own operation rules and transactions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .candidates import CandidateService
from .delivery import DeliveryService
from .evidence import Evidence
from .evidence_service import EvidenceService
from .learning_service import LearningService
from .lifecycle import LifecycleService
from .maintenance_service import MaintenanceService
from .registry import Registry
from .revisions import RevisionService
from .search import DEFAULT_RESULTS, MAX_RESULTS, Search
from .service_support import ORIGIN_CONTEXT_FIELDS, ORIGIN_CONTEXT_MAX, ORIGIN_INTENT_MAX
from .storage import Store, default_data_dir


class ToolSeed:
    """Local capability API; services share one Store and its nested transactions."""

    _ORIGIN_CONTEXT_MAX = ORIGIN_CONTEXT_MAX
    _ORIGIN_INTENT_MAX = ORIGIN_INTENT_MAX
    _ORIGIN_CONTEXT_FIELDS = ORIGIN_CONTEXT_FIELDS

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        max_results: int = DEFAULT_RESULTS,
    ) -> None:
        if (
            not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or not 1 <= max_results <= MAX_RESULTS
        ):
            raise ValueError(f"max_results must be an integer from 1 to {MAX_RESULTS}")
        self.store = Store(data_dir if data_dir is not None else default_data_dir())
        self.registry = Registry(self.store)
        self.evidence = Evidence(self.store)
        self.search_engine = Search(self.store, self.registry, max_results=max_results)
        self.candidates = CandidateService(self.store, self.registry, self.evidence)
        self.learning = LearningService(self.store, self.registry, self.evidence, self.candidates)
        self.lifecycle = LifecycleService(self.store, self.registry, self.evidence)
        self.verification = EvidenceService(self.store, self.registry, self.evidence)
        self.maintenance = MaintenanceService(
            self.store, self.registry, self.evidence, self.candidates
        )
        self.delivery = DeliveryService(
            self.store, self.registry, self.evidence, self.search_engine
        )
        self.revisions = RevisionService(
            self.store, self.registry, self.evidence, self.verification, self.lifecycle
        )

    def prepare_revision_validation(self, binding: Any, environment: Any = None) -> dict[str, Any]:
        return self.revisions.prepare(binding, environment)

    def complete_revision_validation(self, receipt: Any) -> dict[str, Any]:
        return self.revisions.complete(receipt)

    def toolbox_search(self, query: Any, context: Any = None) -> dict[str, Any]:
        return self.delivery.toolbox_search(query, context)

    def toolbox_save(self, candidate: Any, intent: Any = "", context: Any = None) -> dict[str, Any]:
        result = self.candidates.save(candidate, intent, context)
        target = candidate.get("target_capability_id") if isinstance(candidate, dict) else None
        self.delivery.record_tool_failure("toolbox_save", result, target)
        return result

    def toolbox_learn(self, experience: Any, context: Any = None) -> dict[str, Any]:
        """Persist model-extracted methods and observations in one transaction."""
        result = self.learning.learn(experience, context)
        self.delivery.record_tool_failure("toolbox_learn", result)
        return result

    def toolbox_run(self, capability: Any, args: Any = None, options: Any = None) -> dict[str, Any]:
        return self.delivery.toolbox_run(capability, args, options)

    def toolbox_stats(self) -> dict[str, Any]:
        return self.delivery.toolbox_stats()

    def quarantine(self, capability_id: Any, reason: str = "manual quarantine") -> dict[str, Any]:
        return self.lifecycle.quarantine(capability_id, reason)

    def quarantine_version(
        self, version_id: Any, reason: str = "manual quarantine"
    ) -> dict[str, Any]:
        return self.lifecycle.quarantine_version(version_id, reason)

    def release_capability(
        self, capability_id: Any, reason: str, evidence_ref: str | None = None
    ) -> dict[str, Any]:
        """Lift a whole-capability quarantine after explicit review.

        Archival is permanent and is not undone here. The reason and optional
        evidence reference are recorded as an append-only audit event."""
        return self.lifecycle.release_capability(capability_id, reason, evidence_ref)

    def release_version(
        self, version_id: Any, reason: str, evidence_ref: str | None = None
    ) -> dict[str, Any]:
        """Release a quarantined version back to candidate (still not deliverable)."""
        return self.lifecycle.release_version(version_id, reason, evidence_ref)

    def promote_version(
        self, version_id: Any, reason: str, evidence_ref: str | None = None
    ) -> dict[str, Any]:
        """Promote a candidate only if valid independent verification is bound to it."""
        return self.lifecycle.promote_version(version_id, reason, evidence_ref)

    def rollback_version(
        self, capability_id: Any, version_id: Any, reason: Any, evidence_ref: Any = None
    ) -> dict[str, Any]:
        return self.lifecycle.rollback_version(capability_id, version_id, reason, evidence_ref)

    def assess_evidence(
        self,
        evidence_id: Any,
        validity: Any,
        reason_code: Any,
        *,
        fingerprint: dict[str, Any] | None = None,
        invalidated_by: Any = None,
        superseded_by: Any = None,
    ) -> dict[str, Any]:
        """Append a trusted local manager's declaration, not independent verification.

        Fingerprints are optional audit snapshots, not checked attestations. This
        management method is not exposed through the public Agent tools."""
        return self.verification.assess_evidence(
            evidence_id,
            validity,
            reason_code,
            fingerprint=fingerprint,
            invalidated_by=invalidated_by,
            superseded_by=superseded_by,
        )

    def evidence_validity(self, evidence_id: Any) -> dict[str, Any]:
        return self.verification.evidence_validity(evidence_id)

    def expire_version_evidence(
        self, version_id: Any, reason_code: Any = "policy_or_environment_changed"
    ) -> dict[str, Any]:
        return self.verification.expire_version_evidence(version_id, reason_code)

    def expire_version_observations(
        self, version_id: Any, reason_code: Any = "policy_or_environment_changed"
    ) -> dict[str, Any]:
        return self.verification.expire_version_observations(version_id, reason_code)

    def maintenance_report(self) -> dict[str, Any]:
        return self.maintenance.maintenance_report()

    def version_report(self, version_id: Any) -> dict[str, Any]:
        return self.maintenance.version_report(version_id)

    def run_maintenance(self) -> dict[str, Any]:
        return self.maintenance.run_maintenance()

    def list_evolution_decisions(
        self, *, status: Any = None, capability_id: Any = None
    ) -> dict[str, Any]:
        return self.maintenance.list_evolution_decisions(status=status, capability_id=capability_id)

    def dismiss_evolution_decision(
        self, decision_id: Any, resolution: Any = None
    ) -> dict[str, Any]:
        return self.maintenance.dismiss_evolution_decision(decision_id, resolution)

    def record_observation(
        self,
        *,
        capability_id: Any,
        observation_type: Any,
        summary: Any,
        version_id: Any = None,
        evidence_ids: Any = None,
        applicability: Any = None,
        generation_method: Any = "human",
        confidence: Any = None,
    ) -> dict[str, Any]:
        return self.verification.record_observation(
            capability_id=capability_id,
            observation_type=observation_type,
            summary=summary,
            version_id=version_id,
            evidence_ids=evidence_ids,
            applicability=applicability,
            generation_method=generation_method,
            confidence=confidence,
        )

    def list_observations(
        self, *, capability_id: Any = None, version_id: Any = None, status: Any = None
    ) -> dict[str, Any]:
        return self.verification.list_observations(
            capability_id=capability_id, version_id=version_id, status=status
        )

    def set_observation_status(
        self, observation_id: Any, status: Any, reason: Any = None
    ) -> dict[str, Any]:
        return self.verification.set_observation_status(observation_id, status, reason)

    def apply_evolution_decision(self, decision_id: Any, resolution: Any = None) -> dict[str, Any]:
        return self.maintenance.apply_evolution_decision(decision_id, resolution)

    def diagnose_failure(
        self,
        *,
        capability_id: Any,
        version_id: Any,
        category: Any,
        summary: Any,
        invocation_id: Any = None,
        task_id: Any = None,
        evidence_ids: Any = None,
    ) -> dict[str, Any]:
        return self.maintenance.diagnose_failure(
            capability_id=capability_id,
            version_id=version_id,
            category=category,
            summary=summary,
            invocation_id=invocation_id,
            task_id=task_id,
            evidence_ids=evidence_ids,
        )

    def list_failure_diagnoses(
        self, *, capability_id: Any = None, status: Any = None
    ) -> dict[str, Any]:
        return self.maintenance.list_failure_diagnoses(capability_id=capability_id, status=status)

    def dismiss_diagnosis(self, diagnosis_id: Any) -> dict[str, Any]:
        return self.maintenance.dismiss_diagnosis(diagnosis_id)

    def propose_repair(
        self,
        diagnosis_id: Any,
        candidate: Any,
        intent: Any = "repair candidate",
        context: Any = None,
    ) -> dict[str, Any]:
        return self.maintenance.propose_repair(diagnosis_id, candidate, intent, context)

    def archive(self, capability_id: Any, reason: str = "manual archive") -> dict[str, Any]:
        return self.lifecycle.archive(capability_id, reason)

    def record_version_verification(
        self,
        *,
        version_id: Any,
        content_hash: Any,
        outcome: Any,
        source_type: Any,
        verification_ref: Any,
        verification: Any,
    ) -> dict[str, Any]:
        """Append version-bound evidence without changing lifecycle state."""
        return self.verification.record_version_verification(
            version_id=version_id,
            content_hash=content_hash,
            outcome=outcome,
            source_type=source_type,
            verification_ref=verification_ref,
            verification=verification,
        )

    def record_task_outcome(
        self,
        *,
        capability_id: Any,
        version_id: Any,
        invocation_id: Any,
        outcome: Any,
        source_type: Any,
        task_id: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Record a task-result signal together with its source (never inferred)."""
        return self.verification.record_task_outcome(
            capability_id=capability_id,
            version_id=version_id,
            invocation_id=invocation_id,
            outcome=outcome,
            source_type=source_type,
            task_id=task_id,
            summary=summary,
        )

    def close(self) -> None:
        self.store.close()
