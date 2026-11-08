import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowDown,
  ArrowCounterClockwise,
  Check,
  Checks,
  Fingerprint,
  HandCoins,
  Moon,
  ShieldCheck,
  Sun,
  UsersThree,
} from "@phosphor-icons/react";

const steps = [
  {
    id: "gather",
    icon: UsersThree,
    title: "Bring your people together",
    text: "Create your clan and invite your members. Each person chooses to join. Your group picks 3, 5 or 7 signatories to approve payments.",
  },
  {
    id: "request",
    icon: HandCoins,
    title: "Help a member grow",
    text: "Add money to your group. A member asks for a grant and explains what it is for. Everyone can see the request.",
  },
  {
    id: "vote",
    icon: Checks,
    title: "Make the decision together",
    text: "Members vote. If the request passes, the member accepts and adds a payment request from their Lightning wallet. Enough signatories must approve before money is sent.",
  },
  {
    id: "repay",
    icon: ArrowCounterClockwise,
    title: "Bring the money back",
    text: "Repay a little at a time or all at once. Every confirmed repayment reduces what is owed and returns money to the clan.",
  },
];
const questions = [
  [
    "Who is Clans for?",
    "A group of people who know each other and want to fund their members together. You can start with your existing savings group, business group or community.",
  ],
  [
    "Is Clans part of Afribit Wallet?",
    "Yes. Clans is a feature of Afribit Wallet. You can use this web app on your phone and add it to your home screen.",
  ],
  [
    "Where does a grant go?",
    "The member supplies a Lightning payment request from their own wallet after accepting the grant. Signatories approve that exact request, amount and highest fee. Clans pays it only after the required checks pass.",
  ],
  [
    "Can a member repay in small amounts?",
    "Yes. A member can choose an amount and pay from a Lightning wallet. Only a confirmed payment reduces the amount they owe. Extra money stays in the clan.",
  ],
  [
    "Why can the amount in shillings change?",
    "You can see amounts in your local currency. The money and repayments are kept in Bitcoin, so their local-currency value can change.",
  ],
  [
    "How is the money held?",
    "Afribit runs the shared payment wallet. Your group's votes and approvals control payments made through Clans. Afribit still controls the wallet that holds the funds.",
  ],
];

