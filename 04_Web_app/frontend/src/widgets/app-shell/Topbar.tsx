import { ThemeSwitcher } from "../../shared/ui/ThemeSwitcher";
import styles from "./app-shell.module.css";

export function Topbar() {
  return (
    <header className={styles.topbar}>
      <div className={styles.systemState} role="status">
        <span aria-hidden="true" />
        API не подключён
      </div>
      <ThemeSwitcher />
    </header>
  );
}
