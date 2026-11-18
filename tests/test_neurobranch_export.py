import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
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

            # Manifest must be well-formed XML with the adlcp namespace declared
            root = ET.fromstring(zf.read("imsmanifest.xml"))
            ns = {"ims": "http://www.imsproject.org/xsd/imscp_rootv1p1p2"}
            self.assertIsNotNone(root.find("ims:organizations/ims:organization/ims:item", ns))

        # Cleanup
        if zip_path.exists():
            zip_path.unlink()

    def test_manifest_escapes_special_characters(self):
        dag = self.orchestrator.generate_scenario_dag(
            topic="Risk & Return <Basics>",
            presenter_persona="srinivas_cloud"
        )
        dag = dag.model_copy(update={"title": 'Risk & Return <Basics> "Q1"'})
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = self.packager.export_scenario_zip(dag, output_zip_path=Path(tmp) / "sim.zip")
            with zipfile.ZipFile(zip_path, "r") as zf:
                root = ET.fromstring(zf.read("imsmanifest.xml"))
        titles = [el.text for el in root.iter() if el.tag.endswith("title")]
        self.assertIn('Risk & Return <Basics> "Q1"', titles)


if __name__ == "__main__":
    unittest.main()