export default function ProductPage() {
  const root = useRef<HTMLDivElement>(null);
  const [theme, setTheme] = useState(() =>
    document.documentElement.dataset.theme === "light" ? "light" : "dark",
  );
  useEffect(() => {
    if (
      !root.current ||
      !window.IntersectionObserver ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
      },
      { threshold: 0.12 },
    );
    const elements = root.current.querySelectorAll("[data-reveal]");
    elements.forEach((element) => {
      element.classList.add("will-reveal");
      observer.observe(element);
    });
    return () => {
      observer.disconnect();
      elements.forEach((element) => element.classList.remove("will-reveal"));
    };
  }, []);
  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", next === "dark" ? "#0c0d0c" : "#f6f5ee");
    try {
      localStorage.setItem("clans-theme", next);
    } catch {
      /* Theme works without storage. */
    }
    setTheme(next);
  }
  return (
    <div className="product-page" ref={root}>
      <a className="product-skip" href="#main">
        Skip to content
      </a>
      <div className="product-backdrop" aria-hidden="true" />
      <header className="product-header product-wrap">
        <a
          className="product-brand"
          href="/about/"
          aria-label="Clans, a feature of Afribit Wallet"
        >
          <img src="/assets/afribit-mark.webp" width="48" height="48" alt="" />
          <span>
            <strong>
              Afribit <em>Clans</em>
            </strong>
            <small>A feature of Afribit Wallet</small>
          </span>
        </a>
        <nav aria-label="Main navigation">
          <a className="product-nav-link" href="#how-it-works">
            How it works
          </a>
          <button
            className="product-theme"
            onClick={toggleTheme}
            aria-label={
              theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
            }
          >
            {theme === "dark" ? <Sun size={23} /> : <Moon size={23} />}
          </button>
          <a className="product-open" href="/">
            Open Clans <ArrowRight size={18} />
          </a>
        </nav>
      </header>
      <main id="main">
        <section className="product-hero product-wrap">
          <div className="product-hero-copy">
            <span className="product-kicker">
              Your group. Your shared money.
            </span>
            <h1>
              Help a member.
              <br />
              <em>Keep your group moving.</em>
            </h1>
            <p>
              Put money together, decide who to support, and bring repayments
              back to help the next person.
            </p>
            <div className="product-hero-actions">
              <a className="product-cta" href="/">
                Start your clan <ArrowRight size={22} />
              </a>
              <a className="product-text-link" href="#how-it-works">
                See how it works <ArrowDown size={18} />
              </a>
            </div>
            <p className="product-hero-note">
              <Fingerprint size={20} /> Your account opens with your phone’s
              fingerprint, face unlock or PIN.
            </p>
          </div>
          <div
            className="product-paw-scene"
            aria-label="Request a grant, vote together and repay your clan"
          >
            <a className="product-paw product-paw-request" href="#request">
              <HandCoins size={45} weight="light" />
              <span>
                Receive
                <br />
                grant
              </span>
            </a>
            <a className="product-paw product-paw-repay" href="#repay">
              <ArrowCounterClockwise size={45} weight="light" />
              <span>Repay</span>
            </a>
            <a className="product-paw product-paw-vote" href="#vote">
              <Checks size={45} weight="light" />
              <span>Vote</span>
            </a>
            <span className="product-paw-caption">
              Keep it moving. Together.
            </span>
          </div>
        </section>
        <section
          className="product-principles product-wrap"
          aria-label="How your group stays involved"
          data-reveal
        >
          <div>
            <UsersThree size={28} />
            <span>
              <strong>People you know</strong>
              <small>Join by invitation</small>
            </span>
          </div>
          <div>
            <Checks size={28} />
            <span>
              <strong>A say for members</strong>
              <small>Vote before a grant is paid</small>
            </span>
          </div>
          <div>
            <ShieldCheck size={28} />
            <span>
              <strong>Shared approval</strong>
              <small>No single member pays alone</small>
            </span>
          </div>
        </section>
        <section className="product-story product-wrap" id="how-it-works">
          <div className="product-section-intro" data-reveal>
            <span className="product-kicker">How Clans works</span>
            <h2>
              One grant can help.
              <br />
              <em>Repayments help the next member.</em>
            </h2>
            <p>
              Your group decides together. Clans keeps the requests, votes,
              payments and repayments in one place.
            </p>
          </div>
          <ol className="product-steps">
            {steps.map(({ id, icon: Icon, title, text }, index) => (
              <li id={id} key={id} data-reveal>
                <span className="product-step-number">0{index + 1}</span>
                <div className="product-step-content">
                  <Icon size={31} weight="light" />
                  <h3>{title}</h3>
                  <p>{text}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
        <section className="product-approval product-wrap" data-reveal>
          <div>
            <span className="product-kicker">A decision shared</span>
            <h2>
              Your group chooses.
              <br />
              <em>Your signatories approve.</em>
            </h2>
          </div>
          <div className="product-approval-detail">
            <ShieldCheck size={38} weight="light" />
            <p>
              Choose <strong>3, 5 or 7 signatories.</strong> Each payment needs
              a majority of them to approve. Members vote first, and the person
              receiving a grant confirms before payment.
            </p>
            <span>
              <Check size={19} /> Every approval is tied to the member’s payment
              request.
            </span>
          </div>
        </section>
        <section
          className="product-faq product-wrap"
          aria-labelledby="questions-title"
          data-reveal
        >
          <div className="product-section-intro">
            <span className="product-kicker">A few useful answers</span>
            <h2 id="questions-title">
              Before you
              <br />
              <em>bring your people.</em>
            </h2>
          </div>
          <div>
            {questions.map(([question, answer]) => (
              <details key={question}>
                <summary>
                  {question}
                  <span aria-hidden="true">+</span>
                </summary>
                <p>{answer}</p>
              </details>
            ))}
          </div>
        </section>
        <section className="product-final product-wrap" data-reveal>
          <img
            src="/assets/afribit-mark.webp"
            width="62"
            height="62"
            alt=""
            loading="lazy"
          />
          <h2>
            Start with
            <br />
            <em>your people.</em>
          </h2>
          <p>Create your clan. Invite the group. Decide what comes next.</p>
          <a className="product-cta" href="/">
            Open Clans <ArrowRight size={22} />
          </a>
        </section>
      </main>
      <footer className="product-footer product-wrap">
        <span>
          Clans <span aria-hidden="true">/</span> Afribit Wallet
        </span>
        <span>Built by Afribit Africa</span>
        <a href="/">
          Open the app <ArrowRight size={16} />
        </a>
      </footer>
    </div>
  );
}
