import type { KeyboardEvent } from "react";
import styles from "./ui.module.css";

export interface TabItem {
  id: string;
  label: string;
  disabled?: boolean;
}

interface TabsProps {
  items: TabItem[];
  activeId: string;
  onChange: (id: string) => void;
}

export function Tabs({ items, activeId, onChange }: TabsProps) {
  const enabledItems = items.filter((item) => !item.disabled);

  const moveFocus = (
    event: KeyboardEvent<HTMLButtonElement>,
    itemId: string,
  ) => {
    const currentIndex = enabledItems.findIndex((item) => item.id === itemId);
    if (currentIndex < 0) return;
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % enabledItems.length;
    if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + enabledItems.length) % enabledItems.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = enabledItems.length - 1;
    if (nextIndex === null) return;
    const nextItem = enabledItems[nextIndex];
    if (!nextItem) return;
    event.preventDefault();
    onChange(nextItem.id);
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
      '[role="tab"]:not(:disabled)',
    );
    buttons?.[nextIndex]?.focus();
  };

  return (
    <div className={styles.tabs} role="tablist" aria-label="Разделы результата">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={item.id === activeId}
          aria-controls={`${item.id}-panel`}
          id={`${item.id}-tab`}
          tabIndex={item.id === activeId ? 0 : -1}
          disabled={item.disabled}
          className={item.id === activeId ? styles.activeTab : styles.tab}
          title={item.disabled ? "Будет реализовано в следующей фазе" : undefined}
          onClick={() => onChange(item.id)}
          onKeyDown={(event) => moveFocus(event, item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
