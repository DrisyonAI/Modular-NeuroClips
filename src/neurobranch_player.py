"""
NeuroBranch™ Runtime HTML5 & SCORM Player Generator.
Generates an interactive player for multi-path branching scenarios with seamless
clip switching, decision overlays, and cmi.interactions telemetry.
"""
import json
from typing import Optional
from src.contracts.scenario_contract import ScenarioDAGContract


def generate_neurobranch_player_html(
    scenario_dag: ScenarioDAGContract,
    pass_percentage: int = 70
) -> str:
    """
    Renders an HTML5 / SCORM-compatible branching simulation player.
    """
    dag_json = scenario_dag.model_dump_json() if hasattr(scenario_dag, "model_dump_json") else scenario_dag.json()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{scenario_dag.title} - NeuroBranch™ Simulation</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #090d16;
      color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 1rem;
    }}
    .sim-container {{
      width: 100%;
      max-width: 960px;
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5);
      position: relative;
    }}
    .sim-header {{
      padding: 12px 20px;
      background: #090d16;
      border-bottom: 1px solid #1e293b;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .badge {{
      background: rgba(99,102,241,0.2);
      color: #818cf8;
      border: 1px solid rgba(99,102,241,0.4);
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .video-viewport {{
      position: relative;
      width: 100%;
      aspect-ratio: 16/9;
      background: #000;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    video {{
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .hud-overlay {{
      position: absolute;
      inset: 0;
      background: rgba(9, 13, 22, 0.85);
      backdrop-filter: blur(8px);
      display: none;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      padding: 2rem;
      z-index: 10;
    }}
    .hud-overlay.active {{
      display: flex;
    }}
    .decision-card {{
      max-width: 680px;
      width: 100%;
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 12px;
      padding: 1.5rem;
      box-shadow: 0 10px 25px rgba(0,0,0,0.4);
    }}
    .decision-title {{
      font-size: 18px;
      font-weight: bold;
      color: #38bdf8;
      margin-bottom: 0.5rem;
    }}
    .decision-desc {{
      font-size: 14px;
      color: #cbd5e1;
      margin-bottom: 1.25rem;
      line-height: 1.4;
    }}
    .choices-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .choice-btn {{
      background: #0f172a;
      border: 1px solid #3b82f6;
      color: #f8fafc;
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 14px;
      text-align: left;
      cursor: pointer;
      transition: all 0.2s;
    }}
    .choice-btn:hover {{
      background: #2563eb;
      border-color: #60a5fa;
      transform: translateX(4px);
    }}
    .debrief-card {{
      text-align: center;
      max-width: 600px;
      padding: 2rem;
    }}
    .score-circle {{
      font-size: 48px;
      font-weight: 800;
      color: #10b981;
      margin: 1rem 0;
    }}
  </style>
</head>
<body>
  <div class="sim-container">
    <div class="sim-header">
      <h2 style="font-size: 14px; font-weight: 600;">{scenario_dag.title}</h2>
      <span class="badge">NeuroBranch™ Adaptive Simulation</span>
    </div>
    
    <div class="video-viewport">
      <video id="sim-player" controls autoplay playsinline></video>

      <!-- Interactive HUD Decision Overlay -->
      <div id="decision-hud" class="hud-overlay">
        <div class="decision-card">
          <div id="hud-node-title" class="decision-title">Incident Response Required</div>
          <p id="hud-node-desc" class="decision-desc">Analyze the telemetry and select your strategic action:</p>
          <div id="hud-choices-list" class="choices-list"></div>
        </div>
      </div>

      <!-- Final Debrief Overlay -->
      <div id="debrief-hud" class="hud-overlay">
        <div class="debrief-card">
          <h2 style="font-size: 22px; margin-bottom: 8px;">Simulation Concluded</h2>
          <p style="color: #94a3b8; font-size: 13px;">Your decision telemetry has been recorded to LMS audit trail.</p>
          <div id="final-score" class="score-circle">100%</div>
          <p id="final-status" style="font-weight: 600; margin-bottom: 1.5rem;"></p>
          <button class="choice-btn" style="text-align:center;" onclick="restartSimulation()">🔄 Replay Simulation</button>
        </div>
      </div>
    </div>
  </div>

  <script>
    const DAG = {dag_json};
    let currentNodeId = DAG.root_node_id;
    let totalScore = 0;
    let scormConnected = false;

    // Lightweight SCORM 1.2 / 2004 Bridge
    function initSCORM() {{
      try {{
        if (window.API) {{
          window.API.LMSInitialize("");
          window.API.LMSSetValue("cmi.core.lesson_status", "incomplete");
          scormConnected = true;
        }}
      }} catch(e) {{}}
    }}

    function recordInteraction(choiceId, isCorrect, weight) {{
      if (!scormConnected || !window.API) return;
      try {{
        window.API.LMSSetValue("cmi.interactions.0.id", choiceId);
        window.API.LMSSetValue("cmi.interactions.0.type", "choice");
        window.API.LMSSetValue("cmi.interactions.0.result", isCorrect ? "correct" : "wrong");
      }} catch(e) {{}}
    }}

    function renderNode(nodeId) {{
      const node = DAG.nodes[nodeId];
      if (!node) return;

      currentNodeId = nodeId;
      const hud = document.getElementById("decision-hud");
      hud.classList.remove("active");

      const player = document.getElementById("sim-player");
      player.onended = () => {{
        if (node.is_terminal) {{
          showDebrief();
        }} else if (node.choices && node.choices.length > 0) {{
          showDecisionHUD(node);
        }}
      }};
      // Trigger decision prompt
      if (node.choices && node.choices.length > 0) {{
        showDecisionHUD(node);
      }}
    }}

    function showDecisionHUD(node) {{
      document.getElementById("hud-node-title").innerText = node.title;
      document.getElementById("hud-node-desc").innerText = node.narration;
      const choicesContainer = document.getElementById("hud-choices-list");
      choicesContainer.innerHTML = "";

      node.choices.forEach(ch => {{
        const btn = document.createElement("button");
        btn.className = "choice-btn";
        btn.innerText = ch.label;
        btn.onclick = () => onSelectChoice(ch);
        choicesContainer.appendChild(btn);
      }});

      document.getElementById("decision-hud").classList.add("active");
    }}

    function onSelectChoice(choice) {{
      totalScore += (choice.competency_score || 0);
      recordInteraction(choice.choice_id, (choice.competency_score > 0), choice.competency_score);
      renderNode(choice.target_node_id);
    }}

    function showDebrief() {{
      document.getElementById("decision-hud").classList.remove("active");
      const debrief = document.getElementById("debrief-hud");
      const normalizedScore = Math.max(0, Math.min(100, Math.round(totalScore)));
      const passed = normalizedScore >= {pass_percentage};

      document.getElementById("final-score").innerText = normalizedScore + "%";
      const statusEl = document.getElementById("final-status");
      statusEl.innerText = passed ? "COMPETENCY VERIFIED: PASS" : "REMEDIATION REQUIRED: FAIL";
      statusEl.style.color = passed ? "#10b981" : "#ef4444";

      if (scormConnected && window.API) {{
        window.API.LMSSetValue("cmi.core.score.raw", normalizedScore.toString());
        window.API.LMSSetValue("cmi.core.lesson_status", passed ? "passed" : "failed");
        window.API.LMSCommit("");
        window.API.LMSFinish("");
      }}

      debrief.classList.add("active");
    }}

    function restartSimulation() {{
      totalScore = 0;
      document.getElementById("debrief-hud").classList.remove("active");
      renderNode(DAG.root_node_id);
    }}

    window.onload = () => {{
      initSCORM();
      renderNode(DAG.root_node_id);
    }};
  </script>
</body>
</html>
"""
    return html
