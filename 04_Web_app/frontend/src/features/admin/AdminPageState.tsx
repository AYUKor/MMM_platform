import { useEffect, useRef, type PropsWithChildren, type ReactNode } from "react";
import { Button } from "../../shared/ui/Button";
import styles from "./admin.module.css";

export function AdminPage({
  eyebrow,
  title,
  description,
  actions,
  children,
}: PropsWithChildren<{
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}>) {
  return (
    <div className={styles.adminPage}>
      <header className={styles.pageHeader}>
        <div>
          <span className={styles.eyebrow}>{eyebrow}</span>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {actions ? <div className={styles.headerActions}>{actions}</div> : null}
      </header>
      {children}
    </div>
  );
}

export function AdminLoading({ label }: { label: string }) {
  return (
    <div className={styles.loadingGrid} role="status" aria-busy="true">
      <span /><span /><span />
      <span className="sr-only">{label}</span>
    </div>
  );
}

function statusOf(error: unknown): number | null {
  if (!error || typeof error !== "object") return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === "number" ? status : null;
}

export function AdminError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status = statusOf(error);
  const unsupported = Boolean(error && typeof error === "object" &&
    (error as { code?: unknown }).code === "UNSUPPORTED_AUTH_ADMIN_CONTRACT");
  const displayText = error && typeof error === "object" &&
    typeof (error as { displayText?: unknown }).displayText === "string"
    ? String((error as { displayText: string }).displayText)
    : error instanceof Error && error.name === "AuthAdminError" && error.message.trim()
      ? error.message
      : null;
  const title = status === 403
    ? "Недостаточно прав"
    : unsupported
      ? "Формат ответа не поддерживается"
      : status === 404
        ? "Запись не найдена"
        : status === 409
          ? "Изменение невозможно"
          : "Раздел временно недоступен";
  const description = status === 403
    ? "Ваша сессия активна, но для этого раздела нет необходимого разрешения."
    : displayText ?? (unsupported
      ? "Сервис вернул неподдерживаемую версию данных."
      : "Не удалось получить данные. Повторите попытку.");
  return (
    <section className={styles.pageState} role="alert">
      <span>Состояние раздела</span>
      <h2>{title}</h2>
      <p>{description}</p>
      {status !== 403 && status !== 404 ? <Button onClick={onRetry}>Повторить</Button> : null}
    </section>
  );
}

export function EmptyAdminState({ title, description }: { title: string; description: string }) {
  return (
    <section className={styles.emptyState}>
      <span aria-hidden="true">0</span>
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}

export function Modal({
  title,
  description,
  onClose,
  children,
}: PropsWithChildren<{ title: string; description?: string; onClose: () => void }>) {
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    panel?.querySelector<HTMLElement>("button, input, select, textarea")?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab" || !panel) return;
      const focusable = [...panel.querySelectorAll<HTMLElement>(
        "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])",
      )];
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="admin-modal-title" ref={panelRef}>
        <div className={styles.modalHeader}>
          <div>
            <h2 id="admin-modal-title">{title}</h2>
            {description ? <p>{description}</p> : null}
          </div>
          <button type="button" className={styles.iconButton} onClick={onClose} aria-label="Закрыть">×</button>
        </div>
        {children}
      </div>
    </div>
  );
}
