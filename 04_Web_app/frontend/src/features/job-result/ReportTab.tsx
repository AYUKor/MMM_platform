import { UnavailableBlock } from "./ResultVisuals";
import styles from "./job-result.module.css";

export function ReportTab() {
  return (
    <div className={styles.tabStack}>
      <section className={styles.tabIntro}>
        <div><span className={styles.eyebrow}>Отчет</span><h2>Выгрузка результата</h2></div>
        <p>Отсутствующие сведения не восстанавливаются из прежнего формата результата.</p>
      </section>
      <UnavailableBlock
        title="Excel-отчет пока недоступен"
        description="Текущий формат результата не содержит проверенных сведений о файле отчета. Скачивание появится, когда сервис опубликует их вместе с результатом."
      />
    </div>
  );
}
