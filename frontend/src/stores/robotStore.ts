import { create } from "zustand";

import type { RobotState, RuntimeProfile } from "../types/protocol";

interface HmiStore {
  profile: RuntimeProfile | null;
  state: RobotState | null;
  setProfile: (profile: RuntimeProfile) => void;
  setState: (state: RobotState) => void;
}

export const useHmiStore = create<HmiStore>((set) => ({
  profile: null,
  state: null,
  setProfile: (profile) => set({ profile }),
  setState: (state) => set({ state }),
}));
