import type { ReactNode } from "react";
import styles from "./ui.module.css";

interface PageHeaderProps {
  eyebrow: ReactNode;
  title: string;
  meta: ReactNode;
  actions?: ReactNode;
}

export function PageHeader({ eyebrow, title, meta, actions }: PageHeaderProps) {
  return (
    <header className={styles.pageHeader}>
      <div>
        <div className={styles.eyebrow}>{eyebrow}</div>
        <h1>{title}</h1>
        <div className={styles.pageMeta}>{meta}</div>
      </div>
      {actions ? <div className={styles.pageActions}>{actions}</div> : null}
    </header>
  );
}
