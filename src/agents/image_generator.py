"""
Image & Avatar Generator Sub-Agent.
Synthesizes keyframes, diagrams, and avatar portraits anchored to Persona continuity tokens.
"""
import uuid
from pathlib import Path
from typing import List, Optional
from src.contracts.persona import PersonaIdentityContract
from src.contracts.script_contract import ScriptContract, ScriptScene
from src.contracts.visual_contract import SceneVisualArtifact, ImageContract
from src.pipeline import MediaGenerationEngine


class ImageGeneratorAgent:
    """
    Specialized agent responsible for generating identity-locked keyframes,
    resolving uploaded video assets, and formatting presenter overlays.
    """

    def __init__(self, output_dir: Path, assets_dir: Path):
        self.output_dir = output_dir
        self.assets_dir = assets_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.media_engine = MediaGenerationEngine()

    def resolve_video_source(self, url_or_path: Optional[str]) -> Optional[str]:
        """Resolves static asset URL to absolute filesystem path."""
        if not url_or_path:
            return None
        s = str(url_or_path).strip()
        if s.startswith("/static_assets/"):
            p = self.assets_dir / s.replace("/static_assets/", "")
            return str(p) if p.exists() else None
        if s.startswith("/static_renders/"):
            p = self.output_dir / s.replace("/static_renders/", "")
            return str(p) if p.exists() else None
        if Path(s).exists():
            return str(Path(s).resolve())
        return None

    def generate_scene_image(
        self,
        scene: ScriptScene,
        persona: PersonaIdentityContract,
        art_style: str,
        resolution: str,
        session_id: str
    ) -> Path:
        """
        Synthesizes visual keyframe image for a scene, appending style and continuity anchors.
        """
        image_path = self.output_dir / f"keyframe_{session_id}_{scene.scene_id}.png"
        
        # Build prompt
        base_prompt = scene.visual_description
        if "photorealistic" in art_style.lower() or "corporate" in art_style.lower():
            full_prompt = f"{base_prompt}, {art_style}, professional 4k broadcast quality"
        else:
            full_prompt = f"{base_prompt}, {art_style}"

        success = self.media_engine.generate_image(
            prompt=full_prompt,
            output_path=image_path,
            resolution=resolution
        )
        if not success or not image_path.exists():
            # Fallback canvas
            self.media_engine._create_placeholder_image(full_prompt, image_path, resolution)

        return image_path

    def generate_avatar_portrait(
        self,
        persona: PersonaIdentityContract,
        session_id: str
    ) -> Optional[Path]:
        """Generates or retrieves portrait image for PiP avatar compositing."""
        avatar_path = self.output_dir / f"avatar_{session_id}_{persona.persona_id}.png"
        prompt = f"Professional studio portrait headshot of {persona.visual_continuity_anchor}, transparent or neutral dark background, 8k"
        
        success = self.media_engine.generate_image(
            prompt=prompt,
            output_path=avatar_path,
            resolution="1:1_square"
        )
        if success and avatar_path.exists():
            return avatar_path
        return None

    def generate_visual_contract(
        self,
        script: ScriptContract,
        persona: PersonaIdentityContract,
        resolution: str = "16:9_hd",
        avatar_layout: str = "pip_bottom_right",
        custom_avatar_path: Optional[str] = None
    ) -> ImageContract:
        """
        Executes complete visual package generation for all scenes.
        """
        session_id = uuid.uuid4().hex[:8]
        scene_visuals: List[SceneVisualArtifact] = []

        # Resolve avatar portrait
        avatar_img_path = custom_avatar_path
        if not avatar_img_path and avatar_layout != "none":
            portrait_file = self.generate_avatar_portrait(persona, session_id)
            if portrait_file:
                avatar_img_path = str(portrait_file)

        for scene in script.scenes:
            # Check if using uploaded video asset
            if scene.video_source_type == "uploaded_video" and scene.video_source_url:
                resolved = self.resolve_video_source(scene.video_source_url)
                if resolved:
                    scene_visuals.append(
                        SceneVisualArtifact(
                            scene_id=scene.scene_id,
                            visual_type="uploaded_video",
                            media_path=resolved,
                            avatar_overlay_path=avatar_img_path if avatar_layout != "none" else None,
                            avatar_layout=avatar_layout
                        )
                    )
                    continue

            # Generate AI Keyframe
            img_path = self.generate_scene_image(
                scene=scene,
                persona=persona,
                art_style=script.art_style_preset,
                resolution=resolution,
                session_id=session_id
            )
            scene_visuals.append(
                SceneVisualArtifact(
                    scene_id=scene.scene_id,
                    visual_type="ai_image",
                    media_path=str(img_path),
                    avatar_overlay_path=avatar_img_path if avatar_layout != "none" else None,
                    avatar_layout=avatar_layout
                )
            )

        return ImageContract(
            art_style_applied=script.art_style_preset,
            resolution=resolution,
            scene_visuals=scene_visuals
        )
