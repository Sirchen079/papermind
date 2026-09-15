import React from "react";
import ReactDOM from "react-dom/client";
import WorkspaceRoot from "./WorkspaceRoot";
import "./design-tokens.css";
import "./index.css";
import "./workspace.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <WorkspaceRoot />
  </React.StrictMode>
);
