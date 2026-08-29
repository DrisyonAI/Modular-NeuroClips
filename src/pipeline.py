import gc
import time
import torch
from pathlib import Path
from PIL import Image
from diffusers import AutoPipelineForText2Image, CogVideoXImageToVideoPipeline
from diffusers.utils import export_to_video
from src.config import OUTPUT_DIR, DEVICE, T2I_MODEL, I2V_MODEL, RENDER_WIDTH, RENDER_HEIGHT

class VRAMGuard:
    @staticmethod
    def cleanup():
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

class MediaGenerationEngine:
    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir
        self.device = DEVICE if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if torch.cuda.is_available() else torch.float32

    def generate_image_keyframe(self, prompt: str, scene_id: int, max_retries: int = 3) -> str:
        """Generates a standard-definition keyframe (576x320 / 512x512)."""
        image_path = self.output_dir / f"scene_{scene_id}_keyframe.png"
        if image_path.exists():
            return str(image_path)

        for attempt in range(1, max_retries + 1):
            pipe = None
            try:
                VRAMGuard.cleanup()
                pipe = AutoPipelineForText2Image.from_pretrained(
                    T2I_MODEL,
                    torch_dtype=self.dtype,
                    safety_checker=None
                ).to(self.device)

                if hasattr(pipe, "enable_model_cpu_offload"):
                    pipe.enable_model_cpu_offload()

                # Low-res fast generation (20 steps)
                image = pipe(
                    prompt=prompt,
                    width=RENDER_WIDTH,
                    height=RENDER_HEIGHT,
                    num_inference_steps=20,
                    guidance_scale=6.5
                ).images[0]
                
                image.save(image_path)
                return str(image_path)
            except Exception as e:
                print(f"[Keyframe Error] Scene {scene_id} Attempt {attempt} failed: {e}")
                VRAMGuard.cleanup()
                time.sleep(2 ** attempt)
                if attempt == max_retries:
                    raise RuntimeError(f"Failed keyframe generation for Scene {scene_id}")
            finally:
                if pipe is not None:
                    del pipe
                VRAMGuard.cleanup()

    def generate_video_clip(self, image_path: str, motion_prompt: str, scene_id: int, max_retries: int = 3) -> str:
        """Generates standard-definition video animation."""
        clip_path = self.output_dir / f"scene_{scene_id}_clip.mp4"
        if clip_path.exists():
            return str(clip_path)

        for attempt in range(1, max_retries + 1):
            pipe = None
            try:
                VRAMGuard.cleanup()
                init_image = Image.open(image_path).convert("RGB").resize((RENDER_WIDTH, RENDER_HEIGHT))

                pipe = CogVideoXImageToVideoPipeline.from_pretrained(
                    I2V_MODEL,
                    torch_dtype=torch.float16
                )
                pipe.enable_sequential_cpu_offload()
                pipe.vae.enable_tiling()
                pipe.vae.enable_slicing()

                video_frames = pipe(
                    prompt=motion_prompt,
                    image=init_image,
                    num_videos_per_prompt=1,
                    num_inference_steps=20, # Reduced steps for rapid generation
                    use_dynamic_cfg=True
                ).frames[0]

                export_to_video(video_frames, str(clip_path), fps=8)
                return str(clip_path)
            except Exception as e:
                print(f"[Render Error] Scene {scene_id} Attempt {attempt} failed: {e}")
                VRAMGuard.cleanup()
                time.sleep(2 ** attempt)
                if attempt == max_retries:
                    raise RuntimeError(f"Video clip generation failed for Scene {scene_id}")
            finally:
                if pipe is not None:
                    del pipe
                VRAMGuard.cleanup()