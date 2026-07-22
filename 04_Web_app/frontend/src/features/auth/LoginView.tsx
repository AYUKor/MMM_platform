import { useEffect, useRef, useState, type FormEvent } from "react";
import { ThemeSwitcher } from "../../shared/ui/ThemeSwitcher";
import { Button } from "../../shared/ui/Button";
import { isSyntheticReview } from "../../shared/config/review";
import { loginErrorCopy, registrationErrorCopy } from "./authModel";
import styles from "./auth.module.css";

type AuthMode = "login" | "register";

export function LoginView({
  notice,
  onSubmit,
  onRegister,
}: {
  notice: string | null;
  onSubmit: (email: string, password: string) => Promise<void>;
  onRegister?: (email: string, password: string, displayName: string | null) => Promise<void>;
}) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const isRegister = mode === "register" && onRegister !== undefined;

  useEffect(() => {
    if (error || localError) errorRef.current?.focus();
  }, [error, localError]);

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode);
    setError(null);
    setLocalError(null);
    setPassword("");
    setPasswordConfirm("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setError(null);
    setLocalError(null);
    if (isRegister) {
      if (password.length < 12) {
        setLocalError("Пароль должен содержать не менее 12 символов.");
        return;
      }
      if (password !== passwordConfirm) {
        setLocalError("Пароли не совпадают.");
        return;
      }
    }
    setPending(true);
    try {
      if (isRegister && onRegister) {
        await onRegister(email.trim(), password, displayName.trim() || null);
      } else {
        await onSubmit(email.trim(), password);
      }
    } catch (nextError) {
      setPassword("");
      setPasswordConfirm("");
      setError(nextError);
    } finally {
      setPending(false);
    }
  }

  const errorCopy = localError
    ? { title: "Проверьте данные регистрации", description: localError }
    : error
      ? isRegister ? registrationErrorCopy(error) : loginErrorCopy(error)
      : null;
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
          <p>Используйте локальную pilot-учетную запись или создайте ее самостоятельно.</p>
        </div>

        <form className={styles.loginForm} onSubmit={submit} noValidate>
          {notice ? <div className={styles.notice} role="status">{notice}</div> : null}
          {errorCopy ? (
            <div className={styles.loginError} role="alert" tabIndex={-1} ref={errorRef}>
              <strong>{errorCopy.title}</strong>
              <span>{errorCopy.description}</span>
            </div>
          ) : null}
          {isRegister ? (
            <label>
              <span>Имя (необязательно)</span>
              <input
                type="text"
                autoComplete="name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                maxLength={120}
                disabled={pending}
              />
            </label>
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
              autoComplete={isRegister ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              maxLength={256}
              disabled={pending}
            />
          </label>
          {isRegister ? (
            <label>
              <span>Повторите пароль</span>
              <input
                type="password"
                autoComplete="new-password"
                value={passwordConfirm}
                onChange={(event) => setPasswordConfirm(event.target.value)}
                required
                maxLength={256}
                disabled={pending}
              />
            </label>
          ) : null}
          <Button
            variant="primary"
            type="submit"
            disabled={pending || !email.trim() || !password || (isRegister && !passwordConfirm)}
          >
            {pending
              ? isRegister ? "Создаем…" : "Входим…"
              : isRegister ? "Зарегистрироваться" : "Войти"}
          </Button>
          {onRegister ? (
            <small>
              {isRegister ? "Уже есть учетная запись?" : "Нет учетной записи?"}{" "}
              <button
                type="button"
                className={styles.modeSwitch}
                onClick={() => switchMode(isRegister ? "login" : "register")}
                disabled={pending}
              >
                {isRegister ? "Войти" : "Создать учетную запись"}
              </button>
            </small>
          ) : (
            <small>Регистрация и восстановление пароля в pilot-контуре не предусмотрены.</small>
          )}
        </form>
      </section>
    </main>
  );
}
