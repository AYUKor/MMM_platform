import { useEffect, useRef, useState, type FormEvent } from "react";
import { ThemeSwitcher } from "../../shared/ui/ThemeSwitcher";
import { Button } from "../../shared/ui/Button";
import { isSyntheticReview } from "../../shared/config/review";
import { loginErrorCopy } from "./authModel";
import styles from "./auth.module.css";

export function LoginView({
  notice,
  onSubmit,
}: {
  notice: string | null;
  onSubmit: (email: string, password: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      await onSubmit(email.trim(), password);
    } catch (nextError) {
      setPassword("");
      setError(nextError);
    } finally {
      setPending(false);
    }
  }

  const errorCopy = error ? loginErrorCopy(error) : null;
  return (
    <main className={styles.loginPage}>
      <div className={styles.loginTopbar}>
        <span>Исследовательский контур</span>
        {isSyntheticReview()
          ? <strong className={styles.reviewBadge}>Демонстрационные данные</strong>
          : null}
        <ThemeSwitcher />
      </div>
      <section className={styles.loginFrame} aria-labelledby="login-title">
        <div className={styles.loginIntro}>
          <span className={styles.brandMark}>M</span>
          <p className={styles.eyebrow}>MMM Forecast &amp; Optimizer</p>
          <h1 id="login-title">Войдите в рабочее пространство</h1>
          <p>Используйте локальную pilot-учетную запись, выданную администратором проекта.</p>
        </div>

        <form className={styles.loginForm} onSubmit={submit} noValidate>
          {notice ? <div className={styles.notice} role="status">{notice}</div> : null}
          {errorCopy ? (
            <div className={styles.loginError} role="alert" tabIndex={-1} ref={errorRef}>
              <strong>{errorCopy.title}</strong>
              <span>{errorCopy.description}</span>
            </div>
          ) : null}
          <label>
            <span>Email</span>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              maxLength={254}
              disabled={pending}
            />
          </label>
          <label>
            <span>Пароль</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              maxLength={256}
              disabled={pending}
            />
          </label>
          <Button variant="primary" type="submit" disabled={pending || !email.trim() || !password}>
            {pending ? "Входим…" : "Войти"}
          </Button>
          <small>Регистрация и восстановление пароля в pilot-контуре не предусмотрены.</small>
        </form>
      </section>
    </main>
  );
}
