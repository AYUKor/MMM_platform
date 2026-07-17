import { Button } from "../../shared/ui/Button";
import { Link } from "react-router-dom";
import { navigationErrorCopy } from "./productNavigationModel";
import styles from "./product-navigation.module.css";

export function ProductNavigationLoading({ label }: { label: string }) {
  return (
    <div className={styles.loadingPage} role="status" aria-live="polite" aria-busy="true">
      <div className={styles.loadingHeader} aria-hidden="true">
        <span />
        <strong />
        <i />
      </div>
      <div className={styles.loadingStrip} aria-hidden="true">
        {Array.from({ length: 4 }, (_, index) => <span key={index} />)}
      </div>
      <div className={styles.loadingBody} aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function ProductNavigationPageState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const copy = navigationErrorCopy(error);
  return (
    <section className={styles.pageState} role="alert">
      <span className={styles.eyebrow}>Состояние раздела</span>
      <h1>{copy.title}</h1>
      <p>{copy.description}</p>
      <div className={styles.stateActions}>
        {copy.retryable ? <Button onClick={onRetry}>Повторить</Button> : null}
        <Link className={styles.secondaryLink} to="/">На главную</Link>
      </div>
    </section>
  );
}

export function RefreshNotice({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className={styles.refreshNotice} role="status">
      <span>{message}</span>
      <Button onClick={onRetry}>Повторить</Button>
    </div>
  );
}
