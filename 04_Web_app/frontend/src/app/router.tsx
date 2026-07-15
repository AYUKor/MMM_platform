import { createBrowserRouter, type RouteObject } from "react-router-dom";
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
        element: (
          <PlaceholderPage
            title="Главная"
            description="Dashboard будет реализован после core marketer flow."
          />
        ),
      },
      {
        path: "calculations",
        element: (
          <PlaceholderPage
            title="Мои расчёты"
            description="История расчётов не входит в Phase 1."
          />
        ),
      },
      {
        path: "calculations/:id/result",
        element: <ResultOverviewPage />,
      },
      {
        path: "model",
        element: (
          <PlaceholderPage
            title="Модель"
            description="Model passport будет реализован после marketer flow."
          />
        ),
      },
      {
        path: "help",
        element: (
          <PlaceholderPage
            title="Справка"
            description="Контекстная справка не входит в Phase 1."
          />
        ),
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
            title="Страница не найдена"
            description="Проверьте адрес или вернитесь к списку расчётов."
          />
        ),
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
