import { useEffect, useRef, useState } from "react";

import { connectCameraWS } from "../services/wsClient";
import { useHmiStore } from "../stores/robotStore";

interface CameraPanelProps {
  cameraName: string;
}

export function CameraPanel(props: CameraPanelProps): JSX.Element {
  const [frame, setFrame] = useState("");
  const [receiveFps, setReceiveFps] = useState<number | null>(null);
  const [displayFps, setDisplayFps] = useState<number | null>(null);
  const [frameAgeMs, setFrameAgeMs] = useState<number | null>(null);
  const latestFrameRef = useRef<string>("");
  const rafIdRef = useRef<number | null>(null);
  const profile = useHmiStore((s) => s.profile);

  useEffect(() => {
    if (!profile) {
      return;
    }
    const subscription = connectCameraWS(profile, props.cameraName, (payload) => {
      if (payload.dataUrl !== null) {
        latestFrameRef.current = payload.dataUrl;
        if (rafIdRef.current === null) {
          rafIdRef.current = window.requestAnimationFrame(() => {
            rafIdRef.current = null;
            setFrame(latestFrameRef.current);
          });
        }
      }
      setReceiveFps(payload.receiveFps);
      setDisplayFps(payload.displayFps);
      setFrameAgeMs(payload.frameAgeMs);
    });
    return () => {
      subscription.close();
      if (rafIdRef.current !== null) {
        window.cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    };
  }, [profile, props.cameraName]);

  return (
    <section className="panel camera-panel">
      <div className="camera-panel-header">
        <div className="camera-fps-wrap">
          <p className="camera-fps">Receive FPS: {receiveFps !== null ? `${receiveFps.toFixed(1)} FPS` : "-- FPS"}</p>
          <p className="camera-fps">Display FPS: {displayFps !== null ? `${displayFps.toFixed(1)} FPS` : "-- FPS"}</p>
          <p className="camera-fps">Frame Age: {frameAgeMs !== null ? `${frameAgeMs.toFixed(1)} ms` : "-- ms"}</p>
        </div>
      </div>
      <div className="camera-media-wrap">
        {frame ? <img src={frame} alt={props.cameraName} /> : <div className="placeholder">Waiting for stream...</div>}
      </div>
    </section>
  );
}
