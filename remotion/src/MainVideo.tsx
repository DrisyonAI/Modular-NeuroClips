import React from "react";
import { AbsoluteFill, Audio, Sequence } from "remotion";
import { Scene } from "./Scene";
import { TitleCard } from "./TitleCard";
import { AudioVisualizer } from "./AudioVisualizer";

export interface SceneData {
  scene_id: number;
  keyframe_path?: string;
  visual_prompt: string;
  motion_prompt: string;
  narration?: string;
  duration_seconds: number;
}

export interface MainVideoProps {
  title: string;
  art_style_preset: string;
  scenes: SceneData[];
  audio_path?: string;
}

export const MainVideo: React.FC<MainVideoProps> = ({
  title,
  art_style_preset,
  scenes,
  audio_path
}) => {
  const fps = 30;
  let currentFrame = 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "#090d16" }}>
      {/* Title Card at beginning */}
      <Sequence from={0} durationInFrames={60}>
        <TitleCard title={title} artStyle={art_style_preset} />
      </Sequence>

      {/* Sequential Scenes */}
      {scenes.map((sc, idx) => {
        const durationFrames = Math.round((sc.duration_seconds || 4) * fps);
        const fromFrame = 60 + currentFrame;
        currentFrame += durationFrames;

        return (
          <Sequence key={idx} from={fromFrame} durationInFrames={durationFrames}>
            <Scene scene={sc} sceneIndex={idx} />
          </Sequence>
        );
      })}

      {/* Synchronized Voiceover Audio */}
      {audio_path && <Audio src={audio_path} />}

      {/* Audio Visualizer Overlay */}
      <AudioVisualizer />
    </AbsoluteFill>
  );
};
