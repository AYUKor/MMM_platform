import { Link, useLocation } from "react-router-dom";
import type { AppPermission } from "../../app/access";
import { useAuth } from "../../features/auth/AuthProvider";
import styles from "./app-shell.module.css";

const primaryItems: { to: string; label: string; icon: string; permission: AppPermission }[] = [
  { to: "/", label: "Главная", icon: "M", permission: "workspace.read" },
  { to: "/calculations/new", label: "Новый расчёт", icon: "+", permission: "calculation.create" },
  { to: "/calculations", label: "История расчетов", icon: "R", permission: "calculation.read" },
  { to: "/model", label: "Модель", icon: "O", permission: "model.read" },
  { to: "/help", label: "Справка", icon: "?", permission: "help.read" },
];

const adminItems: { to: string; label: string; icon: string; permission: AppPermission }[] = [
  { to: "/admin/users", label: "Пользователи", icon: "U", permission: "admin.users.read" },
  { to: "/admin/roles", label: "Роли", icon: "R", permission: "admin.users.read" },
  { to: "/admin/system", label: "Система", icon: "S", permission: "admin.system.read" },
  { to: "/admin/audit", label: "Журнал действий", icon: "A", permission: "admin.audit.read" },
];

function NavItem({ to, label, icon }: { to: string; label: string; icon: string }) {
  const { pathname } = useLocation();
  const normalizedPath = pathname.replace(/\/+$/, "") || "/";
  const nestedCalculationsActive = to === "/calculations" && normalizedPath.startsWith("/calculations/") && normalizedPath !== "/calculations/new";
  const isActive = normalizedPath === to || nestedCalculationsActive;
  return (
    <Link to={to} aria-current={isActive ? "page" : undefined} className={isActive ? styles.activeNav : styles.navItem}>
      <span className={styles.navIcon} aria-hidden="true">{icon}</span>
      <span className={styles.navLabel}>{label}</span>
    </Link>
  );
}

export function Sidebar() {
  const auth = useAuth();
  const primary = primaryItems.filter((item) => auth.can(item.permission));
  const admin = adminItems.filter((item) => auth.can(item.permission));
  const user = auth.session?.user;
  return (
    <aside className={styles.sidebar} aria-label="Основная навигация">
      <div className={styles.brand}>
        <span className={styles.brandMark}>M</span>
        <span className={styles.brandCopy}><strong>MMM Forecast<br />&amp; Optimizer</strong><small>decision system</small></span>
      </div>
      <nav className={styles.nav} aria-label="Разделы продукта">
        {primary.map((item) => <NavItem key={`${item.to}-${item.label}`} to={item.to} label={item.label} icon={item.icon} />)}
      </nav>
      {admin.length > 0 ? (
        <div className={styles.adminSection}>
          <div className={styles.adminLabel}>Администрирование</div>
          {admin.map((item) => <NavItem key={item.to} to={item.to} label={item.label} icon={item.icon} />)}
        </div>
      ) : null}
      {user ? (
        <div className={styles.identity}>
          <span className={styles.identityMark}>{user.display_name.slice(0, 1).toLocaleUpperCase("ru-RU")}</span>
          <span className={styles.identityCopy}><strong>{user.display_name}</strong><small>{user.role.title}</small></span>
        </div>
      ) : null}
    </aside>
  );
}
