import type { PropsWithChildren } from "react";
import styles from "./ui.module.css";

interface StatusBadgeProps {
  tone?: "neutral" | "accent" | "warning" | "danger";
}

export function StatusBadge({
  tone = "neutral",
  children,
}: PropsWithChildren<StatusBadgeProps>) {
  return (
    <span className={`${styles.badge} ${styles[`badge-${tone}`]}`}>
      {children}
    </span>
  );
}
