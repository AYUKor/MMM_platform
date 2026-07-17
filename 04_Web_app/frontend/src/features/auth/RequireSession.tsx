import { Navigate, useLocation } from "react-router-dom";
import type { PropsWithChildren } from "react";
import type { AppPermission } from "../../app/access";
import { Button } from "../../shared/ui/Button";
import { PermissionDeniedPage } from "../../pages/PermissionDeniedPage";
import { bootstrapErrorCopy } from "./authModel";
import { useAuth } from "./AuthProvider";
import styles from "./auth.module.css";

export function SessionBootstrapState() {
  return (
    <main className={styles.bootstrapPage} aria-busy="true" aria-live="polite">
      <div className={styles.bootstrapCard}>
        <span className={styles.pulse} aria-hidden="true" />
        <p>Проверяем сессию…</p>
      </div>
    </main>
  );
}

export function RequireSession({ children }: PropsWithChildren) {
  const auth = useAuth();
  const location = useLocation();
  if (auth.status === "loading") return <SessionBootstrapState />;
  if (auth.status === "error") {
    const copy = bootstrapErrorCopy(auth.bootstrapError);
    return (
      <main className={styles.bootstrapPage}>
        <section className={styles.bootstrapError} role="alert">
          <span>Состояние входа</span>
          <h1>{copy.title}</h1>
          <p>{copy.description}</p>
          <Button onClick={() => { void auth.refreshSession(); }}>Повторить</Button>
        </section>
      </main>
    );
  }
  if (auth.status !== "authenticated") {
    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    const query = new URLSearchParams({ return_to: returnTo });
    return <Navigate to={`/login?${query.toString()}`} replace state={{ authNotice: auth.notice }} />;
  }
  return children;
}

export function RequirePermission({
  permission,
  children,
}: PropsWithChildren<{ permission: AppPermission }>) {
  const auth = useAuth();
  if (!auth.can(permission)) return <PermissionDeniedPage />;
  return children;
}
