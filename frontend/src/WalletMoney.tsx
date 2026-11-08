import { useRegion } from "./Region";
import { useRate, localMoney } from "./LocalMoney";
export function useWalletMoney() {
  const { currency, locale } = useRegion();
  const { rate } = useRate(currency);
  return (value: bigint) => (
    <span className="wallet-money">
      {new Intl.NumberFormat(locale).format(value)} sats
      <small>
        {rate
          ? `≈ ${localMoney((value * 1000n).toString(), rate, true, locale)}`
          : `${currency} estimate unavailable`}
      </small>
    </span>
  );
}
