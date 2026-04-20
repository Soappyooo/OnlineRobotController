import type { RobotState, RuntimeProfile } from "../types/protocol";

interface WsSubscription {
  close: () => void;
}

const RECONNECT_DELAY_MS = 800;

function toWebSocketBase(wsBase: string): string {
  if (wsBase.startsWith("ws://") || wsBase.startsWith("wss://")) {
    return wsBase;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${wsBase}`;
}

export function connectStateWS(profile: RuntimeProfile, onState: (state: RobotState) => void): WsSubscription {
  const wsBase = toWebSocketBase(profile.wsBase);
  const url = `${wsBase}/state`;

  let socket: WebSocket | null = null;
  let disposed = false;
  let reconnectTimer: number | null = null;

  const connect = (): void => {
    if (disposed) {
      return;
    }
    const ws = new WebSocket(url);
    socket = ws;
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as RobotState;
      onState(data);
    };
    ws.onclose = () => {
      if (disposed) {
        return;
      }
      reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
    };
  };

  connect();

  return {
    close: () => {
      disposed = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      if (socket && socket.readyState < WebSocket.CLOSING) {
        socket.close();
      }
    },
  };
}

export function connectCameraWS(
  profile: RuntimeProfile,
  cameraName: string,
  onFrame: (payload: { dataUrl: string | null; receiveFps: number | null; displayFps: number | null; frameAgeMs: number | null }) => void,
): WsSubscription {
  const wsBase = toWebSocketBase(profile.wsBase);
  const url = `${wsBase}/camera/${cameraName}`;

  let socket: WebSocket | null = null;
  let disposed = false;
  let reconnectTimer: number | null = null;

  const connect = (): void => {
    if (disposed) {
      return;
    }
    const ws = new WebSocket(url);
    socket = ws;
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as {
        data_url: string | null;
        receive_fps?: number;
        display_fps?: number;
        frame_age_ms?: number;
      };
      onFrame({
        dataUrl: data.data_url,
        receiveFps: typeof data.receive_fps === "number" ? data.receive_fps : null,
        displayFps: typeof data.display_fps === "number" ? data.display_fps : null,
        frameAgeMs: typeof data.frame_age_ms === "number" ? data.frame_age_ms : null,
      });
    };
    ws.onclose = () => {
      if (disposed) {
        return;
      }
      reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
    };
  };

  connect();

  return {
    close: () => {
      disposed = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      if (socket && socket.readyState < WebSocket.CLOSING) {
        socket.close();
      }
    },
  };
}
