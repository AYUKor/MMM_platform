import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { safeReturnTo } from "../app/access";
import { LoginView } from "../features/auth/LoginView";
import { SessionBootstrapState } from "../features/auth/RequireSession";
import { useAuth } from "../features/auth/AuthProvider";

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const returnTo = safeReturnTo(searchParams.get("return_to"));
  const routeNotice = typeof location.state === "object" && location.state &&
    "authNotice" in location.state && typeof location.state.authNotice === "string"
    ? location.state.authNotice
    : null;

  if (auth.status === "loading") return <SessionBootstrapState />;
  if (auth.status === "authenticated") return <Navigate to={returnTo} replace />;

  return (
    <LoginView
      notice={routeNotice ?? auth.notice}
      onSubmit={async (email, password) => {
        await auth.login(email, password);
        navigate(returnTo, { replace: true });
      }}
    />
  );
}
