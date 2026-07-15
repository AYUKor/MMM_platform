import { useTheme } from "../theme/ThemeProvider";
import type { ThemePreference } from "../theme/theme";
import styles from "./ui.module.css";

const choices: Array<{ value: ThemePreference; label: string; glyph: string }> = [
  { value: "light", label: "Светлая тема", glyph: "L" },
  { value: "system", label: "Системная тема", glyph: "A" },
  { value: "dark", label: "Темная тема", glyph: "D" },
];

export function ThemeSwitcher() {
  const { preference, setPreference } = useTheme();
  return (
    <div className={styles.themeSwitcher} aria-label="Переключение темы">
      {choices.map((choice) => (
        <button
          type="button"
          key={choice.value}
          className={preference === choice.value ? styles.themeActive : undefined}
          aria-label={choice.label}
          aria-pressed={preference === choice.value}
          onClick={() => setPreference(choice.value)}
        >
          {choice.glyph}
        </button>
      ))}
    </div>
  );
}
