import type { RuntimeProfile } from "../types/protocol";

const DEFAULT_PROFILE: RuntimeProfile = {
  appTitle: "Online Robot Controller",
  wsBase: "/api/ws",
  apiBase: "/api",
  urdfUrl: "",
  cameraNames: [],
  chains: [],
  chainNameMap: {},
  cameraNameMap: {},
  activePlugin: "",
  pluginOptions: [""],
  mode: "simulation",
  jointMap: {},
  jointOffsetsDeg: {},
  tipLinks: {},
};

export async function loadProfile(): Promise<RuntimeProfile> {
  let merged = DEFAULT_PROFILE;

  try {
    const response = await fetch("/profile.json", { cache: "no-cache" });
    if (response.ok) {
      const data = (await response.json()) as Partial<RuntimeProfile>;
      merged = {
        ...DEFAULT_PROFILE,
        ...data,
        cameraNames: data.cameraNames?.length ? data.cameraNames : DEFAULT_PROFILE.cameraNames,
        pluginOptions: data.pluginOptions?.length ? data.pluginOptions : DEFAULT_PROFILE.pluginOptions,
      };
    }
  } catch {
    merged = DEFAULT_PROFILE;
  }

  try {
    const runtimeResponse = await fetch(`${merged.apiBase}/profile`, { cache: "no-cache" });
    if (!runtimeResponse.ok) {
      return merged;
    }
    const runtimeData = (await runtimeResponse.json()) as Partial<RuntimeProfile>;
    return {
      ...merged,
      ...runtimeData,
      cameraNames: runtimeData.cameraNames?.length ? runtimeData.cameraNames : merged.cameraNames,
      pluginOptions: runtimeData.pluginOptions?.length ? runtimeData.pluginOptions : merged.pluginOptions,
    };
  } catch {
    return merged;
  }
}
