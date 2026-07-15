import styles from "./ui.module.css";

export interface TabItem {
  id: string;
  label: string;
  disabled?: boolean;
}

interface TabsProps {
  items: TabItem[];
  activeId: string;
}

export function Tabs({ items, activeId }: TabsProps) {
  return (
    <div className={styles.tabs} role="tablist" aria-label="Разделы результата">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={item.id === activeId}
          aria-controls={`${item.id}-panel`}
          disabled={item.disabled}
          className={item.id === activeId ? styles.activeTab : styles.tab}
          title={item.disabled ? "Будет реализовано в следующей фазе" : undefined}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
