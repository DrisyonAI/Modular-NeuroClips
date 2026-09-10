import gc
import time
import subprocess
import urllib.request
import urllib.parse
import random
from pathlib import Path
from typing import Optional
from src.config import OUTPUT_DIR, DEVICE, T2I_MODEL, I2V_MODEL, get_resolution_dimensions

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    Image = ImageDraw = ImageFont = None
    PIL_AVAILABLE = False

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
        self._create_placeholder_image(
            prompt=prompt,
            output_path=image_path,
            resolution=f"{width}x{height}",
            title=f"MODULAR-NEUROCLIPS | SCENE #{scene_id} ({width}x{height})"
        )
        return str(image_path)

    def _create_placeholder_image(
        self,
        prompt: str,
        output_path: Path,
        resolution: str = "16:9_hd",
        title: Optional[str] = None
    ) -> bool:
        """Generates a styled visual placeholder card when neural synthesis is unavailable."""
        width, height = get_resolution_dimensions(resolution)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not PIL_AVAILABLE:
            return False

        try:
            img = Image.new("RGB", (width, height), color=(15, 23, 42))
            draw = ImageDraw.Draw(img)

            for y in range(height):
                r = int(15 + (y / height) * 20)
                g = int(23 + (y / height) * 45)
                b = int(42 + (y / height) * 90)
                draw.line([(0, y), (width, y)], fill=(r, g, b))

            draw.rectangle([(20, 20), (width - 20, height - 20)], outline=(56, 189, 248), width=2)
            draw.rectangle([(30, 30), (width - 30, 70)], fill=(2, 132, 199))
            card_title = title or f"MODULAR-NEUROCLIPS ({width}x{height})"
            draw.text((40, 42), card_title, fill=(255, 255, 255))

            words = prompt.split()
            lines = []
            cur_line = []
            max_chars = max(30, width // 22)
            for w in words:
                if len(" ".join(cur_line + [w])) > max_chars:
                    lines.append(" ".join(cur_line))
                    cur_line = [w]
                else:
                    cur_line.append(w)
            if cur_line:
                lines.append(" ".join(cur_line))

            y_offset = 95
            for line in lines[:8]:
                draw.text((40, y_offset), line, fill=(226, 232, 240))
                y_offset += 26

            img.save(output_path)
            return output_path.exists() and output_path.stat().st_size > 500
        except Exception as exc:
            print(f"[Placeholder Image Warning] {exc}")
            return False

    def generate_image(
        self,
        prompt: str,
        output_path: Path,
        resolution: str = "16:9_hd",
        force_refresh: bool = True
    ) -> bool:
        """
        Unified image generation method called by ImageGeneratorAgent and studios.
        Resolves resolution, tries local GPU SD, cloud AI, and falls back to placeholder card.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not force_refresh and output_path.exists() and output_path.stat().st_size > 1000:
            return True

        width, height = get_resolution_dimensions(resolution)

        # 1. Try local Stable Diffusion GPU
        if DIFFUSERS_AVAILABLE and TORCH_AVAILABLE and torch.cuda.is_available():
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

                image.save(output_path)
                return True
            except Exception as e:
                print(f"[generate_image Warning] GPU failed: {e}")
            finally:
                if pipe is not None:
                    del pipe
                VRAMGuard.cleanup()

        # 2. Try High-Quality Cloud AI Synthesis (Pollinations Flux / SDXL)
        if self._fetch_cloud_ai_image(prompt, output_path, width=width, height=height):
            return True

        # 3. Procedural Fallback Card
        return self._create_placeholder_image(prompt, output_path, resolution=resolution)

    def generate_instructional_slide(
        self,
        title: str,
        content: str,
        output_path: Path,
        resolution: str = "16:9_hd",
        subtitle: Optional[str] = None,
        badge_text: Optional[str] = None
    ) -> bool:
        """
        Generates a high-contrast, professional instructional slide card for education/course content.
        Designed as a clean background for an avatar presenter to narrate concepts, frameworks, and diagrams.
        """
        width, height = get_resolution_dimensions(resolution)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not PIL_AVAILABLE:
            return False

        try:
            # Elegant deep slate-blue background
            img = Image.new("RGB", (width, height), color=(11, 15, 25))
            draw = ImageDraw.Draw(img)

            # Subtle corporate gradient
            for y in range(height):
                r = int(11 + (y / height) * 12)
                g = int(15 + (y / height) * 20)
                b = int(25 + (y / height) * 45)
                draw.line([(0, y), (width, y)], fill=(r, g, b))

            # Outer border with accent glow
            pad = max(16, int(min(width, height) * 0.03))
            draw.rectangle([(pad, pad), (width - pad, height - pad)], outline=(30, 58, 138), width=2)

            # Slide Header Banner
            header_h = max(48, int(height * 0.12))
            draw.rectangle([(pad + 2, pad + 2), (width - pad - 2, pad + header_h)], fill=(15, 23, 42))
            draw.line([(pad + 2, pad + header_h), (width - pad - 2, pad + header_h)], fill=(56, 189, 248), width=2)

            # Category pill tag
            pill_text = (badge_text or subtitle or "INSTRUCTIONAL SLIDE  |  CORE CONCEPT").upper()
            draw.text((pad + 16, pad + 10), pill_text, fill=(56, 189, 248))

            # Slide Title
            clean_title = (title or "Instructional Module").upper()
            if len(clean_title) > 60:
                clean_title = clean_title[:57] + "..."
            draw.text((pad + 16, pad + 28), clean_title, fill=(255, 255, 255))

            # Content Bullet Points
            raw_lines = [c.strip() for c in content.replace("\r", "").split("\n") if c.strip()]
            if not raw_lines or len(raw_lines) == 1:
                sentences = [s.strip() for s in content.replace(". ", ".\n").split("\n") if s.strip()]
                raw_lines = sentences[:6] if sentences else ["Key Concept Analysis"]

            y_pos = pad + header_h + max(24, int(height * 0.05))
            line_height = max(26, int(height * 0.07))
            max_chars = max(35, int(width / 16))

            for item in raw_lines[:6]:
                # Draw bullet marker
                draw.rectangle([(pad + 20, y_pos + 4), (pad + 28, y_pos + 12)], fill=(14, 165, 233))
                words = item.split()
                line_acc = []
                for w in words:
                    if len(" ".join(line_acc + [w])) > max_chars:
                        draw.text((pad + 40, y_pos), " ".join(line_acc), fill=(241, 245, 249))
                        y_pos += int(line_height * 0.85)
                        line_acc = [w]
                    else:
                        line_acc.append(w)
                if line_acc:
                    draw.text((pad + 40, y_pos), " ".join(line_acc), fill=(241, 245, 249))
                    y_pos += line_height

            # Bottom status banner
            draw.line([(pad, height - pad - 28), (width - pad, height - pad - 28)], fill=(30, 41, 59), width=1)
            draw.text((pad + 16, height - pad - 22), "MODULAR-NEUROCLIPS ACADEMY", fill=(100, 116, 139))

            img.save(output_path)
            return output_path.exists() and output_path.stat().st_size > 500
        except Exception as exc:
            print(f"[Instructional Slide Warning] {exc}")
            return False

    def generate_video(
        self,
        image_path: Path,
        motion_prompt: str,
        output_path: Path,
        duration_sec: int = 5,
        resolution: str = "16:9_hd",
        motion_graphics: bool = True
    ) -> bool:
        """
        Unified video motion generator called by DirectorAgent and studios.
        Uses CogVideoX or FFmpeg Smooth Ken Burns Zoom to generate duration-matched video.
        If motion_graphics is False, generates a clean static frame video.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = get_resolution_dimensions(resolution)
        dur_str = str(max(1, duration_sec))

        # Static video loop if motion graphics is disabled
        if not motion_graphics:
            try:
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", str(Path(image_path).resolve()),
                    "-t", dur_str,
                    "-vf", f"scale={width}:{height}",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "ultrafast",
                    str(output_path)
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 500
            except Exception:
                return False

        # 1. Try CogVideoX if GPU is available
        if DIFFUSERS_AVAILABLE and TORCH_AVAILABLE and torch.cuda.is_available():
            pipe = None
            try:
                VRAMGuard.cleanup()
                init_image = Image.open(image_path).convert("RGB").resize((width, height))
                pipe = CogVideoXImageToVideoPipeline.from_pretrained(I2V_MODEL, torch_dtype=torch.float16)
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

                export_to_video(video_frames, str(output_path), fps=8)
                return output_path.exists() and output_path.stat().st_size > 1000
            except Exception as e:
                print(f"[generate_video Warning] Neural motion failed: {e}")
            finally:
                if pipe is not None:
                    del pipe
                VRAMGuard.cleanup()

        # 2. Smooth Ken Burns Zoom with FFmpeg
        frames = max(30, int(duration_sec * 25))
        try:
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(Path(image_path).resolve()),
                "-vf", f"zoompan=z='min(zoom+0.0012,1.20)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}",
                "-t", dur_str,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "ultrafast",
                str(output_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 500:
                return True
        except Exception:
            pass

        # 3. Static loop fallback
        try:
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(Path(image_path).resolve()),
                "-t", dur_str,
                "-vf", f"scale={width}:{height}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(output_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 500
        except Exception:
            return False

    def generate_video_clip(
        self,
        image_path: str,
        motion_prompt: str,
        scene_id: int,
        job_id: str = "fresh",
        width: int = 1280,
        height: int = 720,
        force_refresh: bool = True,
        max_retries: int = 3,
        motion_graphics: bool = True,
        duration_sec: float = 4.0
    ) -> str:
        """Generates video clip using CogVideoX or FFmpeg Smooth Ken Burns Zoom, or static loop when motion_graphics=False."""
        clip_path = self.output_dir / f"scene_{scene_id}_{job_id}_clip.mp4"
        if not force_refresh and clip_path.exists() and clip_path.stat().st_size > 1000:
            return str(clip_path)

        dur_str = str(max(1.0, float(duration_sec)))

        if not motion_graphics:
            try:
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", str(image_path),
                    "-t", dur_str,
                    "-vf", f"scale={width}:{height}",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "ultrafast",
                    str(clip_path)
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return str(clip_path)
            except Exception:
                pass

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
            except Exception as e2:
                print(f"[Render Error] All video encoding methods failed for {image_path}: {e2}")
                # Ensure the path exists so downstream steps can proceed with warning
                if not clip_path.exists():
                    clip_path.touch()
                return str(clip_path)

    def extract_video_thumbnail(self, video_path: str, thumbnail_path: Path, width: int = 1280, height: int = 720) -> str:
        """Extracts a frame from an existing video to serve as keyframe preview."""
        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", "00:00:00.5",
                "-i", str(video_path),
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
                "-vframes", "1",
                str(thumbnail_path)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return str(thumbnail_path)
        except Exception:
            img = Image.new("RGB", (width, height), color=(15, 23, 42))
            img.save(thumbnail_path)
            return str(thumbnail_path)

    def prepare_existing_video_clip(
        self,
        input_video_path: str,
        scene_id: int,
        job_id: str = "fresh",
        target_duration: float = 5.0,
        width: int = 1280,
        height: int = 720
    ) -> str:
        """
        Normalizes an uploaded video clip to the studio's exact resolution, aspect ratio,
        and frame rate so it concatenates seamlessly with AI scenes.
        """
        clip_path = self.output_dir / f"scene_{scene_id}_{job_id}_clip.mp4"
        in_p = Path(input_video_path)
        if not in_p.exists():
            from src.config import ASSETS_DIR
            alt_p = ASSETS_DIR / in_p.name
            if alt_p.exists():
                in_p = alt_p

        try:
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", str(in_p.resolve()),
                "-t", str(target_duration),
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,fps=30",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-an",
                str(clip_path)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return str(clip_path)
        except Exception as e:
            print(f"[Video Normalization Warning] ({e}). Performing simple copy fallback.")
            if in_p.exists():
                with open(in_p, "rb") as f_src, open(clip_path, "wb") as f_dst:
                    f_dst.write(f_src.read())
            return str(clip_path)

