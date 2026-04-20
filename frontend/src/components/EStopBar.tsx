import { useEffect, useState } from "react";

import type { ApiClient } from "../services/apiClient";
import { loadProfile } from "../services/config";
import { useHmiStore } from "../stores/robotStore";

interface EStopBarProps {
  api: ApiClient;
}

export function EStopBar(props: EStopBarProps): JSX.Element {
  const state = useHmiStore((s) => s.state);
  const profile = useHmiStore((s) => s.profile);
  const setProfile = useHmiStore((s) => s.setProfile);
  const active = Boolean(state?.e_stop);
  const currentMode = profile?.mode ?? "simulation";
  const [switching, setSwitching] = useState(false);
  // Visual mode drives the indicator animation independently of the async switch
  const [visualMode, setVisualMode] = useState(currentMode);

  // Sync visual mode when profile actually changes (e.g. from external source)
  useEffect(() => {
    if (!switching) setVisualMode(currentMode);
  }, [currentMode, switching]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.code !== "ShiftLeft" && event.code !== "ShiftRight") {
        return;
      }
      event.preventDefault();
      props.api.postEStop(true).catch(() => undefined);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.api]);

  const toggleMode = async (): Promise<void> => {
    const target = currentMode === "simulation" ? "real" : "simulation";
    // Immediately move the indicator for smooth animation
    setVisualMode(target);
    setSwitching(true);
    // Wait for the CSS transition to finish before doing the heavy API call
    await new Promise((r) => setTimeout(r, 300));
    try {
      await props.api.postRobotMode(target);
      const modeStatus = await props.api.getRobotMode();
      const newProfile = await loadProfile();
      setProfile({ ...newProfile, mode: modeStatus.mode });
    } catch {
      // Revert visual on failure
      setVisualMode(currentMode);
    } finally {
      setSwitching(false);
    }
  };

  return (
    <div className={`estop-bar ${active ? "estop-active" : "estop-normal"}`}>
      <div className="estop-info">
        <strong>Safety</strong>
        <p>Emergency Stop: {state?.e_stop ? "ACTIVE" : "RELEASED"}</p>
      </div>
      <div className="estop-actions">
        <button className="danger" onClick={() => props.api.postEStop(true)}>
          Emergency Stop (Shift)
        </button>
        <button className="release" onClick={() => props.api.postEStop(false)}>
          Release Emergency Stop
        </button>
        <div className={`mode-segmented ${switching ? "mode-switching" : ""}`}>
          <div className={`mode-seg-indicator ${visualMode === "real" ? "mode-ind-right mode-ind-real" : "mode-ind-left mode-ind-sim"}`} />
          <button
            className={`mode-seg-btn ${visualMode === "simulation" ? "mode-seg-active" : ""}`}
            onClick={currentMode !== "simulation" && !switching ? () => void toggleMode() : undefined}
          >
            Sim
          </button>
          <button
            className={`mode-seg-btn ${visualMode === "real" ? "mode-seg-active" : ""}`}
            onClick={currentMode !== "real" && !switching ? () => void toggleMode() : undefined}
          >
            Real
          </button>
        </div>
      </div>
    </div>
  );
}
