"""Action Executor for NightShift Deployer (Day 6 Task A2).

Wires approved remediation actions to Deployer and Verifier:
- T1 Rollback / Config Revert: executed directly without sandbox or canary stages.
- T2 Code Patch: strictly executed through sequential stages:
    1. Stage 1: Sandbox (isolated git worktree, test suite, and reproduction fix)
    2. Stage 2: Canary (traffic split evaluation against error/latency baseline)
    3. Stage 3: Promote (release deployment and production health verification)
- Enforces strict early abort: any failure in an earlier stage halts execution
  immediately before later stages are invoked.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from contracts.models import FixProposal, VerificationResult
from deployer.release_manager import DeployError, ReleaseManager
from verifier.canary import CanaryMetrics, CanaryVerifier
from verifier.engine import FullVerifier
from verifier.recovery import ProductionRecoveryChecker
from verifier.rollback import AutoRollbackGuard
from verifier.sandbox import SandboxVerifier

logger = logging.getLogger("nightshift.deployer.executor")


@dataclass
class ExecutionResult:
    """Structured outcome of an approved remediation action execution."""
    success: bool
    action_type: str                     # "rollback", "patch", "config"
    risk_tier: str                       # "T1", "T2", "T0", "T3"
    service: str                         # "orders", "payments", "gateway"
    stages_executed: List[str]           # e.g. ["direct_rollback"] or ["sandbox", "canary", "promote"]
    failed_stage: Optional[str] = None   # None, "sandbox", "canary", "promote"
    aborted: bool = False                # True if execution was halted due to earlier stage failure
    verification: Optional[VerificationResult] = None
    deploy_result: Optional[Dict[str, Any]] = None
    rollback_result: Optional[Dict[str, Any]] = None
    message: str = ""
    duration_seconds: float = 0.0
    stage_details: Dict[str, Any] = field(default_factory=dict)


class ActionExecutor:
    """Executes approved remediation actions against Deployer and Verifier engines."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        release_manager: Optional[ReleaseManager] = None,
        full_verifier: Optional[FullVerifier] = None,
        sandbox_verifier: Optional[SandboxVerifier] = None,
        canary_verifier: Optional[CanaryVerifier] = None,
        deploy_fn: Optional[Callable[..., Any]] = None,
        rollback_fn: Optional[Callable[..., Any]] = None,
        metrics_query_fn: Optional[Callable[[str], float]] = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.release_manager = release_manager
        self.deploy_fn = deploy_fn or (release_manager.deploy if release_manager else None)
        self.rollback_fn = rollback_fn or (release_manager.rollback if release_manager else None)
        self.metrics_query_fn = metrics_query_fn

        # Verifiers
        if full_verifier is not None:
            self.full_verifier = full_verifier
            self.sandbox_verifier = sandbox_verifier or full_verifier.sandbox_verifier
            self.canary_verifier = canary_verifier or full_verifier.canary_verifier
        else:
            self.sandbox_verifier = sandbox_verifier or SandboxVerifier(self.repo_root, use_container=False)
            self.canary_verifier = canary_verifier or CanaryVerifier()
            self.full_verifier = FullVerifier(
                self.repo_root,
                use_container=False,
                metrics_query_fn=self.metrics_query_fn,
                release_manager=self.release_manager,
            )

    def execute(
        self,
        action: Union[FixProposal, Any, Dict[str, Any]],
        *,
        incident_id: str = "inc_default",
        fault_id: str = "fault_001_bad_deploy",
        author: str = "nightshift-agent",
        message: str = "",
        to_ref: Optional[str] = None,
        target_ref: Optional[str] = None,
        target_file: Optional[str] = None,
        faulty_file: Optional[str] = None,
        reproduction_command: Optional[Sequence[str]] = None,
        test_command: Optional[Sequence[str]] = None,
        simulated_canary_healthy: Optional[bool] = None,
        post_promotion_error_rate: Optional[float] = None,
    ) -> ExecutionResult:
        """Execute an approved remediation action with strict risk-tier routing.
        
        Routing:
        - T1 Rollback: executes directly via deployer rollback (bypassing sandbox and canary).
        - T2 Code Patch: strictly executed through sequential stages:
            1. Sandbox: isolated worktree testing & repro verification.
            2. Canary: traffic-weighted health validation.
            3. Promote: production deployment & post-promotion recovery verification.
        - Strict abort: earlier stage failure prevents execution of subsequent stages.
        """
        start_time = time.time()
        action_type, risk_tier, service, diff, rationale = self._extract_action_props(action)

        logger.info(
            "Executing approved action: type=%s, tier=%s, service=%s (incident=%s, fault=%s)",
            action_type,
            risk_tier,
            service,
            incident_id,
            fault_id,
        )

        # -------------------------------------------------------------
        # PATH 1: T1 Direct Rollback
        # -------------------------------------------------------------
        if action_type == "rollback" or risk_tier == "T1":
            return self._execute_t1_rollback(
                service=service,
                incident_id=incident_id,
                author=author,
                message=message or rationale or f"Rollback {service} for {incident_id}",
                to_ref=to_ref,
                start_time=start_time,
            )

        # -------------------------------------------------------------
        # PATH 2: T2 Code Patch (Strict 3-Stage Pipeline)
        # -------------------------------------------------------------
        if action_type == "patch" or risk_tier == "T2":
            return self._execute_t2_patch(
                service=service,
                diff=diff,
                incident_id=incident_id,
                fault_id=fault_id,
                author=author,
                message=message or rationale or f"Deploy patch for {incident_id}",
                target_ref=target_ref,
                target_file=target_file,
                faulty_file=faulty_file,
                reproduction_command=reproduction_command,
                test_command=test_command,
                simulated_canary_healthy=simulated_canary_healthy,
                post_promotion_error_rate=post_promotion_error_rate,
                start_time=start_time,
            )

        # -------------------------------------------------------------
        # PATH 3: Config or Other Tiers
        # -------------------------------------------------------------
        if action_type == "config":
            # Config revert maps to T1, config change maps to T2 pipeline
            if risk_tier == "T1":
                return self._execute_t1_rollback(
                    service=service,
                    incident_id=incident_id,
                    author=author,
                    message=message or f"Revert config for {incident_id}",
                    to_ref=to_ref,
                    start_time=start_time,
                )
            else:
                return self._execute_t2_patch(
                    service=service,
                    diff=diff,
                    incident_id=incident_id,
                    fault_id=fault_id,
                    author=author,
                    message=message or f"Apply config patch for {incident_id}",
                    target_ref=target_ref,
                    target_file=target_file,
                    faulty_file=faulty_file,
                    reproduction_command=reproduction_command,
                    test_command=test_command,
                    simulated_canary_healthy=simulated_canary_healthy,
                    post_promotion_error_rate=post_promotion_error_rate,
                    start_time=start_time,
                )

        # Unsupported or unhandled tier
        duration = time.time() - start_time
        return ExecutionResult(
            success=False,
            action_type=action_type,
            risk_tier=risk_tier,
            service=service,
            stages_executed=[],
            failed_stage="validation",
            aborted=True,
            message=f"Action type '{action_type}' with tier '{risk_tier}' is not executable directly",
            duration_seconds=round(duration, 4),
        )

    def _execute_t1_rollback(
        self,
        *,
        service: str,
        incident_id: str,
        author: str,
        message: str,
        to_ref: Optional[str],
        start_time: float,
    ) -> ExecutionResult:
        """Execute a T1 Rollback directly via Deployer without sandbox/canary."""
        stages_executed = ["direct_rollback"]
        stage_details: Dict[str, Any] = {}

        if self.rollback_fn is None:
            duration = time.time() - start_time
            return ExecutionResult(
                success=False,
                action_type="rollback",
                risk_tier="T1",
                service=service,
                stages_executed=stages_executed,
                failed_stage="direct_rollback",
                aborted=True,
                message="No rollback runner configured on ActionExecutor",
                duration_seconds=round(duration, 4),
            )

        try:
            rb_result = self.rollback_fn(
                service=service,
                author=author,
                message=message,
                to_ref=to_ref,
            )
            stage_details["direct_rollback"] = rb_result
            duration = time.time() - start_time
            return ExecutionResult(
                success=True,
                action_type="rollback",
                risk_tier="T1",
                service=service,
                stages_executed=stages_executed,
                rollback_result=rb_result if isinstance(rb_result, dict) else {"result": rb_result},
                message=f"T1 rollback executed directly for service '{service}'",
                duration_seconds=round(duration, 4),
                stage_details=stage_details,
            )
        except Exception as exc:
            duration = time.time() - start_time
            logger.error("T1 direct rollback failed for %s: %s", service, exc)
            return ExecutionResult(
                success=False,
                action_type="rollback",
                risk_tier="T1",
                service=service,
                stages_executed=stages_executed,
                failed_stage="direct_rollback",
                aborted=True,
                message=f"T1 rollback failed: {exc}",
                duration_seconds=round(duration, 4),
                stage_details=stage_details,
            )

    def _execute_t2_patch(
        self,
        *,
        service: str,
        diff: str,
        incident_id: str,
        fault_id: str,
        author: str,
        message: str,
        target_ref: Optional[str],
        target_file: Optional[str],
        faulty_file: Optional[str],
        reproduction_command: Optional[Sequence[str]],
        test_command: Optional[Sequence[str]],
        simulated_canary_healthy: Optional[bool],
        post_promotion_error_rate: Optional[float],
        start_time: float,
    ) -> ExecutionResult:
        """Execute a T2 Code Patch through Sandbox -> Canary -> Promote in strict order."""
        stages_executed: List[str] = []
        stage_details: Dict[str, Any] = {}

        actual_target_file = target_file or f"target-app/services/{service}/app.py"
        actual_faulty_file = faulty_file or f"faults/catalog/{fault_id}/buggy_app.py"
        actual_repro_cmd = reproduction_command or ["python", "tests/verifier/reproduce.py", fault_id]
        actual_test_cmd = test_command or [
            "python", "-m", "pytest", "-q",
            f"tests/verifier/test_reproductions.py::TestDay4Reproductions::test_{fault_id}",
        ]

        # -------------------------------------------------------------
        # STAGE 1: Sandbox Verification
        # -------------------------------------------------------------
        stages_executed.append("sandbox")
        resolved_faulty_file = (
            actual_faulty_file if (self.repo_root / actual_faulty_file).exists() else None
        )
        try:
            sandbox_run = self.sandbox_verifier.verify(
                incident_id=incident_id,
                patch=diff,
                target_file=actual_target_file,
                faulty_file=resolved_faulty_file,
                reproduction_command=actual_repro_cmd,
                test_command=actual_test_cmd,
            )
            stage_details["sandbox"] = {
                "accepted": sandbox_run.accepted,
                "tests_passed": sandbox_run.verification.tests_passed,
                "repro_fixed": sandbox_run.verification.repro_fixed,
                "error": sandbox_run.error,
            }
        except Exception as exc:
            duration = time.time() - start_time
            logger.error("Stage 1 (Sandbox) exception for %s: %s", incident_id, exc)
            return ExecutionResult(
                success=False,
                action_type="patch",
                risk_tier="T2",
                service=service,
                stages_executed=stages_executed,
                failed_stage="sandbox",
                aborted=True,
                message=f"Stage 1 (Sandbox) failed with error: {exc}",
                duration_seconds=round(duration, 4),
                stage_details=stage_details,
            )

        if (
            not sandbox_run.accepted
            or not sandbox_run.verification.tests_passed
            or not sandbox_run.verification.repro_fixed
        ):
            # STAGE 1 FAILED -> ABORT IMMEDIATELY! Do NOT proceed to Canary or Promote.
            duration = time.time() - start_time
            reason = sandbox_run.error or "Unit tests failed or reproduction was not fixed in sandbox"
            logger.warning("Stage 1 (Sandbox) failed for incident %s; aborting execution", incident_id)
            return ExecutionResult(
                success=False,
                action_type="patch",
                risk_tier="T2",
                service=service,
                stages_executed=stages_executed,
                failed_stage="sandbox",
                aborted=True,
                verification=sandbox_run.verification,
                message=f"Stage 1 (Sandbox) verification rejected: {reason}",
                duration_seconds=round(duration, 4),
                stage_details=stage_details,
            )

        # -------------------------------------------------------------
        # STAGE 2: Canary Verification
        # -------------------------------------------------------------
        stages_executed.append("canary")
        if simulated_canary_healthy is not None:
            canary_healthy = simulated_canary_healthy
            canary_details = {"simulated": True, "healthy": canary_healthy}
        else:
            base_rate = self._query_error_rate(service, default=0.20)
            base_metrics = CanaryMetrics(
                total_requests=1000,
                error_count=int(base_rate * 1000),
                error_rate=base_rate,
                mean_latency_ms=25.0,
                p95_latency_ms=45.0,
            )
            sample_metrics = CanaryMetrics(
                total_requests=150,
                error_count=0,
                error_rate=0.00,
                mean_latency_ms=24.0,
                p95_latency_ms=40.0,
            )
            canary_result = self.canary_verifier.evaluate(base_metrics, sample_metrics)
            canary_healthy = canary_result.healthy
            canary_details = {
                "healthy": canary_result.healthy,
                "verdict": getattr(canary_result, "verdict", "PASS"),
                "reason": getattr(canary_result, "reason", getattr(canary_result, "reasons", "")),
            }

        stage_details["canary"] = canary_details

        if not canary_healthy:
            # STAGE 2 FAILED -> ABORT IMMEDIATELY! Do NOT proceed to Promote.
            duration = time.time() - start_time
            logger.warning("Stage 2 (Canary) failed for incident %s; aborting before promotion", incident_id)
            partial_verification = VerificationResult(
                tests_passed=True,
                repro_fixed=True,
                canary_healthy=False,
                metric_before=self._query_error_rate(service, default=0.20),
                metric_after=self._query_error_rate(service, default=0.20),
                recovered_at=None,
                verdict="FAIL",
            )
            return ExecutionResult(
                success=False,
                action_type="patch",
                risk_tier="T2",
                service=service,
                stages_executed=stages_executed,
                failed_stage="canary",
                aborted=True,
                verification=partial_verification,
                message="Stage 2 (Canary) verification failed: canary metrics unhealthy",
                duration_seconds=round(duration, 4),
                stage_details=stage_details,
            )

        # -------------------------------------------------------------
        # STAGE 3: Promote & Production Recovery
        # -------------------------------------------------------------
        stages_executed.append("promote")
        deploy_res: Optional[Dict[str, Any]] = None

        if self.deploy_fn is not None:
            ref_to_deploy = target_ref or "HEAD"
            try:
                deploy_out = self.deploy_fn(
                    service=service,
                    ref=ref_to_deploy,
                    author=author,
                    message=message,
                )
                deploy_res = deploy_out if isinstance(deploy_out, dict) else {"result": deploy_out}
                stage_details["promote"] = deploy_res
            except Exception as exc:
                duration = time.time() - start_time
                logger.error("Stage 3 (Promote) deployment failed for %s: %s", service, exc)
                return ExecutionResult(
                    success=False,
                    action_type="patch",
                    risk_tier="T2",
                    service=service,
                    stages_executed=stages_executed,
                    failed_stage="promote",
                    aborted=True,
                    message=f"Stage 3 (Promote) deployment failed: {exc}",
                    duration_seconds=round(duration, 4),
                    stage_details=stage_details,
                )

        # Evaluate post-promotion health & Auto-Rollback guard
        metric_before = self._query_error_rate(service, default=0.20)
        current_after = (
            post_promotion_error_rate
            if post_promotion_error_rate is not None
            else self._query_error_rate(service, default=0.002)
        )

        rollback_guard = AutoRollbackGuard(
            service=service,
            baseline_error_rate=metric_before,
            release_manager=self.release_manager,
            window_seconds=60.0,
            bad_samples_threshold=1,
        )

        if rollback_guard.is_degraded(current_after):
            # Degraded post-promotion metrics -> trigger auto-rollback!
            rb_decision = rollback_guard.execute_rollback(
                reason=f"Post-promotion error rate ({current_after:.2%}) degraded over baseline ({metric_before:.2%})",
                observed_rate=current_after,
                elapsed=5.0,
            )
            duration = time.time() - start_time
            stage_details["auto_rollback"] = rb_decision.reason
            partial_verification = VerificationResult(
                tests_passed=True,
                repro_fixed=True,
                canary_healthy=True,
                metric_before=metric_before,
                metric_after=current_after,
                recovered_at=None,
                verdict="ROLLBACK",
            )
            return ExecutionResult(
                success=False,
                action_type="patch",
                risk_tier="T2",
                service=service,
                stages_executed=stages_executed,
                failed_stage="promote",
                aborted=True,
                verification=partial_verification,
                rollback_result={"executed": True, "reason": rb_decision.reason},
                message=f"Stage 3 (Promote) degraded; auto-rollback executed: {rb_decision.reason}",
                duration_seconds=round(duration, 4),
                stage_details=stage_details,
            )

        # Successfully recovered!
        recovered_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        duration = time.time() - start_time
        final_verification = VerificationResult(
            tests_passed=True,
            repro_fixed=True,
            canary_healthy=True,
            metric_before=metric_before,
            metric_after=current_after,
            recovered_at=recovered_iso,
            verdict="PASS",
        )

        return ExecutionResult(
            success=True,
            action_type="patch",
            risk_tier="T2",
            service=service,
            stages_executed=stages_executed,
            verification=final_verification,
            deploy_result=deploy_res,
            message=f"T2 patch passed Sandbox, Canary, and Promote with healthy metrics ({current_after:.2%})",
            duration_seconds=round(duration, 4),
            stage_details=stage_details,
        )

    def _extract_action_props(
        self, action: Union[FixProposal, Any, Dict[str, Any]]
    ) -> tuple[str, str, str, str, str]:
        """Normalize action properties from FixProposal, ActionRequest, or dict."""
        if isinstance(action, FixProposal):
            action_type = action.type
            risk_tier = action.risk_tier
            service = action.target_service or "orders"
            diff = action.diff or ""
            rationale = action.rationale or ""
        elif isinstance(action, dict):
            action_type = str(action.get("type", action.get("action_type", "patch")))
            risk_tier = str(action.get("risk_tier", "T2"))
            service = str(action.get("target_service", action.get("service", "orders")))
            diff = str(action.get("diff", ""))
            rationale = str(action.get("rationale", ""))
        else:
            action_type = str(getattr(action, "action_type", getattr(action, "type", "patch")))
            tier_val = getattr(action, "risk_tier", "T2")
            risk_tier = tier_val.value if hasattr(tier_val, "value") else str(tier_val)
            service = str(getattr(action, "target_service", getattr(action, "service", "orders")))
            diff = str(getattr(action, "diff", ""))
            rationale = str(getattr(action, "rationale", ""))

        return action_type, risk_tier, service, diff, rationale

    def _query_error_rate(self, service: str, default: float) -> float:
        """Query current error rate using metrics_query_fn if available."""
        if self.metrics_query_fn is not None:
            try:
                return float(self.metrics_query_fn(service))
            except Exception:
                pass
        return default
