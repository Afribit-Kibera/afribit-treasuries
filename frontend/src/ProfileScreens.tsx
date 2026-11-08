import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  CaretRight,
  Fingerprint,
  Globe,
  UserCircle,
  Wallet,
  DownloadSimple,
  Info,
  SignOut,
} from "@phosphor-icons/react";
import { Avatar, useScreenStart } from "./ui";
const pages = [
  ["details", "My details", "Name, username and contact", UserCircle],
  [
    "security",
    "Passkeys & recovery",
    "Ways to get back into your account",
    Fingerprint,
  ],
  ["region", "Country & currency", "Location and how money is shown", Globe],
  ["limits", "Payment limits", "How much your clan can send", Wallet],
  ["install", "Install Clans", "Add Clans to your home screen", DownloadSimple],
  ["about", "About your membership", "Your clan, grants and repayments", Info],
] as const;
export type ProfilePage = (typeof pages)[number][0];
export function ProfileScreens({
  name,
  username,
  children,
  logout,
  busy,
}: {
  name: string;
  username: string;
  children: (page: ProfilePage) => ReactNode;
  logout: () => void;
  busy: boolean;
}) {
  const [page, setPage] = useState<ProfilePage | null>(null);
  useScreenStart(page);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (page) heading.current?.focus({ preventScroll: true });
  }, [page]);
  return (
    <section className="content-page profile-screens" key={page || "menu"}>
      {page ? (
        <>
          <button
            className="text-button settings-back"
            onClick={() => setPage(null)}
          >
            <ArrowLeft size={20} />
            Profile
          </button>
          <h2 ref={heading} tabIndex={-1}>
            {pages.find((row) => row[0] === page)?.[1]}
          </h2>
          {children(page)}
        </>
      ) : (
        <>
          <div className="profile-identity">
            <Avatar name={name} />
            <div>
              <h2>{name}</h2>
              <p>@{username}</p>
            </div>
          </div>
          <div className="settings-menu">
            {pages.map(([key, label, help, Icon]) => (
              <button key={key} onClick={() => setPage(key)}>
                <Icon size={25} />
                <span>
                  <strong>{label}</strong>
                  <small>{help}</small>
                </span>
                <CaretRight size={19} />
              </button>
            ))}
          </div>
          <button
            className="text-button profile-logout"
            disabled={busy}
            onClick={logout}
          >
            <SignOut size={21} />
            Sign out
          </button>
        </>
      )}
    </section>
  );
}
