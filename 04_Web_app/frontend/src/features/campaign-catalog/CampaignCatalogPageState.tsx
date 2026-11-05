import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import { campaignCatalogErrorCopy } from "./campaignCatalogErrors";
import styles from "./campaign-catalog.module.css";

export function CampaignCatalogPageState({
  error,
  onRetry,
  backLink = "/campaigns",
}: {
  error: unknown;
  onRetry: () => void;
  backLink?: string;
}) {
  const copy = campaignCatalogErrorCopy(error);
  return (
    <section className={styles.page}>
      <div className={`${styles.panel} ${styles.statePanel}`} role="alert">
        <div className={styles.eyebrow}>Каталог прошлых кампаний</div>
        <h2>{copy.title}</h2>
        <p>{copy.description}</p>
        <div className={styles.toolbar}>
          {copy.retryable ? <Button onClick={onRetry}>Повторить</Button> : null}
          <Link className={styles.back} to={backLink}>Все кампании</Link>
        </div>
      </div>
    </section>
  );
}
