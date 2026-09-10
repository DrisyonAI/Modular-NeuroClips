import unittest
import zipfile
from pathlib import Path
from src.scenario_orchestrator import ScenarioOrchestrator
from src.scorm_packager import SCORMPackager
from src.config import EXPORTS_DIR


class TestNeuroBranchSCORMExport(unittest.TestCase):
    def setUp(self):
        self.orchestrator = ScenarioOrchestrator()
        self.packager = SCORMPackager(course_id="test_sim_course", course_title="Simulation Course")

    def test_export_scenario_zip(self):
        dag = self.orchestrator.generate_scenario_dag(
            topic="High Frequency Algorithmic Containment",
            presenter_persona="srinivas_cloud"
        )
        zip_path = self.packager.export_scenario_zip(dag)

        self.assertTrue(zip_path.exists())
        self.assertTrue(zip_path.stat().st_size > 500)

        # Inspect zip contents
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            self.assertIn("imsmanifest.xml", namelist)
            self.assertIn("index.html", namelist)

            # Check that player contains DAG data
            html_content = zf.read("index.html").decode("utf-8")
            self.assertIn("NeuroBranch™ Simulation", html_content)
            self.assertIn(dag.title, html_content)
            self.assertIn("cmi.interactions", html_content)

        # Cleanup
        if zip_path.exists():
            zip_path.unlink()


if __name__ == "__main__":
    unittest.main()
