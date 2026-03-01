"use client";

import React from "react";

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ReactNode;
  gradient: string;
}

export default function StatCard({ title, value, subtitle, icon, gradient }: StatCardProps) {
  return (
    <div className={`group relative p-[1px] rounded-2xl bg-gradient-to-br ${gradient} transition-all`}>
      <div className="relative rounded-2xl bg-card/80 backdrop-blur-xl p-6 h-full overflow-hidden">
        {/* Subtle gradient tint overlay */}
        <div className={`absolute inset-0 bg-gradient-to-br ${gradient} opacity-[0.06] pointer-events-none`} />
        <div className="relative flex justify-between items-start">
          <div>
            <p className="text-sm text-muted-foreground mb-1">{title}</p>
            <p className="text-4xl font-bold font-heading text-foreground">{value}</p>
            {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
          </div>
          <div className="text-5xl text-muted-foreground/30 group-hover:text-primary/40 transition-colors">{icon}</div>
        </div>
      </div>
    </div>
  );
}
