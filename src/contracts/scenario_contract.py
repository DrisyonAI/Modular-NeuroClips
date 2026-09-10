"""
NeuroBranch™ Scenario & Adaptive Decision Graph Contracts.
Defines schema for non-linear, branching micro-simulations, decision nodes,
and contextual consequences for interactive learning & SCORM/xAPI packaging.
"""
from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class NodeCategoryEnum(str, Enum):
    ROOT_DILEMMA = "root_dilemma"
    DECISION_POINT = "decision_point"
    CONSEQUENCE = "consequence"
    REMEDIATION = "remediation"
    DEBRIEF = "debrief"


class ScenarioChoice(BaseModel):
    """
    Learner selectable option at a decision point.
    """
    choice_id: str = Field(..., description="Unique branch ID, e.g. 'choice_a'")
    label: str = Field(..., description="Text displayed on the interactive HUD choice card")
    target_node_id: str = Field(..., description="The scenario node triggered when this choice is selected")
    competency_score: int = Field(default=0, description="Score delta or competency weight (-100 to +100)")
    feedback_rationale: str = Field(..., description="Immediate instructional feedback rationale explaining consequences")


class ScenarioNode(BaseModel):
    """
    A single interactive narrative block within the branching scenario DAG.
    """
    node_id: str = Field(..., description="Unique node identifier, e.g. 'node_root', 'node_escalate'")
    title: str = Field(..., description="Node title, e.g. 'High Frequency Risk Spike'")
    category: NodeCategoryEnum = Field(default=NodeCategoryEnum.DECISION_POINT)
    presenter_persona: str = Field(default="srinivas_cloud", description="Avatar presenter persona key")
    narration: str = Field(..., description="Spoken dialogue/script delivered by the avatar")
    visual_prompt: str = Field(..., description="Detailed visual prompt for scene synthesis")
    motion_prompt: str = Field(default="Slow cinematic tracking shot", description="Camera motion prompt")
    duration_seconds: float = Field(default=6.0, description="Estimated duration in seconds")
    choices: List[ScenarioChoice] = Field(default_factory=list, description="Choices presented at the end of this clip")
    is_terminal: bool = Field(default=False, description="True if this node concludes the simulation")


class ScenarioDAGContract(BaseModel):
    """
    Complete non-linear scenario decision tree.
    """
    scenario_id: str
    title: str
    domain: str = Field(default="FinTech & Enterprise Risk", description="Subject matter domain")
    root_node_id: str = Field(default="node_root")
    nodes: Dict[str, ScenarioNode] = Field(..., description="Mapping of node_id to ScenarioNode")
    passing_score: int = Field(default=70, description="Passing competency threshold percentage")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def validate_graph_integrity(self) -> List[str]:
        """
        Validates that all target_node_ids exist and the root node is present.
        Returns a list of error strings if invalid.
        """
        errors = []
        if self.root_node_id not in self.nodes:
            errors.append(f"Root node '{self.root_node_id}' not found in scenario nodes.")
        for nid, node in self.nodes.items():
            for ch in node.choices:
                if ch.target_node_id not in self.nodes:
                    errors.append(f"Node '{nid}' choice '{ch.choice_id}' targets non-existent node '{ch.target_node_id}'.")
        return errors
