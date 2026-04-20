import { useEffect, useRef } from "react";

import { useHmiStore } from "../stores/robotStore";
import { RobotScene } from "../three/robotScene";

interface Robot3DPanelProps {
  activeChainIds?: string[];
}

export function Robot3DPanel({ activeChainIds }: Robot3DPanelProps): JSX.Element {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<RobotScene | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const state = useHmiStore((s) => s.state);
  const profile = useHmiStore((s) => s.profile);
  const urdfUrl = profile?.urdfUrl ?? "";
  const chainMapKey = JSON.stringify(profile?.jointMap ?? {});

  useEffect(() => {
    if (!mountRef.current || !profile) {
      return;
    }
    const mountNode = mountRef.current;
    sceneRef.current = new RobotScene(mountNode, profile.urdfUrl, profile);

    const onResize = (): void => {
      sceneRef.current?.resize();
    };
    window.addEventListener("resize", onResize);

    if (typeof ResizeObserver !== "undefined") {
      resizeObserverRef.current = new ResizeObserver(() => {
        sceneRef.current?.resize();
      });
      resizeObserverRef.current.observe(mountNode);
    }

    return () => {
      window.removeEventListener("resize", onResize);
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      sceneRef.current?.dispose();
      sceneRef.current = null;
    };
  }, [urdfUrl, chainMapKey]);

  useEffect(() => {
    if (state) {
      sceneRef.current?.update(state);
    }
  }, [state, urdfUrl, chainMapKey]);

  useEffect(() => {
    sceneRef.current?.setActiveChains(activeChainIds ?? null);
  }, [activeChainIds]);

  return (
    <section className="panel panel-3d">
      <div className="viewport" ref={mountRef} />
    </section>
  );
}
