import type { ReactNode } from "react";

import { Icon } from "./Icon";

const admissionsUrl = "https://priem.mai.ru/";

function Brand() {
  return (
    <span className="brand">
      <span className="brand__words">
        <strong><span>MAI</span> Agent</strong>
        <small>Помощник МАИ</small>
      </span>
    </span>
  );
}

// Минимальная обёртка: шапка с брендом и содержимое (чат). Без аккаунтов и меню.
export function ChatShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell app-shell--agent">
      <header className="app-header">
        <div className="app-masthead">
          <span className="brand"><Brand /></span>
          <a href={admissionsUrl} target="_blank" rel="noreferrer" className="topbar-link">
            Сайт приёмной комиссии <Icon name="external" />
          </a>
        </div>
      </header>
      <div className="app-column">
        <main className="app-content">
          <div className="workspace-content workspace-content--agent">{children}</div>
        </main>
      </div>
    </div>
  );
}
