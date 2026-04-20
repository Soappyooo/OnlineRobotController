import type { Ack, CartesianFrame, ChainId, ModeStatus, PluginCatalog, PluginConfigPayload, RuntimeProfile } from "../types/protocol";

export class ApiClient {
  public constructor(private readonly profile: RuntimeProfile) { }

  public async postEStop(trigger: boolean): Promise<Ack> {
    return this.post<Ack>("/robot/estop", { trigger });
  }

  public async postJointCommand(arm: ChainId, targetAnglesDeg: number[]): Promise<Ack> {
    return this.post<Ack>("/robot/joint-command", {
      arm,
      target_angles_deg: targetAnglesDeg,
    });
  }

  public async postCartesianJog(
    arm: ChainId,
    delta: number[],
    frame: CartesianFrame,
  ): Promise<Ack> {
    return this.post<Ack>("/robot/cartesian-jog", {
      arm,
      delta_xyzrpy: delta,
      frame,
    });
  }

  public async postEeTarget(chainId: ChainId, matrix: number[][]): Promise<Ack> {
    return this.post<Ack>(`/robot/ee-target/${chainId}`, { matrix });
  }

  public async getRobotMode(): Promise<ModeStatus> {
    return this.get<ModeStatus>("/robot/mode");
  }

  public async postRobotMode(mode: "real" | "simulation"): Promise<Ack> {
    return this.post<Ack>("/robot/mode", { mode });
  }

  public async getProfile(): Promise<Partial<RuntimeProfile>> {
    return this.get<Partial<RuntimeProfile>>("/profile");
  }

  public async getPluginCatalog(): Promise<PluginCatalog> {
    return this.get<PluginCatalog>("/plugins");
  }

  public async postPluginSelect(plugin: string): Promise<Ack> {
    return this.post<Ack>("/plugins/select", { plugin });
  }

  public async getPluginConfig(plugin: string): Promise<PluginConfigPayload> {
    return this.get<PluginConfigPayload>(`/plugins/config/${plugin}`);
  }

  public async putPluginConfig(plugin: string, payload: { config?: Record<string, unknown>; config_toml?: string }): Promise<Ack> {
    return this.put<Ack>(`/plugins/config/${plugin}`, payload);
  }

  private async get<T>(path: string): Promise<T> {
    const response = await fetch(`${this.profile.apiBase}${path}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    return response.json() as Promise<T>;
  }

  private async post<T>(path: string, payload: object): Promise<T> {
    const response = await fetch(`${this.profile.apiBase}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return response.json() as Promise<T>;
  }

  private async put<T>(path: string, payload: object): Promise<T> {
    const response = await fetch(`${this.profile.apiBase}${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return response.json() as Promise<T>;
  }
}
