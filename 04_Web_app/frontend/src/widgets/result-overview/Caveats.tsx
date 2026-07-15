import { Card } from "../../shared/ui/Card";
import styles from "./result-overview.module.css";

interface CaveatsProps {
  caveats: string[];
}

export function Caveats({ caveats }: CaveatsProps) {
  return (
    <Card as="section" className={styles.caveats}>
      <h2>Что важно учитывать</h2>
      {caveats.length > 0 ? (
        <ul>{caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul>
      ) : (
        <p>Нет данных</p>
      )}
    </Card>
  );
}
