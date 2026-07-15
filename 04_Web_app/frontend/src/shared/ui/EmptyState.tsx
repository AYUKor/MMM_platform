import { Card } from "./Card";
import styles from "./ui.module.css";

interface EmptyStateProps {
  title: string;
  description: string;
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <Card className={styles.stateCard} role="status">
      <span className={styles.stateCode}>00</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </Card>
  );
}
