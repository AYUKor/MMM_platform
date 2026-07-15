import type { HTMLAttributes, PropsWithChildren } from "react";
import styles from "./ui.module.css";

interface CardProps extends HTMLAttributes<HTMLElement> {
  as?: "article" | "section";
}

export function Card({
  as: Component = "article",
  className = "",
  children,
  ...props
}: PropsWithChildren<CardProps>) {
  return (
    <Component className={`${styles.card} ${className}`} {...props}>
      {children}
    </Component>
  );
}
