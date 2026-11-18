"""
Modular-NeuroClips Studio - Command Line Production Runner.
Executes the full AI video generation pipeline from CLI:
  1. Script generation via ScriptOrchestrator (Ollama / Llama 3)
  2. Keyframe image rendering via MediaGenerationEngine
  3. Video clip motion synthesis
  4. FFmpeg stitching & compilation
"""
import sys
import time
import argparse
from src.orchestrator import ScriptOrchestrator
from src.pipeline import MediaGenerationEngine
from src.compiler import compile_final_video
from src.dashboard import PIPELINE_STATE

def run_pipeline(topic: str, scene_count: int = 3):
    engine = MediaGenerationEngine()
    orchestrator = ScriptOrchestrator()

    PIPELINE_STATE["status"] = "Generating Script"
    PIPELINE_STATE["current_step"] = "Prompting Llama 3 via Ollama"
    
    t0 = time.time()
    script = orchestrator.generate_script(topic=topic, scene_count=scene_count)
    PIPELINE_STATE["model_load_latency"] = time.time() - t0
    PIPELINE_STATE["total_scenes"] = len(script.scenes)
    print(f"[*] Generated script with {len(script.scenes)} scenes. Art style: {script.art_style_preset}")

    clip_paths = []
    for idx, scene in enumerate(script.scenes, start=1):
        PIPELINE_STATE["processed_scenes"] = idx
        full_image_prompt = f"{script.art_style_preset}, {scene.visual_prompt}"

        # 1. Generate Keyframe
        PIPELINE_STATE["status"] = f"Rendering Scene {idx}/{len(script.scenes)}"
        PIPELINE_STATE["current_step"] = "Keyframe Generation"
        print(f"[*] Generating keyframe for Scene {idx}...")
        keyframe_path = engine.generate_image_keyframe(full_image_prompt, scene.scene_id)

        # 2. Render Video Clip
        PIPELINE_STATE["current_step"] = "Video Animation"
        print(f"[*] Rendering video clip for Scene {idx}...")
        clip_path = engine.generate_video_clip(keyframe_path, scene.motion_prompt, scene.scene_id)
        clip_paths.append(clip_path)

    # 3. Stitch Video
    PIPELINE_STATE["status"] = "Compiling Video"
    PIPELINE_STATE["current_step"] = "FFmpeg Concatenation"
    output_path = compile_final_video(clip_paths)

    PIPELINE_STATE["status"] = "Complete"
    PIPELINE_STATE["current_step"] = f"Saved: {output_path}"
    print(f"\n[+] Production ready: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Video Generation Orchestrator")
    parser.add_argument("--topic", type=str, required=True, help="Concept prompt for video generation")
    parser.add_argument("--scenes", type=int, default=3, help="Number of scenes to generate")
    args = parser.parse_args()

    run_pipeline(topic=args.topic, scene_count=args.scenes)