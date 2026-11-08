// Synthetic signet wallet moves and refreshes. Rebuild with scripts/build_wallet_fixtures.py.
export const fixtureMove = {
  "id": "fixture-move",
  "clan_id": "preview",
  "kind": "move",
  "generation": 1,
  "destination": {
    "generation": 2,
    "keychain": "internal",
    "index": 0,
    "address": "tb1pamlxv49prze2karrtysf9jakj4y4rjnyh5m9aswqg6xcjg85z4qqxyhj2u"
  },
  "replaces": null,
  "replaced_by": null,
  "status": "awaiting_signatures",
  "psbt": "cHNidP8BAF4CAAAAAWCr6uQ5IR7P2A6ik7h4dKbCWjJCntZcOpWSpHRUSkJJAAAAAAD9////ARiFAQAAAAAAIlEg7v5mVKEYsqt0Y1kgksu2lUlRymS9Nl7BwEaNiSD0FUAAAAAAAAEBK6CGAQAAAAAAIlEgrdnzmZSvWCLXmjMVhJB8Vhgs5TuuV7063affmjkaqexBFIZQ0aAu51kmnswVoWWb058Ggb4OaGPdl2yfCqy15Pi3DixkbKqXNfhOcM0rjGaPgJrlU7JTtcjlWKXkTkw9WY1ASSWAwzzkxmzqqB3k5+crFn3FE1vEYcClEUbZBzgp/DyO0txIZDfx517iosu6GWC3/eYlJGymZAX3mebY7uc8R0IVwQW6XN2fG653oYunKpwdHGARWajZr5avNWAskNVqmI0XDixkbKqXNfhOcM0rjGaPgJrlU7JTtcjlWKXkTkw9WY1tIIm1Fdba0za8AaEwjSo0sPSwoLXz/MisLEMeyGq7Ap3lrCBfF1WqqBGl2n8BVJkuVqwOtWNDHKaPHbvTIEoPC/t9Erog5pg06hPCAVVfAxdWhblq0Ohx5hfsagHyJkc4kCZVzum6Up0CqGaywEIVwQW6XN2fG653oYunKpwdHGARWajZr5avNWAskNVqmI0X3m1h12bY0iADdIDgEm63nPbmlDlgxH3JdpUPmfi3PHiLIHdTMPLV6KtmMMGWPfrVOWAJj0Ch9v2mcCn4HkvVv6h1rSBQhmqdglpqKVkJuFm/WN3+olURlPPGPe4BZAuwY4Af46wghlDRoC7nWSaezBWhZZvTnwaBvg5oY92XbJ8KrLXk+Le6IJeClkx2kw9Zo0351/jZDnkMNAZM5uHX1PNLhP/dLRk2ulKcwCEWBbpc3Z8brnehi6cqnB0cYBFZqNmvlq81YCyQ1WqYjRcNAHxGHl0AAAAAAAAAACEWUIZqnYJaailZCbhZv1jd/qJVEZTzxj3uAWQLsGOAH+M5AQ4sZGyqlzX4TnDNK4xmj4Ca5VOyU7XI5Vil5E5MPVmNY7V+8VcAAIABAACAAAAAgAAAAAAAAAAAIRZfF1WqqBGl2n8BVJkuVqwOtWNDHKaPHbvTIEoPC/t9EjkB3m1h12bY0iADdIDgEm63nPbmlDlgxH3JdpUPmfi3PHhw7NA6VwAAgAEAAIAAAACAAgAAAAAAAAAhFndTMPLV6KtmMMGWPfrVOWAJj0Ch9v2mcCn4HkvVv6h1OQEOLGRsqpc1+E5wzSuMZo+AmuVTslO1yOVYpeROTD1ZjTl6SlBXAACAAQAAgAAAAIAAAAAAAAAAACEWhlDRoC7nWSaezBWhZZvTnwaBvg5oY92XbJ8KrLXk+Lc5AQ4sZGyqlzX4TnDNK4xmj4Ca5VOyU7XI5Vil5E5MPVmNcOzQOlcAAIABAACAAAAAgAAAAAAAAAAAIRaJtRXW2tM2vAGhMI0qNLD0sKC18/zIrCxDHshquwKd5TkB3m1h12bY0iADdIDgEm63nPbmlDlgxH3JdpUPmfi3PHhjtX7xVwAAgAEAAIAAAACAAgAAAAAAAAAhFpeClkx2kw9Zo0351/jZDnkMNAZM5uHX1PNLhP/dLRk2OQEOLGRsqpc1+E5wzSuMZo+AmuVTslO1yOVYpeROTD1Zjcjjs9NXAACAAQAAgAAAAIAAAAAAAAAAACEW5pg06hPCAVVfAxdWhblq0Ohx5hfsagHyJkc4kCZVzuk5Ad5tYddm2NIgA3SA4BJut5z25pQ5YMR9yXaVD5n4tzx4yOOz01cAAIABAACAAAAAgAIAAAAAAAAAARcgBbpc3Z8brnehi6cqnB0cYBFZqNmvlq81YCyQ1WqYjRcBGCAdtG8GS5l2Hhf6MKJhRQP5YnS6vMqYoLU6CFNdHv5Z9wAA",
  "txid": "d45b273d629f14985480a3a46046b2c86c9276e9250ee0b4f84b5cc433233d00",
  "fee_paid_by": "clan",
  "fee_sats": 392,
  "max_fee_sats": 10000,
  "fee_rate_sat_vb": 2,
  "recipients": [],
  "signatures": {
    "count": 1,
    "required": 2,
    "signed_by_me": false,
    "names": [
      "Juma"
    ]
  },
  "oversight_signed": false,
  "created_at": "2026-11-05T09:00:00Z",
  "broadcast_txid": null,
  "confirmations": 0
} as const;

export const fixtureRefresh = {
  "id": "fixture-refresh",
  "clan_id": "preview",
  "kind": "refresh",
  "generation": 1,
  "destination": {
    "generation": 1,
    "keychain": "internal",
    "index": 4,
    "address": "tb1pwht3yn9q843m2gswqj8xxfwje5anl5gyqn69k3jtnp54ulhrqqdsmn9wtv"
  },
  "replaces": null,
  "replaced_by": null,
  "status": "awaiting_signatures",
  "psbt": "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",
  "txid": "de0d3b1825796e2ef120007a636458ec55a224ccda53222c4595fe69e99aa583",
  "fee_paid_by": "clan",
  "fee_sats": 392,
  "max_fee_sats": 10000,
  "fee_rate_sat_vb": 2,
  "recipients": [],
  "signatures": {
    "count": 1,
    "required": 2,
    "signed_by_me": false,
    "names": [
      "Juma"
    ]
  },
  "oversight_signed": false,
  "created_at": "2026-11-05T09:00:00Z",
  "broadcast_txid": null,
  "confirmations": 0
} as const;
