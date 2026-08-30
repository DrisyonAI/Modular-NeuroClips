import React from "react";

export const Subtitles: React.FC<{ text: string }> = ({ text }) => {
  return (
    <div
      style={{
        position: "absolute",
        bottom: 40,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        paddingLeft: 40,
        paddingRight: 280
      }}
    >
      <div
        style={{
          background: "rgba(9, 13, 22, 0.85)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(255, 255, 255, 0.15)",
          padding: "10px 24px",
          borderRadius: 12,
          color: "#ffffff",
          fontSize: 20,
          fontWeight: 600,
          fontFamily: "sans-serif",
          textAlign: "center",
          maxWidth: "85%",
          boxShadow: "0 8px 24px rgba(0,0,0,0.6)"
        }}
      >
        {text}
      </div>
    </div>
  );
};
