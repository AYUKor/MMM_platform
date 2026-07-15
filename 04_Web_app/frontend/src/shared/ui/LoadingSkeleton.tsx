import styles from "./ui.module.css";

export function LoadingSkeleton() {
  return (
    <div className={styles.skeletonGrid} role="status" aria-live="polite">
      <span className="sr-only">Загрузка результата</span>
      <div className={styles.skeletonHero} />
      <div className={styles.skeletonSide} />
      {Array.from({ length: 4 }, (_, index) => (
        <div className={styles.skeletonMetric} key={index} />
      ))}
    </div>
  );
}
