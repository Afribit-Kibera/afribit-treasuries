import { useState } from "react";
import {
  ArrowLeft,
  CaretRight,
  EnvelopeSimple,
  ShieldCheck,
  UsersThree,
  UserPlus,
} from "@phosphor-icons/react";
import { type ClanDetail } from "./live-api";
import { Avatar, Busy, useScreenStart } from "./ui";
import { useRegion } from "./Region";
import { WalletCard } from "./WalletCard";
import { setCommunityName } from "./community";
export function ClanScreen({
  clan,
  userId,
  busy,
  invite,
  revoke,
}: {
  clan: ClanDetail;
  userId: string;
  busy: boolean;
  invite: () => void;
  revoke: (id: string) => void;
}) {
  // The wallet screens name whoever oversees this clan's payments.
  setCommunityName(clan.community?.name);
  const [page, setPage] = useState<"members" | "signers" | "invites" | null>(
    null,
  );
  useScreenStart(page);
  const { locale } = useRegion();
  const pending = clan.invitations.filter(
    (i) => !i.accepted && !i.revoked && i.expires_at > new Date().toISOString(),
  );
  const organizer = clan.my_role === "organizer";
  return (
    <section className="content-page club-screen" key={page || "overview"}>
      {page ? (
        <>
          <button
            className="text-button settings-back"
            onClick={() => setPage(null)}
          >
            <ArrowLeft size={20} />
            My clan
          </button>
          <div className="section-header">
            <h2>
              {page === "members"
                ? "Members"
                : page === "signers"
                  ? "Signatories"
                  : "Invitations"}
            </h2>
            {organizer && (
              <button className="text-button" onClick={invite}>
                <UserPlus size={20} />
                Invite
              </button>
            )}
          </div>
          {page === "invites" ? (
            <>
              {!pending.length && (
                <p className="empty-state">No invitations waiting.</p>
              )}
              {pending.map((i) => (
                <div className="invitation-row" key={i.id}>
                  <span>
                    {i.is_signer ? "Signatory" : "Member"} invitation
                    <small>
                      Expires{" "}
                      {new Date(i.expires_at).toLocaleDateString(locale, {
                        day: "numeric",
                        month: "short",
                      })}
                    </small>
                  </span>
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => revoke(i.id)}
                  >
                    <Busy busy={busy}>Cancel invitation</Busy>
                  </button>
                </div>
              ))}
            </>
          ) : (
            <>
              {page === "signers" && (
                <p className="field-help">
                  {clan.signer_threshold} of {clan.target_signers} signatories
                  approve each payment. A person receiving a grant cannot
                  approve their own payment.
                </p>
              )}
              <div className="live-member-list">
                {clan.members
                  .filter((m) => page === "members" || m.is_signer)
                  .map((m) => (
                    <div className="live-member" key={m.id}>
                      <Avatar name={m.name} />
                      <div>
                        <strong>
                          {m.name}
                          {m.id === userId ? " (you)" : ""}
                        </strong>
                        <span>
                          {m.role === "organizer" ? "Organizer" : "Member"}
                          {m.is_signer ? " · Signatory" : ""}
                        </span>
                      </div>
                      {m.is_signer && <ShieldCheck size={23} />}
                    </div>
                  ))}
              </div>
            </>
          )}
        </>
      ) : (
        <>
          <div className="club-identity">
            <div className="club-crest">
              <UsersThree size={57} weight="light" />
            </div>
            <h2>{clan.name}</h2>
            <p>
              {clan.member_count}{" "}
              {clan.member_count === 1 ? "member" : "members"} · Started{" "}
              {new Date(clan.created_at).toLocaleDateString(locale, {
                month: "short",
                year: "numeric",
              })}
            </p>
          </div>
          <WalletCard clanId={clan.id} clanName={clan.name} />
          <div className="club-menu">
            <button onClick={() => setPage("members")}>
              <UsersThree size={28} />
              <strong>Members</strong>
              <span>{clan.member_count}</span>
              <CaretRight />
            </button>
            <button onClick={() => setPage("signers")}>
              <ShieldCheck size={28} />
              <strong>Signatories</strong>
              <span>{clan.signer_count}</span>
              <CaretRight />
            </button>
            {organizer && (
              <button onClick={() => setPage("invites")}>
                <EnvelopeSimple size={28} />
                <strong>Invitations</strong>
                <span>{pending.length}</span>
                <CaretRight />
              </button>
            )}
          </div>
          {organizer && (
            <button className="primary-button club-invite" onClick={invite}>
              <UserPlus size={24} />
              Invite member
            </button>
          )}
          <section className="club-rule" aria-label="Payment approvals">
            <span className="club-rule-icon">
              <ShieldCheck size={27} weight="duotone" />
            </span>
            <div>
              <h3>Each payment needs {clan.signer_threshold} approvals</h3>
              <p>
                From your clan’s {clan.target_signers} signatories. Members vote
                on a grant before its payment is approved.
              </p>
            </div>
          </section>
          {!clan.governance_ready && (
            <p className="field-help">
              Your clan is still setting up.{" "}
              {Math.max(0, clan.target_signers - clan.signer_count)} more
              signatories need to join.
            </p>
          )}
        </>
      )}
    </section>
  );
}
