import { Card } from "./Card";
import styles from "./ui.module.css";

interface ErrorStateProps {
  title: string;
  description: string;
  tone?: "error" | "permission";
}

export function ErrorState({
  title,
  description,
  tone = "error",
}: ErrorStateProps) {
  return (
    <Card className={styles.stateCard} role="alert">
      <span className={tone === "error" ? styles.errorCode : styles.permissionCode}>
        {tone === "error" ? "ERR" : "403"}
      </span>
      <h1>{title}</h1>
      <p>{description}</p>
    </Card>
  );
}
