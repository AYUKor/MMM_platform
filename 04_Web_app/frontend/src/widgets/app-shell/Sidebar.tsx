import { NavLink } from "react-router-dom";
import { canAccessAdmin, currentAccess } from "../../app/access";
import styles from "./app-shell.module.css";

const primaryItems = [
  { to: "/", label: "Главная", icon: "M" },
  { to: "/calculations", label: "Новый расчёт", icon: "+" },
  { to: "/calculations", label: "Мои расчёты", icon: "R" },
  { to: "/model", label: "Модель", icon: "O" },
  { to: "/help", label: "Справка", icon: "?" },
];

const adminItems = [
  { to: "/admin/system", label: "Система", icon: "S" },
  { to: "/admin/jobs", label: "Очередь", icon: "Q" },
];

function NavItem({ to, label, icon, disabled = false }: {
  to: string;
  label: string;
  icon: string;
  disabled?: boolean;
}) {
  if (disabled) {
    return (
      <span className={styles.disabledNav} aria-disabled="true" title="Требуются подключённые admin permissions">
        <span className={styles.navIcon} aria-hidden="true">{icon}</span>
        <span className={styles.navLabel}>{label}</span>
      </span>
    );
  }
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) => isActive ? styles.activeNav : styles.navItem}
    >
      <span className={styles.navIcon} aria-hidden="true">{icon}</span>
      <span className={styles.navLabel}>{label}</span>
    </NavLink>
  );
}

export function Sidebar() {
  const adminAvailable = canAccessAdmin(currentAccess);
  return (
    <aside className={styles.sidebar} aria-label="Основная навигация">
      <div className={styles.brand}>
        <span className={styles.brandMark}>M</span>
        <span className={styles.brandCopy}>
          <strong>MMM Forecast<br />&amp; Optimizer</strong>
          <small>decision system</small>
        </span>
      </div>

      <nav className={styles.nav}>
        {primaryItems.map((item) => <NavItem key={`${item.to}-${item.label}`} {...item} />)}
      </nav>

      <div className={styles.adminSection}>
        <div className={styles.adminLabel}>Администрирование</div>
        {adminItems.map((item) => (
          <NavItem key={item.to} {...item} disabled={!adminAvailable} />
        ))}
      </div>

      <div className={styles.identity}>
        <span className={styles.identityMark}>—</span>
        <span className={styles.identityCopy}>
          <strong>Роль не подключена</strong>
          <small>auth pending</small>
        </span>
      </div>
    </aside>
  );
}
