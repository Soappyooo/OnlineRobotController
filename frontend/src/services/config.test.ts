import { afterEach, describe, expect, it, vi } from "vitest";

import { loadProfile } from "./config";

afterEach(() => {
    vi.restoreAllMocks();
});

describe("loadProfile", () => {
    it("merges runtime plugin mode fields", async () => {
        const fetchMock = vi
            .spyOn(globalThis, "fetch")
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    apiBase: "http://127.0.0.1:8100/api",
                    wsBase: "ws://127.0.0.1:8100/api/ws",
                }),
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    appTitle: "Runtime",
                    mode: "simulation",
                    activePlugin: "ur5_shadow",
                    pluginOptions: ["mock", "ur5_shadow"],
                }),
            } as Response);

        const profile = await loadProfile();

        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(profile.appTitle).toBe("Runtime");
        expect(profile.mode).toBe("simulation");
        expect(profile.activePlugin).toBe("ur5_shadow");
        expect(profile.pluginOptions).toContain("ur5_shadow");
    });
});
