import { createBrowserRouter, type RouteObject } from "react-router-dom";
import { CalculationsPage } from "../pages/CalculationsPage";
import { HelpPage } from "../pages/HelpPage";
import { HomePage } from "../pages/HomePage";
import { JobProgressPage } from "../pages/JobProgressPage";
import { NewCalculationPage } from "../pages/NewCalculationPage";
import { ModelPassportPage } from "../pages/ModelPassportPage";
import { PermissionDeniedPage } from "../pages/PermissionDeniedPage";
import { PlaceholderPage } from "../pages/PlaceholderPage";
import { ResultOverviewPage } from "../pages/ResultOverviewPage";
import { AppShell } from "../widgets/app-shell/AppShell";

export const routes: RouteObject[] = [
  {
    path: "/login",
    element: (
      <PlaceholderPage
        title="Вход не подключён"
        description="SSO и локальная authentication-схема требуют отдельного согласования."
      />
    ),
  },
  {
    path: "/",
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <HomePage />,
      },
      {
        path: "calculations",
        element: <CalculationsPage />,
      },
      { path: "calculations/new", element: <NewCalculationPage /> },
      { path: "calculations/:id/progress", element: <JobProgressPage /> },
      {
        path: "calculations/:id/result",
        element: <ResultOverviewPage />,
      },
      {
        path: "model",
        element: <ModelPassportPage />,
      },
      {
        path: "help",
        element: <HelpPage />,
      },
      { path: "admin/system", element: <PermissionDeniedPage /> },
      { path: "admin/jobs", element: <PermissionDeniedPage /> },
      { path: "admin/models", element: <PermissionDeniedPage /> },
      { path: "admin/errors", element: <PermissionDeniedPage /> },
      { path: "admin/users", element: <PermissionDeniedPage /> },
      {
        path: "*",
        element: (
          <PlaceholderPage
            title="Раздел не найден"
            description="Проверьте адрес или вернитесь в рабочее пространство."
          />
        ),
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
