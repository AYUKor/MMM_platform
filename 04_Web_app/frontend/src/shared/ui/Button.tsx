import type { ButtonHTMLAttributes, PropsWithChildren } from "react";
import styles from "./ui.module.css";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "primary";
}

export function Button({
  variant = "default",
  className = "",
  children,
  ...props
}: PropsWithChildren<ButtonProps>) {
  return (
    <button
      className={`${styles.button} ${styles[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
