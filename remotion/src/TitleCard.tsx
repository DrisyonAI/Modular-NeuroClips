import React from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const TitleCard: React.FC<{ title: string; artStyle: string }> = ({
  title,
  artStyle
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scale = spring({
    frame,
    fps,
    config: { damping: 12 }
  });

  return (
    <AbsoluteFill
      style={{
        background: "radial-gradient(circle at center, #1e1b4b 0%, #090d16 100%)",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        padding: 48
      }}
    >
      <div
        style={{
          transform: `scale(${scale})`,
          textAlign: "center"
        }}
      >
        <div
          style={{
            fontSize: 16,
            color: "#38bdf8",
            fontWeight: "bold",
            letterSpacing: 3,
            textTransform: "uppercase",
            fontFamily: "sans-serif",
            marginBottom: 16
          }}
        >
          ⚡ Modular-NeuroClips Studio
        </div>
        <h1
          style={{
            fontSize: 48,
            fontWeight: 900,
            color: "#ffffff",
            fontFamily: "sans-serif",
            lineHeight: 1.2,
            maxWidth: 900
          }}
        >
          {title}
        </h1>
        <div
          style={{
            fontSize: 14,
            color: "#94a3b8",
            fontFamily: "sans-serif",
            marginTop: 16
          }}
        >
          Style: {artStyle}
        </div>
      </div>
    </AbsoluteFill>
  );
};
