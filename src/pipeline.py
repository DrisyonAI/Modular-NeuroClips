import gc
import time
import subprocess
import urllib.request
import urllib.parse
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from src.config import OUTPUT_DIR, DEVICE, T2I_MODEL, I2V_MODEL

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    torch = None
    TORCH_AVAILABLE = False

try:
    from diffusers import AutoPipelineForText2Image, CogVideoXImageToVideoPipeline
    from diffusers.utils import export_to_video
    DIFFUSERS_AVAILABLE = True
except ImportError:
    DIFFUSERS_AVAILABLE = False

class VRAMGuard:
    @staticmethod
    def cleanup():
        gc.collect()
        if TORCH_AVAILABLE and torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            except Exception:
                pass

class MediaGenerationEngine:
    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.device = DEVICE if (TORCH_AVAILABLE and torch.cuda.is_available()) else "cpu"
        self.dtype = (torch.float16 if self.device == "cuda" else torch.float32) if TORCH_AVAILABLE else None

    def _fetch_cloud_ai_image(self, prompt: str, image_path: Path, width: int = 1280, height: int = 720) -> bool:
        """Fetches real AI synthesized image matching the prompt from Pollinations Flux/Turbo API."""
        clean_prompt = prompt.strip()[:350]
        encoded_prompt = urllib.parse.quote(clean_prompt)
        seed_val = random.randint(10000, 999999)
        
        endpoints = [
            f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&model=flux&nologo=true&seed={seed_val}",
            f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&model=turbo&nologo=true&seed={seed_val}"
        ]
        
        for url in endpoints:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
                    }
                )
                with urllib.request.urlopen(req, timeout=25) as response:
                    if response.status == 200:
                        content = response.read()
                        if len(content) > 3000:
                            with open(image_path, "wb") as f:
                                f.write(content)
                            print(f"[Cloud AI Image] Generated ({width}x{height}) for visual prompt: '{clean_prompt[:50]}...'")
                            return True
            except Exception as e:
                print(f"[Cloud AI Notice] Endpoint retry: {e}")
                time.sleep(0.5)
        return False

    def generate_image_keyframe(self, prompt: str, scene_id: int, job_id: str = "fresh", width: int = 1280, height: int = 720, force_refresh: bool = True, max_retries: int = 3) -> str:
        """Generates keyframe image strictly matching the prompt and scene context."""
        image_path = self.output_dir / f"scene_{scene_id}_{job_id}_keyframe.png"
        if not force_refresh and image_path.exists() and image_path.stat().st_size > 1000:
            return str(image_path)

        # 1. Try local Stable Diffusion GPU
        if DIFFUSERS_AVAILABLE and TORCH_AVAILABLE and torch.cuda.is_available():
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

                    image = pipe(
                        prompt=prompt,
                        width=min(width, 768),
                        height=min(height, 512),
                        num_inference_steps=20,
                        guidance_scale=6.5
                    ).images[0]
                    
                    if width != image.width or height != image.height:
                        image = image.resize((width, height), Image.Resampling.LANCZOS)
                        
                    image.save(image_path)
                    return str(image_path)
                except Exception as e:
                    print(f"[Keyframe Warning] GPU generation attempt {attempt} failed: {e}")
                    VRAMGuard.cleanup()
                    time.sleep(1)
                finally:
                    if pipe is not None:
                        del pipe
                    VRAMGuard.cleanup()

        # 2. Try High-Quality Cloud AI Synthesis (Pollinations Flux / SDXL)
        if self._fetch_cloud_ai_image(prompt, image_path, width=width, height=height):
            return str(image_path)

        # 3. Procedural Fallback Card
        img = Image.new("RGB", (width, height), color=(15, 23, 42))
        draw = ImageDraw.Draw(img)
        
        for y in range(height):
            r = int(15 + (y / height) * 20)
            g = int(23 + (y / height) * 45)
            b = int(42 + (y / height) * 90)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        draw.rectangle([(20, 20), (width - 20, height - 20)], outline=(56, 189, 248), width=2)
        draw.rectangle([(30, 30), (width - 30, 70)], fill=(2, 132, 199))
        draw.text((40, 42), f"MODULAR-NEUROCLIPS | SCENE #{scene_id} ({width}x{height})", fill=(255, 255, 255))
        
        words = prompt.split()
        lines = []
        cur_line = []
        for w in words:
            if len(" ".join(cur_line + [w])) > 55:
                lines.append(" ".join(cur_line))
                cur_line = [w]
            else:
                cur_line.append(w)
        if cur_line:
            lines.append(" ".join(cur_line))

        y_offset = 95
        for line in lines[:6]:
            draw.text((40, y_offset), line, fill=(226, 232, 240))
            y_offset += 26

        img.save(image_path)
        return str(image_path)

    def generate_video_clip(self, image_path: str, motion_prompt: str, scene_id: int, job_id: str = "fresh", width: int = 1280, height: int = 720, force_refresh: bool = True, max_retries: int = 3) -> str:
        """Generates video clip using CogVideoX or FFmpeg Smooth Ken Burns Zoom."""
        clip_path = self.output_dir / f"scene_{scene_id}_{job_id}_clip.mp4"
        if not force_refresh and clip_path.exists() and clip_path.stat().st_size > 1000:
            return str(clip_path)

        if DIFFUSERS_AVAILABLE and TORCH_AVAILABLE and torch.cuda.is_available():
            for attempt in range(1, max_retries + 1):
                pipe = None
                try:
                    VRAMGuard.cleanup()
                    init_image = Image.open(image_path).convert("RGB").resize((width, height))

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
                        num_inference_steps=20,
                        use_dynamic_cfg=True
                    ).frames[0]

                    export_to_video(video_frames, str(clip_path), fps=8)
                    return str(clip_path)
                except Exception as e:
                    print(f"[Render Warning] Neural motion attempt {attempt} failed: {e}")
                    VRAMGuard.cleanup()
                    time.sleep(1)
                finally:
                    if pipe is not None:
                        del pipe
                    VRAMGuard.cleanup()

        try:
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(image_path),
                "-vf", f"zoompan=z='min(zoom+0.0012,1.20)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=100:s={width}x{height}",
                "-t", "4",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "ultrafast",
                str(clip_path)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return str(clip_path)
        except Exception:
            try:
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", str(image_path),
                    "-t", "4",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    str(clip_path)
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return str(clip_path)
            except Exception:
                with open(image_path, "rb") as f_in, open(clip_path, "wb") as f_out:
                    f_out.write(f_in.read())
                return str(clip_path)
