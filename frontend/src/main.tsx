import React from "react";
import ReactDOM from "react-dom/client";

import { Dashboard } from "./pages/Dashboard";
import { loadProfile } from "./services/config";
import { useHmiStore } from "./stores/robotStore";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import "./styles.css";

async function bootstrap(): Promise<void> {
  const profile = await loadProfile();
  useHmiStore.getState().setProfile(profile);

  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <Dashboard />
    </React.StrictMode>,
  );
}

void bootstrap();
