import { Card } from "../shared/ui/Card";
import { PageHeader } from "../shared/ui/PageHeader";
import { StatusBadge } from "../shared/ui/StatusBadge";
import styles from "../widgets/result-overview/result-overview.module.css";

const passportSections = [
  {
    title: "Активная версия",
    description: "Версия и дата активации должны приходить из отдельного сервиса моделей.",
  },
  {
    title: "Данные и период обучения",
    description: "Периоды, географии и поддерживаемые каналы нельзя брать из локальных файлов.",
  },
  {
    title: "Проверки качества",
    description: "Диагностики и результаты независимой проверки должны быть подтверждены отдельным контрактом.",
  },
  {
    title: "Границы применения",
    description: "Ограничения и известные риски будут показаны только после появления контракта.",
  },
];

export function ModelPassportPage() {
  return (
    <div className={styles.modelPassport}>
      <PageHeader
        eyebrow={<span>Model Passport</span>}
        title="Паспорт модели"
        meta={<span>Источник данных не подключен</span>}
        actions={<StatusBadge tone="warning">Нет данных</StatusBadge>}
      />
      <Card as="section" className={styles.passportBoundary} role="status">
        <span className={styles.panelLabel}>Контролируемое состояние</span>
        <h2>Паспорт подготовлен, но пока не заполнен</h2>
        <p>
          В текущем сервисе нет отдельного контракта активной модели. Интерфейс не
          подставляет сведения из документации, файлов реестра или демонстрационных данных.
        </p>
      </Card>
      <div className={styles.passportGrid}>
        {passportSections.map((section) => (
          <Card key={section.title} className={styles.passportCard}>
            <div className={styles.sectionHeading}>
              <h2>{section.title}</h2>
              <StatusBadge>Нет данных</StatusBadge>
            </div>
            <p>{section.description}</p>
            <div className={styles.passportPlaceholder} aria-hidden="true"><i /><i /><i /></div>
          </Card>
        ))}
      </div>
    </div>
  );
}
