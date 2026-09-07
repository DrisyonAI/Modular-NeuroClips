"""
Avatar Animation Service.
Provides audio-reactive speaking avatar video synthesis for:
- 2D Portrait Avatars (with audio-synchronized lip-sync visemes, eye blinks, and natural kinematics)
- 3D Mesh Avatars (with 3D blendshape jaw articulation, 3D spatial rotation, and wireframe/shaded rendering)
- Studio curtain compositing (Green Screen, Clean White, Studio Dark)
- Hand gesture framing presets
"""
import os
import math
import subprocess
import random
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import numpy as np
import cv2
from PIL import Image, ImageDraw

from src.config import OUTPUT_DIR, ASSETS_DIR


class AvatarAnimationService:
    """
    Generates lip-synchronized speaking videos for 2D and 3D avatars.
    """

    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_audio_energy(self, audio_path: Path, fps: int = 25) -> np.ndarray:
        """
        Extracts normalized RMS energy per video frame from an audio file using FFmpeg PCM decoding.
        """
        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path.resolve()),
            "-f", "s16le",
            "-ac", "1",
            "-ar", "16000",
            "-"
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw_audio, _ = proc.communicate()
        if not raw_audio or len(raw_audio) < 100:
            return np.zeros(25, dtype=np.float32)

        samples = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
        samples_per_frame = int(16000 / fps)
        total_frames = max(1, int(len(samples) / samples_per_frame))

        energies = []
        for i in range(total_frames):
            chunk = samples[i * samples_per_frame : (i + 1) * samples_per_frame]
            rms = float(np.sqrt(np.mean(chunk**2))) if len(chunk) > 0 else 0.0
            energies.append(rms)

        energies = np.array(energies, dtype=np.float32)
        max_e = float(np.max(energies)) if len(energies) > 0 else 0.0
        if max_e > 0.005:
            # Smooth energy curve with moving average
            kernel = np.ones(3) / 3.0
            smoothed = np.convolve(energies, kernel, mode="same")
            normalized = np.clip(smoothed / (max_e * 0.85), 0.0, 1.0)
            return normalized
        return np.zeros(total_frames, dtype=np.float32)

    def _ensure_portrait_base(self, avatar_image_path: Optional[str] = None) -> np.ndarray:
        """Loads avatar image or generates a high-quality stylized avatar portrait."""
        cand_path = None
        if avatar_image_path:
            p = Path(avatar_image_path)
            if not p.is_absolute():
                c1 = self.output_dir / p.name
                c2 = ASSETS_DIR / p.name
                if c1.exists():
                    cand_path = c1
                elif c2.exists():
                    cand_path = c2
            elif p.exists():
                cand_path = p

        if cand_path and cand_path.exists():
            img = cv2.imread(str(cand_path.resolve()))
            if img is not None and img.shape[0] > 50 and img.shape[1] > 50:
                return cv2.resize(img, (480, 560), interpolation=cv2.INTER_LANCZOS4)

        # Procedural high-grade presenter portrait
        w, h = 480, 560
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        # Gradient body background
        for y in range(h):
            canvas[y, :] = (int(25 + 20 * (y / h)), int(20 + 15 * (y / h)), int(40 + 30 * (y / h)))

        # Torso / Suit
        cv2.ellipse(canvas, (240, 560), (220, 260), 0, 180, 360, (30, 41, 59), -1)
        cv2.ellipse(canvas, (240, 560), (216, 256), 0, 180, 360, (51, 65, 85), 2)
        # Shirt collar
        collar_pts = np.array([[190, 360], [240, 440], [290, 360], [270, 340], [240, 370], [210, 340]], np.int32)
        cv2.fillPoly(canvas, [collar_pts], (240, 245, 250))
        # Tie
        tie_pts = np.array([[232, 430], [248, 430], [252, 530], [240, 550], [228, 530]], np.int32)
        cv2.fillPoly(canvas, [tie_pts], (180, 40, 80))

        # Neck
        cv2.rectangle(canvas, (208, 300), (272, 380), (180, 195, 225), -1)

        # Head / Face oval
        cv2.ellipse(canvas, (240, 220), (115, 145), 0, 0, 360, (190, 205, 235), -1)
        cv2.ellipse(canvas, (240, 220), (115, 145), 0, 0, 360, (160, 175, 205), 2)

        # Hair
        cv2.ellipse(canvas, (240, 150), (120, 95), 0, 180, 360, (25, 28, 36), -1)
        cv2.circle(canvas, (135, 180), 25, (25, 28, 36), -1)
        cv2.circle(canvas, (345, 180), 25, (25, 28, 36), -1)

        # Eyes base
        cv2.ellipse(canvas, (195, 205), (18, 10), 0, 0, 360, (255, 255, 255), -1)
        cv2.circle(canvas, (195, 205), 6, (60, 40, 30), -1)
        cv2.circle(canvas, (197, 203), 2, (255, 255, 255), -1)

        cv2.ellipse(canvas, (285, 205), (18, 10), 0, 0, 360, (255, 255, 255), -1)
        cv2.circle(canvas, (285, 205), 6, (60, 40, 30), -1)
        cv2.circle(canvas, (287, 203), 2, (255, 255, 255), -1)

        # Eyebrows
        cv2.ellipse(canvas, (195, 188), (22, 6), -5, 180, 360, (30, 30, 35), 3)
        cv2.ellipse(canvas, (285, 188), (22, 6), 5, 180, 360, (30, 30, 35), 3)

        # Nose bridge
        cv2.line(canvas, (240, 205), (236, 242), (170, 180, 205), 2)
        cv2.line(canvas, (236, 242), (245, 244), (170, 180, 205), 2)

        return canvas

    def _render_2d_speaking_frame(
        self,
        base_avatar: np.ndarray,
        energy: float,
        frame_idx: int,
        fps: int = 25
    ) -> np.ndarray:
        """
        Renders an animated 2D avatar frame with audio-reactive mouth viseme,
        eye blinking, and subtle natural head sway.
        """
        frame = base_avatar.copy()
        h, w = frame.shape[:2]

        # 1. Subtle head sway / breathing motion (sub-pixel shift)
        sway_x = int(math.sin(frame_idx * 0.08) * 3)
        sway_y = int(math.cos(frame_idx * 0.05) * 2)

        # 2. Eye Blinking: Blink every 80 frames (approx 3.2s) for 3 frames
        blink_cycle = frame_idx % 85
        is_blinking = blink_cycle < 4

        face_cx = int(w * 0.5) + sway_x
        eye_y = int(h * 0.366) + sway_y
        left_eye_x = face_cx - int(w * 0.094)
        right_eye_x = face_cx + int(w * 0.094)

        if is_blinking:
            # Overwrite eye with closed eyelid slit
            cv2.ellipse(frame, (left_eye_x, eye_y), (18, 11), 0, 0, 360, (190, 205, 235), -1)
            cv2.line(frame, (left_eye_x - 16, eye_y), (left_eye_x + 16, eye_y), (60, 50, 50), 2)
            cv2.ellipse(frame, (right_eye_x, eye_y), (18, 11), 0, 0, 360, (190, 205, 235), -1)
            cv2.line(frame, (right_eye_x - 16, eye_y), (right_eye_x + 16, eye_y), (60, 50, 50), 2)

        # 3. Audio-Reactive Mouth Visemes
        mouth_cx = face_cx
        mouth_cy = int(h * 0.51) + sway_y

        # Energy dictates mouth opening
        # Clear mouth region cleanly with skin tone
        skin_color = tuple(int(c) for c in frame[max(0, mouth_cy - 20), mouth_cx])
        cv2.ellipse(frame, (mouth_cx, mouth_cy), (38, 22), 0, 0, 360, skin_color, -1)

        mouth_w = int(24 + 10 * energy)
        mouth_h = int(3 + 22 * energy)

        if energy > 0.08:
            # Open mouth cavity
            cv2.ellipse(frame, (mouth_cx, mouth_cy), (mouth_w, mouth_h), 0, 0, 360, (20, 15, 30), -1)
            # Upper teeth
            teeth_w = int(mouth_w * 0.65)
            teeth_h = max(2, int(mouth_h * 0.35))
            cv2.rectangle(frame, (mouth_cx - teeth_w, mouth_cy - mouth_h + 1), (mouth_cx + teeth_w, mouth_cy - mouth_h + teeth_h), (245, 245, 250), -1)
            # Tongue hint if wide open
            if energy > 0.5:
                cv2.ellipse(frame, (mouth_cx, mouth_cy + int(mouth_h * 0.5)), (int(mouth_w * 0.5), int(mouth_h * 0.45)), 0, 0, 180, (80, 70, 170), -1)
            # Lip borders
            cv2.ellipse(frame, (mouth_cx, mouth_cy), (mouth_w, mouth_h), 0, 0, 360, (100, 90, 140), 2)
        else:
            # Closed gentle smile line
            cv2.ellipse(frame, (mouth_cx, mouth_cy), (22, 5), 0, 0, 180, (90, 80, 130), 2)

        return frame

    def _render_3d_mesh_frame(
        self,
        energy: float,
        frame_idx: int,
        width: int = 480,
        height: int = 560
    ) -> np.ndarray:
        """
        Renders a dynamic 3D wireframe and blended polygon avatar head.
        Articulates jaw based on audio energy and rotates in 3D space with subtle kinematics.
        """
        img = np.zeros((height, width, 3), dtype=np.uint8)

        # Head rotation kinematics: subtle yaw and pitch oscillation
        yaw = math.sin(frame_idx * 0.06) * 0.12
        pitch = math.cos(frame_idx * 0.04) * 0.08
        roll = math.sin(frame_idx * 0.05) * 0.03

        # Rotation matrices
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        cos_p, sin_p = math.cos(pitch), math.sin(pitch)
        cos_r, sin_r = math.cos(roll), math.sin(roll)

        # Base 3D keypoints [x, y, z] for cranial structure & facial blendshapes
        jaw_drop = energy * 26.0

        raw_points = {
            # Cranial contour
            "c_top": [0, -140, 0],
            "c_top_l": [-65, -120, -10],
            "c_top_r": [65, -120, -10],
            "temple_l": [-95, -60, -20],
            "temple_r": [95, -60, -20],
            "cheek_l": [-100, 20, -10],
            "cheek_r": [100, 20, -10],
            # Brow
            "brow_l": [-45, -45, 45],
            "brow_mid": [0, -48, 55],
            "brow_r": [45, -45, 45],
            # Eyes
            "eye_l": [-40, -25, 40],
            "eye_r": [40, -25, 40],
            # Nose
            "nose_bridge": [0, -20, 55],
            "nose_tip": [0, 15, 75],
            "nose_l": [-20, 15, 55],
            "nose_r": [20, 15, 55],
            # Mouth & Articulated Jaw
            "mouth_top": [0, 45, 60],
            "mouth_l": [-32, 52 + energy * 6, 50],
            "mouth_r": [32, 52 + energy * 6, 50],
            "mouth_bottom": [0, 55 + jaw_drop * 0.8, 56],
            "jaw_l": [-75, 75 + jaw_drop * 0.4, -5],
            "jaw_r": [75, 75 + jaw_drop * 0.4, -5],
            "chin": [0, 120 + jaw_drop, 40],
            # Neck/Shoulders
            "neck_l": [-45, 160 + jaw_drop * 0.2, -15],
            "neck_r": [45, 160 + jaw_drop * 0.2, -15],
            "shoulder_l": [-160, 240, -40],
            "shoulder_r": [160, 240, -40]
        }

        # Project 3D points to 2D
        cx, cy = width // 2, height // 2 - 20
        projected = {}
        for name, (x, y, z) in raw_points.items():
            # Apply yaw (Y axis)
            x1 = x * cos_y + z * sin_y
            z1 = -x * sin_y + z * cos_y
            # Apply pitch (X axis)
            y2 = y * cos_p - z1 * sin_p
            z2 = y * sin_p + z1 * cos_p
            # Apply roll (Z axis)
            x3 = x1 * cos_r - y2 * sin_r
            y3 = x1 * sin_r + y2 * cos_r

            # Perspective projection
            fov = 500.0
            scale = fov / (fov + z2 + 180.0)
            px = int(cx + x3 * scale)
            py = int(cy + y3 * scale)
            projected[name] = (px, py, z2)

        # Wireframe / Blendshape Edges
        lines = [
            ("c_top_l", "c_top"), ("c_top", "c_top_r"),
            ("c_top_l", "temple_l"), ("c_top_r", "temple_r"),
            ("temple_l", "cheek_l"), ("temple_r", "cheek_r"),
            ("cheek_l", "jaw_l"), ("cheek_r", "jaw_r"),
            ("jaw_l", "chin"), ("jaw_r", "chin"),
            # Brows & Forehead
            ("temple_l", "brow_l"), ("temple_r", "brow_r"),
            ("brow_l", "brow_mid"), ("brow_mid", "brow_r"),
            ("c_top", "brow_mid"),
            # Nose
            ("brow_mid", "nose_bridge"), ("nose_bridge", "nose_tip"),
            ("nose_l", "nose_tip"), ("nose_r", "nose_tip"),
            ("nose_l", "cheek_l"), ("nose_r", "cheek_r"),
            # Eyes
            ("brow_l", "eye_l"), ("brow_r", "eye_r"),
            # Mouth
            ("nose_tip", "mouth_top"),
            ("mouth_l", "mouth_top"), ("mouth_top", "mouth_r"),
            ("mouth_l", "mouth_bottom"), ("mouth_bottom", "mouth_r"),
            ("mouth_bottom", "chin"),
            ("jaw_l", "mouth_l"), ("jaw_r", "mouth_r"),
            # Shoulders
            ("jaw_l", "neck_l"), ("jaw_r", "neck_r"),
            ("neck_l", "shoulder_l"), ("neck_r", "shoulder_r"),
            ("chin", "neck_l"), ("chin", "neck_r")
        ]

        # Draw dynamic glow polygons for jaw/mouth cavity when speaking
        if energy > 0.08:
            m_poly = np.array([
                projected["mouth_top"][:2],
                projected["mouth_r"][:2],
                projected["mouth_bottom"][:2],
                projected["mouth_l"][:2]
            ], np.int32)
            cv2.fillPoly(img, [m_poly], (25, 20, 45))

        # Render 3D Wireframe lines with depth cueing
        for p1_key, p2_key in lines:
            x1, y1, z1 = projected[p1_key]
            x2, y2, z2 = projected[p2_key]
            # Color intensity based on frontness
            z_avg = (z1 + z2) / 2.0
            intensity = int(np.clip(160 + z_avg * 1.2, 70, 255))
            color = (int(intensity * 0.9), int(intensity * 0.5), int(intensity * 1.0)) # Cyber purple/cyan
            cv2.line(img, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

        # Highlight vertex joints
        for k, (px, py, pz) in projected.items():
            rad = 4 if "mouth" in k or "nose" in k or "brow" in k else 3
            joint_color = (255, 220, 80) if "mouth" in k else (240, 160, 255)
            cv2.circle(img, (px, py), rad, joint_color, -1, cv2.LINE_AA)

        return img

    def synthesize_speaking_avatar_video(
        self,
        script: str,
        audio_path: Path,
        output_path: Path,
        avatar_image_path: Optional[str] = None,
        is_3d_model: bool = False,
        curtain_mode: str = "green",
        curtain_active: bool = True,
        hand_gestures: str = "subtle",
        width: int = 1280,
        height: int = 720,
        fps: int = 25
    ) -> Path:
        """
        Synthesizes an audio-reactive speaking avatar video conformed to requested background and gestures.
        Streams generated frames directly into FFmpeg to ensure high performance and zero disk clutter.
        """
        # 1. Analyze audio energy envelope
        energies = self.extract_audio_energy(audio_path, fps=fps)
        total_frames = max(len(energies), int(fps * 2.0))

        # 2. Determine Curtain Color (BGR for OpenCV)
        if curtain_active and curtain_mode == "green":
            bg_bgr = (0, 255, 0) # Green Screen
        elif curtain_active and curtain_mode == "white":
            bg_bgr = (255, 255, 255) # Clean White Studio
        else:
            bg_bgr = (22, 13, 9) # Studio Dark Obsidian

        # 3. Framing based on hand gestures
        # Scale avatar dimensions proportionally to canvas size
        base_h = max(100, int(height * 0.85))
        base_w = max(80, int(base_h * (480.0 / 560.0)))

        if hand_gestures == "explanatory":
            avatar_w = min(base_w, width)
            avatar_h = min(base_h, height)
            target_x = max(0, min(int(width * 0.08), width - avatar_w))
            target_y = max(0, height - avatar_h)
        elif hand_gestures == "dynamic":
            avatar_h = min(height, max(100, int(base_h * 1.05)))
            avatar_w = min(width, max(80, int(avatar_h * (510.0 / 590.0))))
            target_x = max(0, (width - avatar_w) // 2)
            target_y = max(0, height - avatar_h)
        elif hand_gestures == "executive":
            avatar_h = min(height, max(100, int(base_h * 0.95)))
            avatar_w = min(width, max(80, int(avatar_h * (460.0 / 540.0))))
            target_x = max(0, (width - avatar_w) // 2)
            target_y = max(0, height - avatar_h)
        else: # subtle
            avatar_w = min(base_w, width)
            avatar_h = min(base_h, height)
            target_x = max(0, (width - avatar_w) // 2)
            target_y = max(0, height - avatar_h)

        # 4. Prepare base model
        base_2d = None
        if not is_3d_model:
            base_2d = self._ensure_portrait_base(avatar_image_path)
            if base_2d.shape[1] != avatar_w or base_2d.shape[0] != avatar_h:
                base_2d = cv2.resize(base_2d, (avatar_w, avatar_h), interpolation=cv2.INTER_LANCZOS4)

        # 5. FFmpeg pipe stream encoder
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{width}x{height}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",
            "-i", str(audio_path.resolve()),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_path.resolve())
        ]

        pipe = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        try:
            for f_idx in range(total_frames):
                energy = float(energies[f_idx]) if f_idx < len(energies) else 0.0

                # Canvas background
                canvas = np.full((height, width, 3), bg_bgr, dtype=np.uint8)

                if is_3d_model:
                    avatar_frame = self._render_3d_mesh_frame(energy, f_idx, width=avatar_w, height=avatar_h)
                    # Alpha or chroma blend: black background of 3D frame is transparent
                    gray = cv2.cvtColor(avatar_frame, cv2.COLOR_BGR2GRAY)
                    mask = (gray > 10).astype(np.uint8)
                    roi = canvas[target_y : target_y + avatar_h, target_x : target_x + avatar_w]
                    if roi.shape[:2] == avatar_frame.shape[:2]:
                        for c in range(3):
                            roi[:, :, c] = np.where(mask == 1, avatar_frame[:, :, c], roi[:, :, c])
                else:
                    avatar_frame = self._render_2d_speaking_frame(base_2d, energy, f_idx, fps=fps)
                    if avatar_frame.shape[:2] != (avatar_h, avatar_w):
                        avatar_frame = cv2.resize(avatar_frame, (avatar_w, avatar_h))
                    canvas[target_y : target_y + avatar_h, target_x : target_x + avatar_w] = avatar_frame

                pipe.stdin.write(canvas.tobytes())

            pipe.stdin.close()
            pipe.wait(timeout=45)
        except Exception as e:
            if pipe.poll() is None:
                pipe.kill()
            raise RuntimeError(f"Avatar rendering pipeline error: {e}")

        if not output_path.exists() or output_path.stat().st_size < 1000:
            raise RuntimeError("Avatar video generation failed to produce output file.")

        return output_path
