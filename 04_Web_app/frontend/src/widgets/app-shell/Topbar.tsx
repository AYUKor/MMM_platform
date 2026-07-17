import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { appEnv } from "../../shared/config/env";
import { isSyntheticReview } from "../../shared/config/review";
import { ThemeSwitcher } from "../../shared/ui/ThemeSwitcher";
import { useAuth } from "../../features/auth/AuthProvider";
import styles from "./app-shell.module.css";

export function Topbar() {
  const apiConfigured = appEnv.resultProvider === "http";
  const auth = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const user = auth.session?.user;
  const hasAdmin = auth.canAny(["admin.users.read", "admin.system.read", "admin.audit.read"]);
  useEffect(() => {
    function close(event: PointerEvent) {
      if (!profileRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  return (
    <header className={styles.topbar}>
      <div className={`${styles.systemState} ${apiConfigured ? styles.systemStateConfigured : ""}`} role="status">
        <span aria-hidden="true" />{apiConfigured ? "Сервис настроен" : "Сервис не настроен"}
      </div>
      {isSyntheticReview() ? <span className={styles.reviewBadge}>Демонстрационные данные</span> : null}
      <ThemeSwitcher />
      {user ? (
        <div className={styles.profile} ref={profileRef}>
          <button type="button" className={styles.profileButton} aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen((value) => !value)}>
            <span>{user.display_name.slice(0, 1).toLocaleUpperCase("ru-RU")}</span>
            <strong>{user.display_name}</strong>
          </button>
          {open ? (
            <div className={styles.profileMenu} role="menu">
              <div className={styles.profileSummary}><strong>{user.display_name}</strong><span>{user.role.title}</span><small>{user.email}</small></div>
              {hasAdmin ? <Link to="/admin" role="menuitem" onClick={() => setOpen(false)}>Администрирование</Link> : null}
              <button type="button" role="menuitem" onClick={async () => { setOpen(false); await auth.logout(); navigate("/login", { replace: true }); }}>Выйти</button>
            </div>
          ) : null}
        </div>
      ) : null}
    </header>
  );
}
