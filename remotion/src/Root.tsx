import React from "react";
import { Composition } from "remotion";
import { MainVideo } from "./MainVideo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="MainVideo"
        component={MainVideo}
        durationInFrames={360}
        fps={30}
        width={1280}
        height={720}
        defaultProps={{
          title: "Modular-NeuroClips Production",
          art_style_preset: "Cinematic 35mm",
          scenes: [],
          audio_path: ""
        }}
      />
    </>
  );
};
