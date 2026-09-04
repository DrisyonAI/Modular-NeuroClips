"""
NeuroBranch™ Scenario Orchestrator Sub-Agent.
Generates structured, multi-path scenario DAGs for non-linear interactive learning.
Synthesizes decision points, consequences, and adaptive branching trees from topic or curriculum prompts.
"""
import uuid
from typing import Optional, Dict, Any
from src.contracts.scenario_contract import (
    ScenarioDAGContract,
    ScenarioNode,
    ScenarioChoice,
    NodeCategoryEnum,
)


class ScenarioOrchestrator:
    """
    Orchestrates creation of non-linear branching scenario simulations.
    Generates realistic dilemmas, multiple decision branches, and corresponding outcomes.
    """

    def generate_scenario_dag(
        self,
        topic: str,
        domain: str = "FinTech & Enterprise Risk",
        presenter_persona: str = "srinivas_cloud",
        depth: int = 2,
    ) -> ScenarioDAGContract:
        """
        Generates a validated scenario DAG.
        Creates a root dilemma, decision branches with weighted scoring,
        and outcome/remediation nodes.
        """
        scenario_id = f"sim_{uuid.uuid4().hex[:8]}"
        clean_topic = topic.strip() or "High-Frequency Algorithmic Risk Escalation"

        # Root dilemma
        root_node = ScenarioNode(
            node_id="node_root",
            title=f"Incident Briefing: {clean_topic[:40]}",
            category=NodeCategoryEnum.ROOT_DILEMMA,
            presenter_persona=presenter_persona,
            narration=(
                f"Team, we have an urgent situation unfolding. {clean_topic}. "
                "Anomaly thresholds have triggered across production clusters. "
                "You must decide on our immediate course of action right now."
            ),
            visual_prompt=(
                "Modern high-tech financial operations command center, multiple glowing red warning monitors, "
                "data telemetry dashboards displaying critical latency spikes, ultra-realistic 8k cinematic lighting"
            ),
            motion_prompt="Dynamic push-in camera toward alert console",
            duration_seconds=7.0,
            choices=[
                ScenarioChoice(
                    choice_id="choice_halt",
                    label="Action 1: Emergency System Halt & Circuit Breaker",
                    target_node_id="node_halt_outcome",
                    competency_score=85,
                    feedback_rationale="Immediately halts risk exposure, though causes transient client transaction drop."
                ),
                ScenarioChoice(
                    choice_id="choice_divert",
                    label="Action 2: Dynamic Traffic Rerouting & Sandbox Isolation",
                    target_node_id="node_divert_outcome",
                    competency_score=95,
                    feedback_rationale="Best practice: isolates anomalous flows into quarantine sandbox without business stoppage."
                ),
                ScenarioChoice(
                    choice_id="choice_monitor",
                    label="Action 3: Passive Observation & Wait for Batch Reconciliation",
                    target_node_id="node_monitor_failure",
                    competency_score=-40,
                    feedback_rationale="High risk violation: waiting allows potential exploitation to compound across settlement nodes."
                ),
            ],
            is_terminal=False,
        )

        # Branch A outcome: Halt
        halt_node = ScenarioNode(
            node_id="node_halt_outcome",
            title="Circuit Breaker Tripped - Containment",
            category=NodeCategoryEnum.CONSEQUENCE,
            presenter_persona=presenter_persona,
            narration=(
                "Emergency circuit breakers engaged. Trading activity has halted safely. "
                "We prevented systemic capital drawdown, but downstream clearing queues are backing up. "
                "Let us move directly to audit forensics and executive notification."
            ),
            visual_prompt=(
                "Enterprise server room command desk, amber standby indicators, calming blue ambient glow, "
                "system status monitors showing zero active transactions, professional clean corporate environment"
            ),
            motion_prompt="Slow panning tracking shot across standby monitors",
            duration_seconds=6.5,
            choices=[
                ScenarioChoice(
                    choice_id="choice_debrief_safe",
                    label="Proceed to Executive Incident Debrief",
                    target_node_id="node_final_debrief",
                    competency_score=15,
                    feedback_rationale="Follows incident response protocol for regulatory filing."
                )
            ],
            is_terminal=False,
        )

        # Branch B outcome: Divert (Optimal)
        divert_node = ScenarioNode(
            node_id="node_divert_outcome",
            title="Surgical Sandbox Isolation - Optimal Result",
            category=NodeCategoryEnum.CONSEQUENCE,
            presenter_persona=presenter_persona,
            narration=(
                "Outstanding execution. The anomalous traffic has been surgically shunted into an isolated honeypot. "
                "Zero legitimate customer orders were dropped, and our security models are capturing full adversary telemetry. "
                "Regulatory exposure has been minimized to zero."
            ),
            visual_prompt=(
                "Modern executive analytics glass boardroom, clean green telemetry graphs showing seamless traffic routing, "
                "cutting-edge enterprise architecture diagram on interactive holographic display"
            ),
            motion_prompt="Smooth orbit camera around interactive dashboard",
            duration_seconds=7.0,
            choices=[
                ScenarioChoice(
                    choice_id="choice_debrief_opt",
                    label="Complete Mastery Incident Debrief",
                    target_node_id="node_final_debrief",
                    competency_score=20,
                    feedback_rationale="Flawless scenario navigation meeting Tier-1 operational benchmarks."
                )
            ],
            is_terminal=False,
        )

        # Branch C outcome: Passive Monitor (Failure / Remediation)
        monitor_node = ScenarioNode(
            node_id="node_monitor_failure",
            title="Escalation Breach - Remediation Required",
            category=NodeCategoryEnum.REMEDIATION,
            presenter_persona=presenter_persona,
            narration=(
                "Critical failure: delaying action allowed the anomaly to cascade into settlement reconciliation. "
                "Our risk exposure exceeded compliance thresholds by three hundred percent. "
                "Review the mandatory corrective remediation guidelines before proceeding."
            ),
            visual_prompt=(
                "Dark corporate crisis control room, blinking red alarm indicators, stressed atmosphere, "
                "financial charts with deep downward trajectories and breach warnings"
            ),
            motion_prompt="Sudden dramatic crash zoom into incident report screen",
            duration_seconds=7.5,
            choices=[
                ScenarioChoice(
                    choice_id="choice_retry",
                    label="Mandatory Review & Retry Incident",
                    target_node_id="node_root",
                    competency_score=10,
                    feedback_rationale="Allows learner to review fundamental response doctrines and select a safe branch."
                ),
                ScenarioChoice(
                    choice_id="choice_debrief_fail",
                    label="Acknowledge Non-Compliance & View Audit Log",
                    target_node_id="node_final_debrief",
                    competency_score=0,
                    feedback_rationale="Concludes simulation with recorded compliance remediation deficit."
                ),
            ],
            is_terminal=False,
        )

        # Terminal Debrief Node
        debrief_node = ScenarioNode(
            node_id="node_final_debrief",
            title="Post-Incident Audit & Certification Summary",
            category=NodeCategoryEnum.DEBRIEF,
            presenter_persona=presenter_persona,
            narration=(
                "This concludes our high-stakes incident simulation. "
                "Your strategic decisions, response latency, and compliance scores have been logged "
                "to the audit record. Review your performance breakdown below."
            ),
            visual_prompt=(
                "Sleek architectural modern conference suite with floor-to-ceiling glass windows, "
                "sunrise lighting over corporate skyline, digital certification badge illuminated on glass screen"
            ),
            motion_prompt="Slow elegant crane shot upward toward bright horizon",
            duration_seconds=6.0,
            choices=[],
            is_terminal=True,
        )

        nodes: Dict[str, ScenarioNode] = {
            root_node.node_id: root_node,
            halt_node.node_id: halt_node,
            divert_node.node_id: divert_node,
            monitor_node.node_id: monitor_node,
            debrief_node.node_id: debrief_node,
        }

        dag = ScenarioDAGContract(
            scenario_id=scenario_id,
            title=f"Simulation: {clean_topic[:50]}",
            domain=domain,
            root_node_id=root_node.node_id,
            nodes=nodes,
            passing_score=75,
            metadata={
                "depth": depth,
                "total_nodes": len(nodes),
                "created_by": "ScenarioOrchestrator",
                "presenter_persona": presenter_persona,
            }
        )

        validation_errors = dag.validate_graph_integrity()
        if validation_errors:
            raise ValueError(f"Scenario DAG validation failed: {'; '.join(validation_errors)}")

        return dag
