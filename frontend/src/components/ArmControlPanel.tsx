import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

import type { ApiClient } from "../services/apiClient";
import { useHmiStore } from "../stores/robotStore";
import type { CartesianFrame, ChainId } from "../types/protocol";

interface ArmControlPanelProps {
    chainId: ChainId;
    api: ApiClient;
}

const DEFAULT_JOINT_COUNT = 6;
const CARTESIAN_AXES = ["X", "Y", "Z", "R", "P", "Y"];

const makeNumberArray = (count: number, value: number): number[] => Array.from({ length: count }, () => value);
const makeTextArray = (count: number, value: string): string[] => Array.from({ length: count }, () => value);

export function ArmControlPanel(props: ArmControlPanelProps): JSX.Element {
    const state = useHmiStore((s) => s.state);
    const profile = useHmiStore((s) => s.profile);

    const initAngleStep = profile?.defaultAngleStepDeg ?? 1;
    const initLengthStep = profile?.defaultLengthStepM ?? 0.005;

    const [angleStepDeg, setAngleStepDeg] = useState(initAngleStep);
    const [angleStepDraft, setAngleStepDraft] = useState(initAngleStep.toFixed(3));
    const [lengthStep, setLengthStep] = useState(initLengthStep);
    const [lengthStepDraft, setLengthStepDraft] = useState(initLengthStep.toFixed(4));

    const [jointTargets, setJointTargets] = useState<number[]>(makeNumberArray(DEFAULT_JOINT_COUNT, 0));
    const [jointDrafts, setJointDrafts] = useState<string[]>(makeTextArray(DEFAULT_JOINT_COUNT, "0.00"));
    const initRad = (initAngleStep * Math.PI) / 180;
    const [cartesianSteps, setCartesianSteps] = useState<number[]>([initLengthStep, initLengthStep, initLengthStep, initRad, initRad, initRad]);
    const [frame, setFrame] = useState<CartesianFrame>("tool");
    const [status, setStatus] = useState("idle");
    const [allJointsDraft, setAllJointsDraft] = useState("");
    const [eeMatrixDraft, setEeMatrixDraft] = useState("");
    const eeMatrixFocusedRef = useRef(false);
    // Always-current snapshot of joint state – used in release handlers to
    // avoid stale-closure issues when the buttons fire asynchronously.
    const currentRef = useRef<number[]>([]);
    // Always-current snapshot of commanded joint targets, updated synchronously
    // before each joint command so that rapid-fire hold calls accumulate correctly
    // without depending on React's async state flush.
    const jointTargetsRef = useRef<number[]>(makeNumberArray(DEFAULT_JOINT_COUNT, 0));

    const holdTimerRef = useRef<number | null>(null);
    const holdActiveRef = useRef(false);
    const taskQueueRef = useRef<Promise<void>>(Promise.resolve());
    const activeInputRef = useRef<string | null>(null);
    const syncTargetsWithCurrentRef = useRef(true);
    const isJointHoldRef = useRef(false);

    const pluginJointCount = useMemo(() => {
        const count = profile?.jointMap?.[props.chainId]?.length ?? 0;
        return count > 0 ? count : DEFAULT_JOINT_COUNT;
    }, [profile?.jointMap, props.chainId]);

    const current = useMemo(() => {
        const chainState = state?.chains?.[props.chainId];
        const reported = chainState?.joints.map((item) => item.angle_deg) ?? [];
        if (!reported.length) {
            return makeNumberArray(pluginJointCount, 0);
        }
        if (reported.length >= pluginJointCount) {
            return reported.slice(0, pluginJointCount);
        }
        return [...reported, ...makeNumberArray(pluginJointCount - reported.length, 0)];
    }, [pluginJointCount, props.chainId, state]);

    // Backend-reported joint targets (IK-solved during cartesian jog).
    const backendTargets = useMemo(() => {
        const chainState = state?.chains?.[props.chainId];
        const reported = chainState?.joint_targets?.map((item) => item.angle_deg) ?? [];
        if (!reported.length) {
            return current;
        }
        if (reported.length >= pluginJointCount) {
            return reported.slice(0, pluginJointCount);
        }
        return [...reported, ...makeNumberArray(pluginJointCount - reported.length, 0)];
    }, [pluginJointCount, props.chainId, state, current]);

    const isEstopped = Boolean(state?.e_stop);

    const profileMode = profile?.mode ?? "simulation";
    const activePlugin = profile?.activePlugin ?? "";

    useEffect(() => {
        syncTargetsWithCurrentRef.current = true;
    }, [props.chainId]);

    // Sync angle/length step when profile default values change (e.g. after
    // applying a new plugin config in the settings panel).
    useEffect(() => {
        const a = profile?.defaultAngleStepDeg;
        if (a !== undefined) {
            updateAngleStep(a);
        }
    }, [profile?.defaultAngleStepDeg]);

    useEffect(() => {
        const l = profile?.defaultLengthStepM;
        if (l !== undefined) {
            updateLengthStep(l);
        }
    }, [profile?.defaultLengthStepM]);

    useEffect(() => {
        setJointTargets((prev) => {
            const next = prev.slice(0, pluginJointCount);
            while (next.length < pluginJointCount) {
                next.push(0);
            }
            return next;
        });
        setJointDrafts((prev) => {
            const next = prev.slice(0, pluginJointCount);
            while (next.length < pluginJointCount) {
                next.push("0.0");
            }
            return next;
        });
    }, [pluginJointCount]);

    useEffect(() => {
        taskQueueRef.current = Promise.resolve();
        syncTargetsWithCurrentRef.current = true;
        setJointTargets(current);
        setJointDrafts(current.map((value) => formatDeg(value)));
    }, [props.chainId, profileMode, activePlugin]);

    // When e-stop triggers, revert any in-flight joint targets back to
    // current values and re-enable sync so the display stays consistent.
    useEffect(() => {
        if (!isEstopped) {
            return;
        }
        syncTargetsWithCurrentRef.current = true;
        isJointHoldRef.current = false;
        setJointTargets(current);
        setJointDrafts(current.map((value) => formatDeg(value)));
        setAllJointsDraft("");
    }, [isEstopped]);

    useEffect(() => {
        if (!state) {
            return;
        }
        if (!syncTargetsWithCurrentRef.current) {
            return;
        }
        if (isJointHoldRef.current) {
            return;
        }
        if (activeInputRef.current?.startsWith(`${props.chainId}-joint-`)) {
            return;
        }
        // Use backend-reported targets instead of raw current values so that
        // during cartesian jog the inputs show the IK-solved target, not
        // the lagging actual position.
        setJointTargets(backendTargets);
        setJointDrafts(backendTargets.map((value) => formatDeg(value)));
        if (activeInputRef.current !== `${props.chainId}-all-joints`) {
            setAllJointsDraft("");
        }
    }, [backendTargets, props.chainId, state]);

    useEffect(() => {
        return () => {
            stopHold();
        };
    }, []);

    // Keep currentRef in sync so event-handler closures always see the latest
    // joint state without triggering re-renders.
    useEffect(() => {
        currentRef.current = current;
    }, [current]);

    // Keep jointTargetsRef in sync with jointTargets state for reads that happen
    // outside of a hold sequence (e.g. after a programmatic reset).
    useEffect(() => {
        jointTargetsRef.current = jointTargets;
    }, [jointTargets]);

    // Keep a ref for backendTargets so release handlers see the latest values.
    const backendTargetsRef = useRef<number[]>([]);
    useEffect(() => {
        backendTargetsRef.current = backendTargets;
    }, [backendTargets]);

    // Sync EE matrix display from state when the textarea is not focused
    const eeTarget = state?.chains?.[props.chainId]?.ee_target ?? null;
    useEffect(() => {
        if (eeMatrixFocusedRef.current) return;
        if (eeTarget === null) {
            setEeMatrixDraft("");
            return;
        }
        setEeMatrixDraft(eeTarget.map((row) => row.map((v) => fixedNoNegZero(v, 4)).join("  ")).join("\n"));
    }, [eeTarget]);

    const enqueueTask = (task: () => Promise<void>): void => {
        taskQueueRef.current = taskQueueRef.current
            .catch(() => undefined)
            .then(task)
            .catch(() => undefined);
    };

    const clamp = (value: number, min: number, max: number): number => Math.min(max, Math.max(min, value));

    const parseDraft = (raw: string): number | null => {
        const cleaned = raw.trim().replace(/°$/, "");
        const parsed = Number(cleaned);
        return Number.isFinite(parsed) ? parsed : null;
    };

    const fixedNoNegZero = (v: number, digits: number): string => {
        const s = v.toFixed(digits);
        return s.startsWith('-') && parseFloat(s) === 0 ? s.slice(1) : s;
    };

    const formatDeg = (value: number): string => `${fixedNoNegZero(value, 2)}°`;

    const toCommandPayload = (target: number[]): number[] => {
        return target;
    };

    const sendJointTarget = async (target: number[]): Promise<void> => {
        const result = await props.api.postJointCommand(props.chainId, toCommandPayload(target));
        setStatus(result.message);
    };

    const applyJointDelta = (jointIndex: number, direction: -1 | 1): void => {
        if (isEstopped) {
            setStatus("blocked: estop active");
            return;
        }
        syncTargetsWithCurrentRef.current = false;
        isJointHoldRef.current = true;
        // Compute next target from the ref (not state) so rapid-fire hold calls
        // accumulate correctly even before React flushes the previous state update.
        // Side effects (enqueueTask, setJointDrafts) must NOT be inside the state
        // updater to prevent React StrictMode double-invocation from sending
        // duplicate commands.
        const next = jointTargetsRef.current.map((v, i) =>
            i === jointIndex ? v + direction * angleStepDeg : v
        );
        jointTargetsRef.current = next;
        setJointTargets(next);
        setJointDrafts(next.map((value) => formatDeg(value)));
        enqueueTask(async () => sendJointTarget(next));
    };

    const primeJointTargetsFromCurrent = (): void => {
        if (profileMode !== "real") {
            return;
        }
        syncTargetsWithCurrentRef.current = false;
        const next = [...currentRef.current];
        jointTargetsRef.current = next;
        setJointTargets(next);
        setJointDrafts(next.map((value) => formatDeg(value)));
        if (activeInputRef.current !== `${props.chainId}-all-joints`) {
            setAllJointsDraft("");
        }
    };

    const syncJointTargetToCurrent = (): void => {
        isJointHoldRef.current = false;
        if (profileMode === "real") {
            // In real mode the robot takes time to reach the target.
            // Keep targets at the last commanded values so the input box
            // shows the target and Err reflects the remaining distance.
            return;
        }
        // Simulation mode: snap targets to current (execution is instant).
        syncTargetsWithCurrentRef.current = true;
        const next = [...currentRef.current];
        setJointTargets(next);
        setJointDrafts(next.map((value) => formatDeg(value)));
        if (activeInputRef.current !== `${props.chainId}-all-joints`) {
            setAllJointsDraft("");
        }
    };

    // Called when a cartesian jog button is released.
    // Freeze the display at the backend-reported targets (IK-solved values)
    // so that Err correctly shows the remaining distance.
    const onCartesianRelease = (): void => {
        // Drain the task queue: reset the ref so that any tasks already chained
        // (but not yet started) will not find themselves on the active chain.
        // Combined with the holdActiveRef guard inside each cartesian task body,
        // this ensures no further cartesian commands reach the backend after the
        // button is released.
        taskQueueRef.current = Promise.resolve();
        syncTargetsWithCurrentRef.current = true;
        // Use backend targets (IK-solved) rather than raw current position.
        const next = [...backendTargetsRef.current];
        setJointTargets(next);
        setJointDrafts(next.map((value) => formatDeg(value)));
        if (activeInputRef.current !== `${props.chainId}-all-joints`) {
            setAllJointsDraft("");
        }
    };

    const sendCartesian = async (axis: number, direction: -1 | 1): Promise<void> => {
        const command = [0, 0, 0, 0, 0, 0];
        const magnitude = Math.abs(cartesianSteps[axis] ?? 0);
        command[axis] = direction * magnitude;
        const result = await props.api.postCartesianJog(props.chainId, command, frame);
        setStatus(result.message);
    };

    const startHold = (handler: () => void): void => {
        holdActiveRef.current = true;
        handler(); // fire immediately on press for responsive feel
        const period = Math.round(1000 / (profile?.commandHz ?? 60));
        if (holdTimerRef.current !== null) {
            window.clearTimeout(holdTimerRef.current);
        }
        // Delay the first repeat by one full period before starting the recurring
        // interval.  This ensures holding for exactly one period (e.g. 100 ms at
        // commandHz=10) only sends ONE command (the immediate one), while holding
        // for N periods sends N commands total.  Without this delay the first
        // interval fire at t=period would cause a "double step" for short holds.
        holdTimerRef.current = window.setTimeout(() => {
            if (!holdActiveRef.current) { holdTimerRef.current = null; return; }
            holdTimerRef.current = window.setInterval(() => {
                if (holdActiveRef.current) { handler(); }
            }, period);
        }, period);
    };

    const stopHold = (): boolean => {
        const wasHolding = holdActiveRef.current;
        holdActiveRef.current = false;
        if (holdTimerRef.current !== null) {
            // clearTimeout works for both setTimeout and setInterval IDs in
            // modern browsers; also call clearInterval to be safe.
            window.clearTimeout(holdTimerRef.current);
            window.clearInterval(holdTimerRef.current);
            holdTimerRef.current = null;
        }
        return wasHolding;
    };

    const holdEvents = (handler: () => void, onRelease?: () => void, onPressStart?: () => void) => ({
        onMouseDown: (event: MouseEvent<HTMLButtonElement>) => {
            if (event.button !== 0) {
                return;
            }
            event.preventDefault();
            onPressStart?.();
            startHold(handler);
        },
        onMouseUp: () => {
            if (stopHold()) {
                onRelease?.();
            }
        },
        onMouseLeave: () => {
            if (stopHold()) {
                onRelease?.();
            }
        },
        onTouchStart: () => {
            onPressStart?.();
            startHold(handler);
        },
        onTouchEnd: () => {
            if (stopHold()) {
                onRelease?.();
            }
        },
        onTouchCancel: () => {
            if (stopHold()) {
                onRelease?.();
            }
        },
    });

    const onJointInputChange = (jointIndex: number, raw: string): void => {
        setJointDrafts((prev) => {
            const next = [...prev];
            next[jointIndex] = raw;
            return next;
        });
    };

    const applyJointInput = (jointIndex: number): void => {
        if (isEstopped) {
            // Revert draft to current value after e-stop blocks the command.
            setJointDrafts((prev) => {
                const next = [...prev];
                next[jointIndex] = formatDeg(current[jointIndex] ?? 0);
                return next;
            });
            syncTargetsWithCurrentRef.current = true;
            setJointTargets(current);
            setStatus("blocked: estop active");
            return;
        }
        const parsed = parseDraft(jointDrafts[jointIndex] ?? "");
        if (parsed === null) {
            setJointDrafts((prev) => {
                const next = [...prev];
                next[jointIndex] = formatDeg(jointTargets[jointIndex]);
                return next;
            });
            return;
        }
        const value = clamp(parsed, -360, 360);
        syncTargetsWithCurrentRef.current = false;
        const next = jointTargetsRef.current.map((v, i) => (i === jointIndex ? value : v));
        jointTargetsRef.current = next;
        setJointTargets(next);
        setJointDrafts(next.map((item) => formatDeg(item)));
        enqueueTask(async () => sendJointTarget(next));
    };

    const updateAngleStep = (value: number): void => {
        const next = clamp(value, 0, 10);
        setAngleStepDeg(next);
        setAngleStepDraft(next.toFixed(3));
        const rad = (next * Math.PI) / 180.0;
        setCartesianSteps((prev) => [prev[0], prev[1], prev[2], rad, rad, rad]);
    };

    const updateLengthStep = (value: number): void => {
        const next = clamp(value, 0, 0.05);
        setLengthStep(next);
        setLengthStepDraft(next.toFixed(4));
        setCartesianSteps((prev) => [next, next, next, prev[3], prev[4], prev[5]]);
    };

    const commitAngleStep = (): void => {
        const parsed = parseDraft(angleStepDraft);
        if (parsed === null) {
            setAngleStepDraft(angleStepDeg.toFixed(3));
            return;
        }
        updateAngleStep(parsed);
    };

    const commitLengthStep = (): void => {
        const parsed = parseDraft(lengthStepDraft);
        if (parsed === null) {
            setLengthStepDraft(lengthStep.toFixed(4));
            return;
        }
        updateLengthStep(parsed);
    };

    const applyAllJointsDraft = (): void => {
        if (isEstopped) {
            syncTargetsWithCurrentRef.current = true;
            setJointTargets(current);
            setJointDrafts(current.map((v) => formatDeg(v)));
            setAllJointsDraft("");
            setStatus("blocked: estop active");
            return;
        }
        const parts = allJointsDraft
            .trim()
            .split(/[\s,]+/)
            .map((s) => Number(s))
            .filter((n) => Number.isFinite(n));
        if (parts.length === 0) {
            setAllJointsDraft(jointTargets.map((v) => fixedNoNegZero(v, 2)).join(" "));
            return;
        }
        const filled: number[] = Array.from({ length: pluginJointCount }, (_, i) => parts[i] ?? jointTargets[i] ?? 0);
        syncTargetsWithCurrentRef.current = false;
        jointTargetsRef.current = filled;
        setJointTargets(filled);
        setJointDrafts(filled.map((v) => formatDeg(v)));
        setAllJointsDraft(filled.map((v) => fixedNoNegZero(v, 2)).join(" "));
        enqueueTask(async () => sendJointTarget(filled));
    };

    const applyEeMatrixDraft = (): void => {
        const rows = eeMatrixDraft
            .trim()
            .split("\n")
            .map((line) => line.trim().split(/\s+/).map((s) => Number(s)));
        if (rows.length !== 4 || rows.some((r) => r.length !== 4 || r.some((n) => !Number.isFinite(n)))) {
            // Reset to last known good value from state
            if (eeTarget !== null) {
                setEeMatrixDraft(eeTarget.map((row) => row.map((v) => fixedNoNegZero(v, 4)).join("  ")).join("\n"));
            }
            setStatus("EE matrix must be 4×4 numbers");
            return;
        }
        enqueueTask(async () => {
            const result = await props.api.postEeTarget(props.chainId, rows);
            setStatus(result.message);
        });
    };

    const onEnterCommit = (commit: () => void): ((event: KeyboardEvent<HTMLInputElement>) => void) =>
        (event) => {
            if (event.key === "Enter") {
                commit();
                (event.currentTarget as HTMLInputElement).blur();
            }
        };

    return (
        <section className="panel teach-panel">
            <div className="teach-config-grid">
                <div className="teach-config-item">
                    <label htmlFor={`${props.chainId}-angle-step`}>Angle Step (°)</label>
                    <div className="teach-config-control">
                        <input
                            id={`${props.chainId}-angle-step`}
                            className="teach-slider"
                            type="range"
                            min={0}
                            max={10}
                            step={0.1}
                            value={angleStepDeg}
                            onChange={(event) => updateAngleStep(Number(event.target.value))}
                        />
                        <input
                            className="num-input"
                            type="text"
                            value={angleStepDraft}
                            onFocus={() => {
                                activeInputRef.current = `${props.chainId}-angle-step`;
                            }}
                            onChange={(event) => setAngleStepDraft(event.target.value)}
                            onBlur={() => {
                                activeInputRef.current = null;
                                commitAngleStep();
                            }}
                            onKeyDown={onEnterCommit(commitAngleStep)}
                        />
                    </div>
                </div>

                <div className="teach-config-item">
                    <label htmlFor={`${props.chainId}-length-step`}>Length Step (m)</label>
                    <div className="teach-config-control">
                        <input
                            id={`${props.chainId}-length-step`}
                            className="teach-slider"
                            type="range"
                            min={0}
                            max={0.05}
                            step={0.0001}
                            value={lengthStep}
                            onChange={(event) => updateLengthStep(Number(event.target.value))}
                        />
                        <input
                            className="num-input"
                            type="text"
                            value={lengthStepDraft}
                            onFocus={() => {
                                activeInputRef.current = `${props.chainId}-length-step`;
                            }}
                            onChange={(event) => setLengthStepDraft(event.target.value)}
                            onBlur={() => {
                                activeInputRef.current = null;
                                commitLengthStep();
                            }}
                            onKeyDown={onEnterCommit(commitLengthStep)}
                        />
                    </div>
                </div>

                <div className="teach-config-item">
                    <label htmlFor={`${props.chainId}-frame`}>Cartesian Frame</label>
                    <div className="teach-config-control">
                        <select id={`${props.chainId}-frame`} value={frame} onChange={(event) => setFrame(event.target.value as CartesianFrame)}>
                            <option value="tool">End-Effector</option>
                            <option value="world">World</option>
                        </select>
                    </div>
                </div>
            </div>

            <div className="teach-control-layout">
                <div className="control-grid">
                    <h4>Joint Control</h4>
                    {jointTargets.map((targetValue, index) => (
                        <div key={`${props.chainId}-joint-${index}`} className="control-row joint-control-row">
                            <span className="joint-axis-tag">J{index + 1}</span>
                            <input
                                className="num-input"
                                type="text"
                                value={jointDrafts[index] ?? fixedNoNegZero(targetValue, 2)}
                                onFocus={() => {
                                    syncTargetsWithCurrentRef.current = false;
                                    activeInputRef.current = `${props.chainId}-joint-${index}`;
                                }}
                                onChange={(event) => onJointInputChange(index, event.target.value)}
                                onBlur={() => {
                                    activeInputRef.current = null;
                                    applyJointInput(index);
                                }}
                                onKeyDown={onEnterCommit(() => applyJointInput(index))}
                            />
                            <span className="joint-readback joint-readback-fixed">
                                <span className="joint-readback-half">Cur: {formatDeg(current[index] ?? 0)}</span>
                                <span className="joint-readback-half">Err: {formatDeg(targetValue - (current[index] ?? 0))}</span>
                            </span>
                            <button disabled={isEstopped} {...holdEvents(() => applyJointDelta(index, -1), syncJointTargetToCurrent, primeJointTargetsFromCurrent)}>-</button>
                            <button disabled={isEstopped} {...holdEvents(() => applyJointDelta(index, 1), syncJointTargetToCurrent, primeJointTargetsFromCurrent)}>+</button>
                        </div>
                    ))}
                    <div className="control-row" style={{ marginTop: "6px", width: "462px" }}>
                        <span className="joint-axis-tag" style={{ fontSize: "1em" }}>All</span>
                        <input
                            className="num-input"
                            type="text"
                            placeholder={jointTargets.map((v) => fixedNoNegZero(v, 2)).join(" ")}
                            value={allJointsDraft}
                            onFocus={() => {
                                syncTargetsWithCurrentRef.current = false;
                                activeInputRef.current = `${props.chainId}-all-joints`;
                                if (allJointsDraft === "") {
                                    setAllJointsDraft(jointTargets.map((v) => fixedNoNegZero(v, 2)).join(" "));
                                }
                            }}
                            onChange={(event) => setAllJointsDraft(event.target.value)}
                            onBlur={() => {
                                activeInputRef.current = null;
                                applyAllJointsDraft();
                            }}
                            onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                    applyAllJointsDraft();
                                    (event.currentTarget as HTMLInputElement).blur();
                                }
                            }}
                            style={{ flex: 1, minWidth: 0 }}
                        />
                        {/* Spacer matching the +/- button area so the input aligns with "+ buttons" above */}
                        <span style={{ display: "inline-block", width: "26px", flexShrink: 0 }} />
                    </div>
                </div>

                <div className="control-grid">
                    <h4>Cartesian Jog</h4>
                    {CARTESIAN_AXES.map((axisLabel, axis) => (
                        <div key={`${props.chainId}-cart-${axis}`} className="control-row">
                            <span className="joint-axis-tag">{axisLabel}</span>
                            <button {...holdEvents(
                                () => {
                                    // Enable joint-display sync so inputs track
                                    // the robot during cartesian jog.
                                    syncTargetsWithCurrentRef.current = true;
                                    isJointHoldRef.current = false;
                                    enqueueTask(async () => {
                                        // Guard: skip if button was released before this
                                        // queued task had a chance to run. This prevents
                                        // accumulated promise-chain tasks from continuing
                                        // to fire cartesian commands after button release.
                                        if (!holdActiveRef.current) return;
                                        await sendCartesian(axis, -1);
                                    });
                                },
                                onCartesianRelease
                            )}>-</button>
                            <button {...holdEvents(
                                () => {
                                    syncTargetsWithCurrentRef.current = true;
                                    isJointHoldRef.current = false;
                                    enqueueTask(async () => {
                                        if (!holdActiveRef.current) return;
                                        await sendCartesian(axis, 1);
                                    });
                                },
                                onCartesianRelease
                            )}>+</button>
                        </div>
                    ))}
                </div>
            </div>

            <div className="control-grid">
                <h4>EE Target (World)</h4>
                <textarea
                    className="num-input"
                    rows={4}
                    style={{ fontSize: "0.82rem", resize: "vertical", width: "100%", whiteSpace: "pre" }}
                    value={eeMatrixDraft}
                    placeholder={"1.0000  0.0000  0.0000  0.0000\n0.0000  1.0000  0.0000  0.0000\n0.0000  0.0000  1.0000  0.0000\n0.0000  0.0000  0.0000  1.0000"}
                    onFocus={() => { eeMatrixFocusedRef.current = true; }}
                    onChange={(event) => setEeMatrixDraft(event.target.value)}
                    onBlur={() => {
                        if (eeMatrixFocusedRef.current) {
                            eeMatrixFocusedRef.current = false;
                            applyEeMatrixDraft();
                        }
                    }}
                    onKeyDown={(event) => {
                        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                            eeMatrixFocusedRef.current = false;
                            applyEeMatrixDraft();
                            (event.currentTarget as HTMLTextAreaElement).blur();
                        }
                    }}
                />
                <p style={{ fontSize: "0.7em", margin: "2px 0", color: "#888" }}>
                    4×4 homogeneous matrix, space-separated. Ctrl+Enter or blur to apply.
                </p>
            </div>

            <p className="status-text">Status: {status}</p>
        </section>
    );
}
