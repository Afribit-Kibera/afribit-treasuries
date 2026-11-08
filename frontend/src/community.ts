// The community whose oversight approves this clan's wallet payments: Afribit, or a
// community the clan joined with its code. A member belongs to one clan, so the clan
// screen sets this once and every wallet message names the right people.
const DEFAULT_COMMUNITY = "Afribit";
let current = DEFAULT_COMMUNITY;

export function setCommunityName(name: string | null | undefined) {
  current = name?.trim() || DEFAULT_COMMUNITY;
}

export function communityName() {
  return current;
}
