import type { ReactNode } from "react";

import { Icon } from "./Icon";
import "./workflows.css";

const statusTone: Record<string, string> = {
  accepted: "success",
  analyzed: "success",
  extracted: "accent",
  needs_changes: "warning",
  needs_manual_review: "warning",
  rejected: "danger",
  reviewed: "success",
  submitted: "accent",
  under_review: "accent",
  uploaded: "neutral"
};

export function WorkflowHeader({ title, description, children, level = 2 }: {
  title: string;
  description?: string;
  children?: ReactNode;
  level?: 1 | 2;
}) {
  const Heading = level === 1 ? "h1" : "h2";
  return (
    <header className="workflow-heading">
      <div>
        <Heading>{title}</Heading>
        {description && <p>{description}</p>}
      </div>
      {children && <div className="workflow-heading-actions">{children}</div>}
    </header>
  );
}

export function WorkflowStatus({ status, children }: { status: string; children: ReactNode }) {
  return <strong className={`workflow-status workflow-status--${statusTone[status] ?? "neutral"}`}>{children}</strong>;
}

export function WorkflowEmpty({ title, description, icon = "inbox" }: {
  title: string;
  description?: string;
  icon?: "inbox" | "file" | "search" | "folder";
}) {
  return (
    <div className="workflow-empty">
      <span className="workflow-mark"><Icon name={icon} /></span>
      <strong>{title}</strong>
      {description && <p>{description}</p>}
    </div>
  );
}

export function WorkflowNotice({ children, variant = "info" }: {
  children: ReactNode;
  variant?: "info" | "success";
}) {
  return (
    <div className={`workflow-notice workflow-notice--${variant}`} role="status">
      <Icon name={variant === "success" ? "check" : "info"} />
      <div>{children}</div>
    </div>
  );
}
