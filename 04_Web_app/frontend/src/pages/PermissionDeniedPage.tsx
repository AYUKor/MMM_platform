import { ErrorState } from "../shared/ui/ErrorState";

export function PermissionDeniedPage() {
  return (
    <ErrorState
      tone="permission"
      title="Недостаточно прав"
      description="Ваша сессия активна, но для этого раздела нет необходимого разрешения. Обратитесь к администратору."
    />
  );
}
