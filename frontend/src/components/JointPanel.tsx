import { useMemo } from "react";

import { useHmiStore } from "../stores/robotStore";
import type { ChainId } from "../types/protocol";

interface JointPanelProps {
  chainId: ChainId;
}

export function JointPanel(props: JointPanelProps): JSX.Element {
  const state = useHmiStore((s) => s.state);
  const values = useMemo(() => {
    const chain = state?.chains?.[props.chainId];
    if (!chain) {
      return [0, 0, 0, 0, 0, 0];
    }
    if (!chain.joints.length) {
      return [0, 0, 0, 0, 0, 0];
    }
    // Round to 1 decimal place so the bar and text are always consistent.
    // Also normalises -0 and tiny values like -0.049 that toFixed(1) renders as "-0.0".
    return chain.joints.map((item) => {
      const r = Math.round(item.angle_deg * 10) / 10;
      return r || 0; // convert -0 to 0
    });
  }, [props.chainId, state]);

  const maxAbs = Math.max(0, ...values.map((value) => Math.abs(value)));

  return (
    <section className="panel joint-snapshot-panel">
      <div className="bar-list joint-snapshot-list">
        {values.map((value, index) => {
          const width = maxAbs > 0 ? Math.min(100, (Math.abs(value) / maxAbs) * 100) : 0;
          return (
            <div className="bar-row" key={`${props.chainId}-${index}`}>
              <span>J{index + 1}</span>
              <div className="bar-wrap">
                <div className="bar" style={{ width: `${width}%` }} />
              </div>
              <span>{value.toFixed(1)}°</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
