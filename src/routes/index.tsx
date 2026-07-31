import { createFileRoute, Navigate } from "@tanstack/react-router";

import { homeRouteFor, useAuth } from "@/lib/auth";

export const Route = createFileRoute("/")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Robot Fleet Control — Autonomous Fleet Operations" },
      {
        name: "description",
        content:
          "Real-time monitoring, teleoperation and task dispatch for an autonomous mobile robot fleet running on ROS 2.",
      },
      { property: "og:title", content: "Robot Fleet Control — Autonomous Fleet Operations" },
      {
        property: "og:description",
        content: "Real-time monitoring, teleoperation and task dispatch for an autonomous mobile robot fleet.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: IndexRedirect,
});

function IndexRedirect() {
  const { ready, isAuthenticated, user } = useAuth();
  if (!ready) return <div className="min-h-screen bg-background" />;
  return <Navigate to={isAuthenticated ? homeRouteFor(user) : "/login"} replace />;
}
