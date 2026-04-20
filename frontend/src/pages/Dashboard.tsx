import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Plus, Settings, X } from "lucide-react";
import { Responsive, WidthProvider, type Layout, type Layouts } from "react-grid-layout";

import { ArmControlPanel } from "../components/ArmControlPanel";
import { CameraPanel } from "../components/CameraPanel";
import { EStopBar } from "../components/EStopBar";
import { JointPanel } from "../components/JointPanel";
import { PluginModePanel } from "../components/PluginModePanel";
import { Robot3DPanel } from "../components/Robot3DPanel";
import { ApiClient } from "../services/apiClient";
import { connectStateWS } from "../services/wsClient";
import { useHmiStore } from "../stores/robotStore";
import type { ChainId } from "../types/protocol";

const ResponsiveGridLayout = WidthProvider(Responsive);

type PanelKind = "camera" | "joint" | "teach" | "urdf";

interface DashboardPanel {
    id: string;
    kind: PanelKind;
    chainId?: ChainId;
    cameraName?: string;
}

interface StoredDashboardState {
    panels?: DashboardPanel[];
    layouts?: Layouts;
    panelCounter?: number;
    settingsWindow?: {
        visible?: boolean;
        x?: number;
        y?: number;
    };
}

const STORAGE_KEY = "ohmi.dashboard.layout.v3";
const BREAKPOINTS = { lg: 1200, md: 900, sm: 0 };
const COLS = { lg: 12, md: 8, sm: 1 };
const DEFAULT_SETTINGS_WINDOW_POS = { x: 24, y: 90 };

const humanize = (text: string): string => text.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());

const createDefaultPanels = (chainIds: string[], cameraNames: string[]): DashboardPanel[] => {
    const panels: DashboardPanel[] = [];
    if (chainIds.length > 0) {
        panels.push({ id: "teach:1", kind: "teach", chainId: chainIds[0] });
        panels.push({ id: "joint:2", kind: "joint", chainId: chainIds[0] });
    }
    if (cameraNames.length > 0) {
        panels.push({ id: "camera:3", kind: "camera", cameraName: cameraNames[0] });
    }
    panels.push({ id: "urdf:4", kind: "urdf" });
    return panels;
};

const panelDefaultSize = (kind: PanelKind): { w: number; h: number; minW: number; minH: number } => {
    if (kind === "urdf") {
        return { w: 8, h: 13, minW: 4, minH: 8 };
    }
    if (kind === "teach") {
        return { w: 6, h: 12, minW: 4, minH: 8 };
    }
    return { w: 5, h: 10, minW: 3, minH: 6 };
};

const createSequentialLayout = (panelIds: string[], panelMap: Record<string, DashboardPanel>, cols: number): Layout[] => {
    let cursorX = 0;
    let cursorY = 0;
    let currentRowHeight = 0;

    return panelIds
        .filter((id) => panelMap[id])
        .map((id) => {
            const panel = panelMap[id];
            const size = panelDefaultSize(panel.kind);
            const clampedW = Math.max(1, Math.min(cols, size.w));
            if (cursorX + clampedW > cols) {
                cursorX = 0;
                cursorY += currentRowHeight;
                currentRowHeight = 0;
            }
            const next: Layout = {
                i: id,
                x: cursorX,
                y: cursorY,
                w: clampedW,
                h: size.h,
                minW: Math.min(cols, size.minW),
                minH: size.minH,
            };
            cursorX += clampedW;
            currentRowHeight = Math.max(currentRowHeight, size.h);
            return next;
        });
};

const fillLayoutForPanels = (
    panelIds: string[],
    panelMap: Record<string, DashboardPanel>,
    existing: Layout[] | undefined,
    cols: number,
): Layout[] => {
    const defaults = createSequentialLayout(panelIds, panelMap, cols);
    const existingMap = new Map((existing ?? []).map((item) => [item.i, item]));
    return defaults.map((item) => {
        const prev = existingMap.get(item.i);
        if (!prev) {
            return item;
        }
        return {
            ...item,
            x: Math.max(0, Math.min(cols - 1, prev.x)),
            y: Math.max(0, prev.y),
            w: Math.max(1, Math.min(cols, prev.w)),
            h: Math.max(item.minH ?? 1, prev.h),
        };
    });
};

const buildLayouts = (
    panelIds: string[],
    panelMap: Record<string, DashboardPanel>,
    existing?: Layouts,
): Layouts => ({
    lg: fillLayoutForPanels(panelIds, panelMap, existing?.lg, COLS.lg),
    md: fillLayoutForPanels(panelIds, panelMap, existing?.md, COLS.md),
    sm: fillLayoutForPanels(panelIds, panelMap, existing?.sm, COLS.sm),
});

