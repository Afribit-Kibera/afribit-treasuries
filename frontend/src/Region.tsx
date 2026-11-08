import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  getCountries,
  getCountryCallingCode,
  parsePhoneNumberFromString,
  type CountryCode,
} from "libphonenumber-js/min";
import { MapPin } from "@phosphor-icons/react";

const currencies = [
  "KES",
  "UGX",
  "TZS",
  "USD",
  "EUR",
  "GBP",
  "ZAR",
  "NGN",
  "CAD",
  "AUD",
  "INR",
  "CHF",
  "AED",
];
const localCurrency: Record<string, string> = {
  KE: "KES",
  UG: "UGX",
  TZ: "TZS",
  US: "USD",
  GB: "GBP",
  ZA: "ZAR",
  NG: "NGN",
  CA: "CAD",
  AU: "AUD",
  IN: "INR",
  CH: "CHF",
  AE: "AED",
  DE: "EUR",
  FR: "EUR",
  IT: "EUR",
  ES: "EUR",
  NL: "EUR",
  IE: "EUR",
  PT: "EUR",
  BE: "EUR",
  AT: "EUR",
  FI: "EUR",
  GR: "EUR",
};
const names = new Intl.DisplayNames([navigator.language || "en"], {
  type: "region",
});
const countries = getCountries().sort((a, b) =>
  countryName(a).localeCompare(countryName(b)),
);
export function countryName(code: string) {
  return names.of(code) || code;
}

type Region = { country: CountryCode; currency: string };
type Context = Region & {
  locale: string;
  setCountry: (country: CountryCode) => void;
  setCurrency: (currency: string) => void;
};
const RegionContext = createContext<Context | null>(null);
export function RegionProvider({ children }: { children: ReactNode }) {
  const [region, setRegion] = useState<Region>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("clans-region") || "null");
      if (
        saved &&
        countries.includes(saved.country) &&
        currencies.includes(saved.currency)
      )
        return saved;
    } catch {
      /* Device storage may be unavailable. */
    }
    return { country: "KE", currency: "KES" };
  });
  useEffect(() => {
    try {
      localStorage.setItem("clans-region", JSON.stringify(region));
    } catch {
      /* Preferences remain usable for this visit. */
    }
  }, [region]);
  return (
    <RegionContext.Provider
      value={{
        ...region,
        locale: new Intl.Locale(`und-${region.country}`).maximize().toString(),
        setCountry: (country) =>
          setRegion({ country, currency: localCurrency[country] || "USD" }),
        setCurrency: (currency) => {
          if (currencies.includes(currency))
            setRegion((old) => ({ ...old, currency }));
        },
      }}
    >
      {children}
    </RegionContext.Provider>
  );
}
export function useRegion() {
  const value = useContext(RegionContext);
  if (!value) throw new Error("RegionProvider is required");
  return value;
}

export function RegionSettings({ compact = false }: { compact?: boolean }) {
  const { country, currency, setCountry, setCurrency } = useRegion();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function locate() {
    setBusy(true);
    setMessage("");
    try {
      if (!navigator.geolocation) throw new Error("Choose your country below.");
      const position = await new Promise<GeolocationPosition>(
        (resolve, reject) =>
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: false,
            timeout: 12_000,
            maximumAge: 300_000,
          }),
      );
      const { iso1A2Code } = await import("@rapideditor/country-coder");
      const found = iso1A2Code([
        position.coords.longitude,
        position.coords.latitude,
      ]) as CountryCode | null;
      if (!found || !countries.includes(found))
        throw new Error("We could not find your country. Choose it below.");
      setCountry(found);
      setMessage(`${countryName(found)} selected. You can change it below.`);
    } catch {
      setMessage(
        "Location was not available. You can choose your country below.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className={`region-settings ${compact ? "compact" : ""}`}
      aria-label="Country and money display"
    >
      {!compact && <h3>Country & currency</h3>}
      <p className="field-help">Set your phone code and how money is shown.</p>
      <button
        type="button"
        className="text-button location-button"
        disabled={busy}
        onClick={() => void locate()}
      >
        <MapPin size={19} />
        {busy ? "Finding your country…" : "Use my location"}
      </button>
      <p className="field-help">Your location stays on this device.</p>
      <div className="region-fields">
        <label>
          Country
          <select
            value={country}
            onChange={(event) => {
              setCountry(event.target.value as CountryCode);
              setMessage("");
            }}
          >
            {countries.map((code) => (
              <option key={code} value={code}>
                {countryName(code)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Show money in
          <select
            value={currency}
            onChange={(event) => setCurrency(event.target.value)}
          >
            {currencies.map((code) => (
              <option key={code}>{code}</option>
            ))}
          </select>
        </label>
      </div>
      {message && (
        <p className="field-help" role="status">
          {message}
        </p>
      )}
    </section>
  );
}

export function PhoneField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const { country } = useRegion();
  const [phoneCountry, setPhoneCountry] = useState<CountryCode>(
    () => parsePhoneNumberFromString(value)?.country || country,
  );
  const [raw, setRaw] = useState(() => {
    const parsed = parsePhoneNumberFromString(value);
    return parsed
      ? parsed
          .formatInternational()
          .slice(parsed.countryCallingCode.length + 2)
          .trim()
      : value;
  });
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!raw) setPhoneCountry(country);
  }, [country, raw]);
  function update(
    text: string,
    selected: CountryCode,
    input?: HTMLInputElement,
  ) {
    setRaw(text);
    const parsed = parsePhoneNumberFromString(text, selected);
    const valid = !!parsed?.isPossible();
    (input || inputRef.current)?.setCustomValidity(
      text && !valid ? "Check your phone number and country code." : "",
    );
    onChange(valid && parsed ? parsed.number : text);
  }
  return (
    <>
      <label>
        Phone country
        <select
          value={phoneCountry}
          onChange={(event) => {
            const next = event.target.value as CountryCode;
            setPhoneCountry(next);
            update(raw, next);
          }}
        >
          {countries.map((code) => (
            <option key={code} value={code}>
              {countryName(code)} (+{getCountryCallingCode(code)})
            </option>
          ))}
        </select>
      </label>
      <label>
        Phone number
        <div className="phone-input">
          <span aria-hidden="true">+{getCountryCallingCode(phoneCountry)}</span>
          <input
            ref={inputRef}
            name="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel-national"
            required
            maxLength={25}
            placeholder={
              phoneCountry === "KE" ? "712 345 678" : "Your phone number"
            }
            value={raw}
            onChange={(event) =>
              update(event.target.value, phoneCountry, event.target)
            }
            onBlur={(event) => {
              const parsed = parsePhoneNumberFromString(raw, phoneCountry);
              if (parsed?.isPossible())
                setRaw(
                  parsed
                    .formatInternational()
                    .slice(parsed.countryCallingCode.length + 2)
                    .trim(),
                );
              event.target.setCustomValidity(
                raw && !parsed?.isPossible()
                  ? "Check your phone number and country code."
                  : "",
              );
            }}
          />
        </div>
      </label>
      <p className="field-help">
        Your number stays private. You can start with 0 or use the full country
        code.
      </p>
    </>
  );
}
