import { appEnv } from "../../shared/config/env";
import { ThemeSwitcher } from "../../shared/ui/ThemeSwitcher";
import styles from "./app-shell.module.css";

export function Topbar() {
  const apiConfigured = appEnv.resultProvider === "http";
  return (
    <header className={styles.topbar}>
      <div
        className={`${styles.systemState} ${apiConfigured ? styles.systemStateConfigured : ""}`}
        role="status"
      >
        <span aria-hidden="true" />
        {apiConfigured ? "API настроен" : "API не подключён"}
      </div>
      <ThemeSwitcher />
    </header>
  );
}
