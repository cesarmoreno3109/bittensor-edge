"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Overview" },
  { href: "/subnets", label: "Subnets" },
  { href: "/opportunities", label: "Opportunities" },
  { href: "/onchain", label: "On-Chain" },
  { href: "/analysis", label: "Analysis" },
  { href: "/backtest", label: "Backtest" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="flex items-center gap-1 px-4 py-3 border-b border-[#1e1e2e] bg-[#12121a]">
      <span className="text-lg font-bold mr-6 text-indigo-400">TAO Edge</span>
      {links.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
            path === l.href
              ? "bg-indigo-500/20 text-indigo-300"
              : "text-[#8888a0] hover:text-white hover:bg-white/5"
          }`}
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
