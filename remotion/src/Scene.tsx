import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, Img } from "remotion";
import { SceneData } from "./MainVideo";
import { Subtitles } from "./Subtitles";

export const Scene: React.FC<{ scene: SceneData; sceneIndex: number }> = ({
  scene,
  sceneIndex
}) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, 120], [1.0, 1.15], {
    extrapolateRight: "clamp"
  });

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {/* Background Keyframe / Motion Visual */}
      {scene.keyframe_path ? (
        <Img
          src={scene.keyframe_path}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${scale})`
          }}
        />
      ) : (
        <AbsoluteFill
          style={{
            background: "linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%)",
            display: "flex",
            justifyContent: "center",
            alignItems: "center"
          }}
        >
          <div style={{ color: "#38bdf8", fontSize: 32, fontFamily: "sans-serif" }}>
            Scene #{scene.scene_id}
          </div>
        </AbsoluteFill>
      )}

      {/* Speaker Avatar Floating Card (PiP Bottom Right) */}
      <div
        style={{
          position: "absolute",
          bottom: 36,
          right: 36,
          width: 220,
          height: 220,
          borderRadius: 20,
          background: "rgba(15, 23, 42, 0.85)",
          backdropFilter: "blur(16px)",
          border: "2px solid rgba(56, 189, 248, 0.5)",
          boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center"
        }}
      >
        <div style={{ fontSize: 48 }}>👤</div>
        <div
          style={{
            color: "#38bdf8",
            fontSize: 12,
            fontWeight: "bold",
            fontFamily: "sans-serif",
            marginTop: 8
          }}
        >
          AI Presenter
        </div>
      </div>

      {/* Subtitles Overlay */}
      {scene.narration && <Subtitles text={scene.narration} />}
    </AbsoluteFill>
  );
};
