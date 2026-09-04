import unittest
from src.contracts.scenario_contract import (
    ScenarioDAGContract,
    ScenarioNode,
    ScenarioChoice,
    NodeCategoryEnum,
)
from src.scenario_orchestrator import ScenarioOrchestrator


class TestScenarioOrchestrator(unittest.TestCase):
    def setUp(self):
        self.orchestrator = ScenarioOrchestrator()

    def test_generate_scenario_dag_integrity(self):
        dag = self.orchestrator.generate_scenario_dag(
            topic="FinTech Flash Crash Prevention",
            presenter_persona="srinivas_cloud"
        )
        self.assertIsInstance(dag, ScenarioDAGContract)
        self.assertEqual(dag.root_node_id, "node_root")
        self.assertIn("node_root", dag.nodes)
        self.assertGreaterEqual(len(dag.nodes), 4)

        # Validate graph integrity passes without errors
        errors = dag.validate_graph_integrity()
        self.assertEqual(errors, [])

        # Verify terminal node has no outgoing choices
        terminal_nodes = [n for n in dag.nodes.values() if n.is_terminal]
        self.assertGreaterEqual(len(terminal_nodes), 1)
        for tn in terminal_nodes:
            self.assertEqual(len(tn.choices), 0)

    def test_graph_validation_catches_missing_targets(self):
        bad_node = ScenarioNode(
            node_id="node_root",
            title="Root Dilemma",
            category=NodeCategoryEnum.ROOT_DILEMMA,
            narration="Test dilemma",
            visual_prompt="Test visual",
            choices=[
                ScenarioChoice(
                    choice_id="bad_choice",
                    label="Points nowhere",
                    target_node_id="node_ghost",
                    feedback_rationale="Broken target"
                )
            ]
        )
        bad_dag = ScenarioDAGContract(
            scenario_id="sim_bad",
            title="Broken DAG",
            root_node_id="node_root",
            nodes={"node_root": bad_node}
        )
        errors = bad_dag.validate_graph_integrity()
        self.assertTrue(any("node_ghost" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