export function Dashboard(): JSX.Element {
    const profile = useHmiStore((s) => s.profile);
    const state = useHmiStore((s) => s.state);
    const setState = useHmiStore((s) => s.setState);
    const apiBase = profile?.apiBase;
    const wsBase = profile?.wsBase;

    const [panels, setPanels] = useState<DashboardPanel[]>([]);
    const [layouts, setLayouts] = useState<Layouts>({ lg: [], md: [], sm: [] });
    const [showAddMenu, setShowAddMenu] = useState(false);
    const [showSettingsWindow, setShowSettingsWindow] = useState(false);
    const [panelCounter, setPanelCounter] = useState(1);
    const [settingsWindowPos, setSettingsWindowPos] = useState(DEFAULT_SETTINGS_WINDOW_POS);
    const [layoutHydrated, setLayoutHydrated] = useState(false);
    const [wsReconnectKey, setWsReconnectKey] = useState(0);
    const settingsDragRef = useRef<{ dragX: number; dragY: number } | null>(null);

    const api = useMemo(() => {
        if (!profile) {
            return null;
        }
        return new ApiClient(profile);
    }, [apiBase]);

    useEffect(() => {
        if (!profile) {
            return;
        }
        const subscription = connectStateWS(profile, setState);
        return () => subscription.close();
    }, [wsBase, setState, wsReconnectKey]);

    const chainIds = useMemo(
        () => (profile?.chains?.length ? profile.chains : Object.keys(state?.chains ?? {})),
        [profile?.chains, state?.chains],
    );
    const cameraNames = useMemo(
        () => (profile?.cameraNames?.length ? profile.cameraNames : []),
        [profile?.cameraNames],
    );
    const chainNameMap = profile?.chainNameMap ?? {};
    const cameraNameMap = profile?.cameraNameMap ?? {};
    const chainLabel = (chainId: string): string => chainNameMap[chainId] ?? humanize(chainId);
    const cameraLabel = (cameraId: string): string => cameraNameMap[cameraId] ?? humanize(cameraId);

    const panelMap = useMemo(() => Object.fromEntries(panels.map((panel) => [panel.id, panel] as const)), [panels]);
    const panelIds = useMemo(() => panels.map((panel) => panel.id), [panels]);

    useEffect(() => {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        let stored: StoredDashboardState = {};
        if (raw) {
            try {
                stored = JSON.parse(raw) as StoredDashboardState;
            } catch {
                stored = {};
            }
        }

        const hasStoredPanels = Object.prototype.hasOwnProperty.call(stored, "panels") && Array.isArray(stored.panels);
        const storedPanels: DashboardPanel[] = hasStoredPanels ? (stored.panels as DashboardPanel[]) : [];
        const validPanels: DashboardPanel[] = storedPanels
            .filter((panel): panel is DashboardPanel => {
                if (!panel || typeof panel !== "object") {
                    return false;
                }
                if (!["camera", "joint", "teach", "urdf"].includes(panel.kind)) {
                    return false;
                }
                return typeof panel.id === "string" && panel.id.length > 0;
            })
            .map((panel) => {
                const normalized: DashboardPanel = {
                    id: panel.id,
                    kind: panel.kind,
                    chainId: panel.chainId,
                    cameraName: panel.cameraName,
                };
                if (panel.kind === "camera") {
                    return {
                        ...normalized,
                        cameraName: cameraNames.includes(panel.cameraName ?? "") ? panel.cameraName : cameraNames[0],
                    };
                }
                if (panel.kind === "joint" || panel.kind === "teach") {
                    return {
                        ...normalized,
                        chainId: chainIds.includes(panel.chainId ?? "") ? panel.chainId : chainIds[0],
                    };
                }
                return normalized;
            });

        const seededPanels: DashboardPanel[] = hasStoredPanels
            ? validPanels
            : createDefaultPanels(chainIds, cameraNames);

        const inferredCounter = Math.max(
            stored.panelCounter ?? 1,
            ...seededPanels
                .map((panel) => Number(panel.id.split(":")[1]))
                .filter((value) => Number.isFinite(value) && value > 0),
            1,
        );

        const nextPanelMap = Object.fromEntries(seededPanels.map((panel) => [panel.id, panel] as const));
        setPanels(seededPanels);
        setLayouts(buildLayouts(seededPanels.map((panel) => panel.id), nextPanelMap, stored.layouts));
        setPanelCounter(inferredCounter + 1);
        setShowSettingsWindow(Boolean(stored.settingsWindow?.visible));
        setSettingsWindowPos({
            x: Number.isFinite(stored.settingsWindow?.x) ? Number(stored.settingsWindow?.x) : DEFAULT_SETTINGS_WINDOW_POS.x,
            y: Number.isFinite(stored.settingsWindow?.y) ? Number(stored.settingsWindow?.y) : DEFAULT_SETTINGS_WINDOW_POS.y,
        });
        setLayoutHydrated(true);
    }, [cameraNames, chainIds]);

    useEffect(() => {
        if (!layoutHydrated) {
            return;
        }
        const payload: StoredDashboardState = {
            panels,
            layouts,
            panelCounter,
            settingsWindow: {
                visible: showSettingsWindow,
                x: settingsWindowPos.x,
                y: settingsWindowPos.y,
            },
        };
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    }, [layoutHydrated, panels, layouts, panelCounter, showSettingsWindow, settingsWindowPos]);

    const syncPanelsAndLayouts = (nextPanels: DashboardPanel[]): void => {
        const nextPanelMap = Object.fromEntries(nextPanels.map((panel) => [panel.id, panel] as const));
        setPanels(nextPanels);
        setLayouts((prev) => buildLayouts(nextPanels.map((panel) => panel.id), nextPanelMap, prev));
    };

    const addPanel = (kind: PanelKind): void => {
        const id = `${kind}:${panelCounter}`;
        const nextPanel: DashboardPanel =
            kind === "camera"
                ? { id, kind, cameraName: cameraNames[0] }
                : kind === "joint" || kind === "teach"
                    ? { id, kind, chainId: chainIds[0] }
                    : { id, kind };
        const nextPanels = [...panels, nextPanel];
        syncPanelsAndLayouts(nextPanels);
        setPanelCounter((prev) => prev + 1);
        setShowAddMenu(false);
    };

    const closePanel = (id: string): void => {
        const nextPanels = panels.filter((panel) => panel.id !== id);
        syncPanelsAndLayouts(nextPanels);
    };

    const setPanelChain = (id: string, chainId: ChainId): void => {
        if (!chainIds.includes(chainId)) {
            return;
        }
        setPanels((prev) => prev.map((panel) => (panel.id === id ? { ...panel, chainId } : panel)));
    };

    const setPanelCamera = (id: string, cameraName: string): void => {
        if (!cameraNames.includes(cameraName)) {
            return;
        }
        setPanels((prev) => prev.map((panel) => (panel.id === id ? { ...panel, cameraName } : panel)));
    };

    const resetLayout = (): void => {
        const defaults = createDefaultPanels(chainIds, cameraNames);
        const nextPanelMap = Object.fromEntries(defaults.map((panel) => [panel.id, panel] as const));
        setPanels(defaults);
        setLayouts(buildLayouts(defaults.map((panel) => panel.id), nextPanelMap));
        setPanelCounter(5);
    };

    const startSettingsWindowDrag = (event: ReactMouseEvent<HTMLDivElement>): void => {
        event.preventDefault();
        settingsDragRef.current = {
            dragX: event.clientX - settingsWindowPos.x,
            dragY: event.clientY - settingsWindowPos.y,
        };

        const onMove = (moveEvent: MouseEvent): void => {
            if (!settingsDragRef.current) {
                return;
            }
            setSettingsWindowPos({
                x: Math.max(6, moveEvent.clientX - settingsDragRef.current.dragX),
                y: Math.max(6, moveEvent.clientY - settingsDragRef.current.dragY),
            });
        };

        const onUp = (): void => {
            settingsDragRef.current = null;
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
        };

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    };

    const panelLabel = (panel: DashboardPanel): string => {
        if (panel.kind === "urdf") {
            return "URDF View";
        }
        if (panel.kind === "camera") {
            return "Camera";
        }
        if (panel.kind === "joint") {
            return "Joint Snapshot";
        }
        return "Teach Panel";
    };

    const renderPanel = (panel: DashboardPanel): JSX.Element => {
        if (panel.kind === "camera") {
            return <CameraPanel cameraName={panel.cameraName ?? cameraNames[0]} />;
        }
        if (panel.kind === "joint") {
            return <JointPanel chainId={panel.chainId ?? chainIds[0]} />;
        }
        if (panel.kind === "teach") {
            if (!api) {
                return <section className="panel"><p>Loading profile...</p></section>;
            }
            return <ArmControlPanel chainId={panel.chainId ?? chainIds[0]} api={api} />;
        }
        const teachChainIds = panels.filter((p) => p.kind === "teach").map((p) => p.chainId ?? chainIds[0]);
        return <Robot3DPanel activeChainIds={teachChainIds.length > 0 ? teachChainIds : undefined} />;
    };

    if (!profile || !api) {
        return <main className="dashboard"><p>Loading profile...</p></main>;
    }

    return (
        <main className="dashboard">
            <section className="safety-fixed">
                <EStopBar api={api} />
            </section>

            <div className="floating-actions floating-actions-top">
                <button className="toolbar-button icon-button" title="Add panel" onClick={() => setShowAddMenu((prev) => !prev)}>
                    <Plus size={18} strokeWidth={2.2} aria-hidden="true" />
                </button>
                {showAddMenu ? (
                    <div className="floating-popover">
                        <button className="menu-item" onClick={() => addPanel("teach")}>Teach Panel</button>
                        <button className="menu-item" onClick={() => addPanel("joint")}>Joint Snapshot</button>
                        <button className="menu-item" onClick={() => addPanel("camera")}>Camera</button>
                        <button className="menu-item" onClick={() => addPanel("urdf")}>URDF</button>
                    </div>
                ) : null}
            </div>

            <div className="floating-actions floating-actions-bottom">
                <button
                    className="toolbar-button icon-button"
                    title="Settings"
                    onClick={() => setShowSettingsWindow((prev) => !prev)}
                >
                    <Settings size={18} strokeWidth={2.2} aria-hidden="true" />
                </button>
            </div>

            {showSettingsWindow ? (
                <div
                    className="plugin-floating-window"
                    style={{ left: `${settingsWindowPos.x}px`, top: `${settingsWindowPos.y}px` }}
                >
                    <div className="plugin-floating-header" onMouseDown={startSettingsWindowDrag}>
                        <span>Settings</span>
                        <div className="settings-header-actions" onMouseDown={(event) => event.stopPropagation()}>
                            <button className="close-panel-btn icon-only-btn" onClick={() => setShowSettingsWindow(false)}>
                                <X size={16} aria-hidden="true" />
                            </button>
                        </div>
                    </div>
                    <div className="plugin-floating-content">
                        <PluginModePanel api={api} onResetLayout={resetLayout} onApplyRefresh={() => setWsReconnectKey((k) => k + 1)} />
                    </div>
                </div>
            ) : null}

            <ResponsiveGridLayout
                className="layout-grid"
                draggableHandle=".drag-handle"
                breakpoints={BREAKPOINTS}
                cols={COLS}
                layouts={layouts}
                margin={[12, 12]}
                rowHeight={24}
                resizeHandles={["sw", "nw", "se", "ne"]}
                onLayoutChange={(_currentLayout: Layout[], allLayouts: Layouts) => setLayouts(allLayouts)}
            >
                {panels.map((panel) => (
                    <div key={panel.id} className="layout-cell">
                        <div className="panel-shell">
                            <div className="panel-shell-toolbar drag-handle">
                                <span>{panelLabel(panel)}</span>
                                <div className="panel-shell-controls" onMouseDown={(event) => event.stopPropagation()}>
                                    {panel.kind === "teach" || panel.kind === "joint" ? (
                                        <select
                                            value={panel.chainId ?? chainIds[0]}
                                            onChange={(event) => setPanelChain(panel.id, event.target.value)}
                                        >
                                            {chainIds.map((chainId) => (
                                                <option key={`${panel.id}-${chainId}`} value={chainId}>{chainLabel(chainId)}</option>
                                            ))}
                                        </select>
                                    ) : null}
                                    {panel.kind === "camera" ? (
                                        <select
                                            value={panel.cameraName ?? cameraNames[0]}
                                            onChange={(event) => setPanelCamera(panel.id, event.target.value)}
                                        >
                                            {cameraNames.map((cameraName) => (
                                                <option key={`${panel.id}-${cameraName}`} value={cameraName}>{cameraLabel(cameraName)}</option>
                                            ))}
                                        </select>
                                    ) : null}
                                    <button className="close-panel-btn icon-only-btn" title="Close panel" onClick={() => closePanel(panel.id)}>
                                        <X size={14} aria-hidden="true" />
                                    </button>
                                </div>
                            </div>
                            <div className="panel-shell-content">
                                {renderPanel(panel)}
                            </div>
                        </div>
                    </div>
                ))}
            </ResponsiveGridLayout>
        </main>
    );
}
