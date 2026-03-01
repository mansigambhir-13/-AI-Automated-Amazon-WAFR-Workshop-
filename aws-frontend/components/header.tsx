"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Settings, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getCurrentUserInfo, isTeamUser, signOutUser } from "@/lib/auth";

function getBreadcrumbLabel(pathname: string): string | null {
  if (pathname === "/") return null;
  if (pathname === "/new-assessment") return "New Assessment";
  if (pathname.startsWith("/progress/")) return "Assessment Progress";
  if (pathname.startsWith("/results/")) return "Assessment Results";
  if (pathname.startsWith("/review/")) return "Review Items";
  if (pathname.startsWith("/reports/")) return "Reports & Downloads";
  return null;
}

export default function Header() {
  const pathname = usePathname();
  const [userInfo, setUserInfo] = useState<{ username: string; groups: string[] } | null>(null);

  useEffect(() => {
    getCurrentUserInfo()
      .then(info => setUserInfo({ username: info.username, groups: info.groups }))
      .catch(() => setUserInfo(null));
  }, []);

  const handleSignOut = async () => {
    await signOutUser();
    // Authenticator will show login form automatically after signOut clears tokens
  };

  const breadcrumbLabel = getBreadcrumbLabel(pathname);

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/80 backdrop-blur-xl">
      <div className="flex items-center justify-between px-6 h-16">
        {/* Left side: Logo + Title */}
        <Link href="/" className="flex items-center gap-3">
          <Settings className="h-8 w-8 text-primary shrink-0" />
          <div className="flex flex-col">
            <span className="text-foreground font-bold text-lg leading-tight">
              AWS Well-Architected Tool
            </span>
            <span className="text-muted-foreground text-xs leading-tight">
              Framework Review &amp; Assessment
            </span>
          </div>
        </Link>

        {/* Right side: Breadcrumb nav + Theme toggle */}
        <div className="flex items-center gap-4">
          {/* Breadcrumb navigation */}
          <nav className="flex items-center gap-2 text-sm">
            {breadcrumbLabel ? (
              <>
                <Link
                  href="/"
                  className="text-muted-foreground hover:text-primary transition-colors"
                >
                  Dashboard
                </Link>
                <span className="text-muted-foreground/60">/</span>
                <span className="text-foreground font-semibold">
                  {breadcrumbLabel}
                </span>
              </>
            ) : (
              <span className="text-foreground font-semibold">Dashboard</span>
            )}
          </nav>

          {/* User info + Sign out */}
          {userInfo && (
            <div className="flex items-center gap-2 border-l border-border/40 pl-4 ml-2">
              <span className="text-sm text-foreground font-medium">
                {userInfo.username}
              </span>
              <Badge
                className={
                  isTeamUser(userInfo.groups)
                    ? "bg-primary/10 text-primary border-primary/20 text-xs"
                    : "bg-secondary/10 text-secondary border-secondary/20 text-xs"
                }
              >
                {isTeamUser(userInfo.groups) ? "Team" : "Client"}
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleSignOut}
                className="text-muted-foreground hover:text-foreground h-8 px-2"
                aria-label="Sign out"
              >
                <LogOut className="h-4 w-4 mr-1" />
                Sign out
              </Button>
            </div>
          )}

        </div>
      </div>
    </header>
  );
}
