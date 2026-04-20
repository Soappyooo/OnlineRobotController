export type ChainId = string;
export type CartesianFrame = "tool" | "world";

export interface JointState {
  joint_id: number;
  angle_deg: number;
}

export interface ChainState {
  enabled: boolean;
  joints: JointState[];
  joint_targets?: JointState[] | null;
  ee_target: number[][] | null;
}

export interface RobotState {
  timestamp: number;
  e_stop: boolean;
  motion_enabled: boolean;
  chains: Record<string, ChainState>;
}

export interface Ack {
  ok: boolean;
  message: string;
}

export interface ModeStatus {
  mode: "real" | "simulation";
  available_modes: Array<"real" | "simulation">;
  connected: boolean;
  message?: string | null;
}

export interface RuntimeProfile {
  appTitle: string;
  wsBase: string;
  apiBase: string;
  urdfUrl: string;
  cameraNames: string[];
  chains?: string[];
  chainNameMap?: Record<string, string>;
  cameraNameMap?: Record<string, string>;
  activePlugin?: string;
  pluginOptions?: string[];
  mode?: "real" | "simulation";
  jointMap?: Record<string, string[]>;
  jointOffsetsDeg?: Record<string, number[]>;
  tipLinks?: Record<string, string>;
  commandHz?: number;
  stateHz?: number;
  cameraHz?: number;
  defaultAngleStepDeg?: number;
  defaultLengthStepM?: number;
}

export interface PluginOption {
  name: string;
  description: string;
}

export interface PluginCatalog {
  active_plugin: string;
  available_plugins: PluginOption[];
}

export interface PluginConfigPayload {
  plugin: string;
  config: Record<string, unknown>;
  config_toml: string;
}
