import React from "react";
import { useCurrentFrame } from "remotion";

export const AudioVisualizer: React.FC = () => {
  const frame = useCurrentFrame();
  const bars = [1, 2, 3, 4, 5];

  return (
    <div
      style={{
        position: "absolute",
        bottom: 12,
        right: 48,
        display: "flex",
        alignItems: "flex-end",
        gap: 4,
        height: 18
      }}
    >
      {bars.map((b) => {
        const height = Math.abs(Math.sin((frame + b * 15) * 0.15)) * 16 + 4;
        return (
          <div
            key={b}
            style={{
              width: 3,
              height: `${height}px`,
              backgroundColor: "#38bdf8",
              borderRadius: 2
            }}
          />
        );
      })}
    </div>
  );
};
