import { useEffect, useMemo, useRef, useState, type UIEvent } from "react";

import type { ApiClient } from "../services/apiClient";
import { useHmiStore } from "../stores/robotStore";
import type { ModeStatus, PluginOption, RuntimeProfile } from "../types/protocol";

interface PluginModePanelProps {
    api: ApiClient;
    onApplyRefresh?: () => void;
    onResetLayout?: () => void;
}

const escapeHtml = (text: string): string =>
    text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

const highlightTomlValue = (raw: string): string => {
    let highlighted = escapeHtml(raw);
    highlighted = highlighted.replace(/"([^"\\]|\\.)*"/g, '<span class="toml-string">$&</span>');
    highlighted = highlighted.replace(/\b(true|false)\b/g, '<span class="toml-bool">$1</span>');
    highlighted = highlighted.replace(/\b-?\d+(?:\.\d+)?\b/g, '<span class="toml-number">$&</span>');
    return highlighted;
};

const highlightToml = (text: string): string => {
    const lines = text.split("\n");
    return lines
        .map((line) => {
            if (/^\s*#/.test(line)) {
                return `<span class="toml-comment">${escapeHtml(line)}</span>`;
            }

            const sectionMatch = line.match(/^(\s*)\[(.+?)\](\s*)$/);
            if (sectionMatch) {
                const [, leading, section, trailing] = sectionMatch;
                return `${escapeHtml(leading)}<span class="toml-section">[${escapeHtml(section)}]</span>${escapeHtml(trailing)}`;
            }

            const keyValueMatch = line.match(/^(\s*[A-Za-z0-9_.-]+\s*=)(.*)$/);
            if (keyValueMatch) {
                const [, keyPart, valuePart] = keyValueMatch;
                return `<span class="toml-key">${escapeHtml(keyPart)}</span>${highlightTomlValue(valuePart)}`;
            }

            return highlightTomlValue(line);
        })
        .join("\n");
};

export function PluginModePanel(props: PluginModePanelProps): JSX.Element {
    const profile = useHmiStore((s) => s.profile);
    const setProfile = useHmiStore((s) => s.setProfile);
    const [options, setOptions] = useState<PluginOption[]>([]);
    const [selected, setSelected] = useState(profile?.activePlugin ?? "mock");
    const [configText, setConfigText] = useState("[config]\n");
    const [modeStatus, setModeStatus] = useState<ModeStatus | null>(null);
    const [status, setStatus] = useState("idle");
    const previewRef = useRef<HTMLPreElement | null>(null);

    const modeText = useMemo(() => {
        if (!profile?.mode) {
            return "unknown";
        }
        return profile.mode;
    }, [profile?.mode]);

    const patchProfile = (patch: Partial<RuntimeProfile>): void => {
        const current = useHmiStore.getState().profile;
        if (!current) {
            return;
        }
        const next = {
            ...current,
            ...patch,
        };
        if (JSON.stringify(current) === JSON.stringify(next)) {
            return;
        }
        setProfile(next);
    };

    const refreshModeStatus = async (): Promise<ModeStatus | null> => {
        try {
            const mode = await props.api.getRobotMode();
            setModeStatus(mode);
            patchProfile({ mode: mode.mode });
            return mode;
        } catch {
            setModeStatus(null);
            return null;
        }
    };

    useEffect(() => {
        let cancelled = false;

        const load = async (): Promise<void> => {
            const catalog = await props.api.getPluginCatalog();
            if (cancelled) {
                return;
            }
            setOptions(catalog.available_plugins);
            setSelected(catalog.active_plugin);
            const cfg = await props.api.getPluginConfig(catalog.active_plugin);
            if (cancelled) {
                return;
            }
            setConfigText(cfg.config_toml || "[config]\n");

            const mode = await refreshModeStatus();
            if (cancelled) {
                return;
            }
            if (mode) {
                patchProfile({
                    activePlugin: catalog.active_plugin,
                    mode: mode.mode,
                });
            }
        };

        void load();
        return () => {
            cancelled = true;
        };
    }, [props.api]);

    const applyPlugin = async (): Promise<void> => {
        try {
            const cfgAck = await props.api.putPluginConfig(selected, { config_toml: configText });
            const switchAck = await props.api.postPluginSelect(selected);
            await refreshModeStatus();

            // Re-fetch full profile (includes updated urdfUrl, chains, etc.)
            const freshProfile = await props.api.getProfile();
            const current = useHmiStore.getState().profile;
            if (current) {
                setProfile({
                    ...current,
                    ...freshProfile,
                    cameraNames: freshProfile.cameraNames?.length ? freshProfile.cameraNames : current.cameraNames,
                    pluginOptions: freshProfile.pluginOptions?.length ? freshProfile.pluginOptions : current.pluginOptions,
                });
            }

            setStatus(`${cfgAck.message}; ${switchAck.message}`);
            props.onApplyRefresh?.();
        } catch {
            setStatus("invalid toml config");
        }
    };

    const onPluginChange = async (pluginName: string): Promise<void> => {
        setSelected(pluginName);
        const cfg = await props.api.getPluginConfig(pluginName);
        setConfigText(cfg.config_toml || "[config]\n");
    };

    const currentMode = modeStatus?.mode ?? modeText;
    const modeConnectedText = modeStatus ? (modeStatus.connected ? "connected" : "not connected") : "unknown";
    const highlightedToml = useMemo(() => highlightToml(configText), [configText]);
    const syncEditorScroll = (event: UIEvent<HTMLTextAreaElement>): void => {
        if (!previewRef.current) {
            return;
        }
        previewRef.current.scrollTop = event.currentTarget.scrollTop;
        previewRef.current.scrollLeft = event.currentTarget.scrollLeft;
    };

    return (
        <section className="panel">
            <p>Current mode: {currentMode} ({modeConnectedText})</p>
            <div className="field-row">
                <label htmlFor="plugin-select">Plugin</label>
                <select id="plugin-select" value={selected} onChange={(event) => void onPluginChange(event.target.value)}>
                    {options.map((item) => (
                        <option key={item.name} value={item.name}>
                            {item.name}
                        </option>
                    ))}
                </select>
                <button onClick={() => void applyPlugin()}>Apply Config &amp; Refresh</button>
                {props.onResetLayout ? <button onClick={props.onResetLayout}>Reset Layout</button> : null}
            </div>
            <div className="toml-editor-wrap">
                <pre
                    ref={previewRef}
                    className="toml-editor-preview"
                    aria-hidden="true"
                    dangerouslySetInnerHTML={{ __html: `${highlightedToml}\n` }}
                />
                <textarea
                    className="config-editor toml-editor-input"
                    value={configText}
                    onChange={(event) => setConfigText(event.target.value)}
                    onScroll={syncEditorScroll}
                    rows={12}
                    spellCheck={false}
                />
            </div>
            {modeStatus?.message ? <p className="status-text">Mode note: {modeStatus.message}</p> : null}
            <p className="status-text">Status: {status}</p>
        </section>
    );
}
