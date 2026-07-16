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
        {apiConfigured ? "Сервис настроен" : "Сервис не настроен"}
      </div>
      <ThemeSwitcher />
    </header>
  );
}
