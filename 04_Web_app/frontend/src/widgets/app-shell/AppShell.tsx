import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import styles from "./app-shell.module.css";

export function AppShell() {
  return (
    <div className={styles.appShell}>
      <a className={styles.skipLink} href="#main-content">
        Перейти к содержимому
      </a>
      <Sidebar />
      <div className={styles.workspace}>
        <Topbar />
        <main id="main-content" className={styles.main} tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
