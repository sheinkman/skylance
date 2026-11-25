# Security notes

What protects Skylance players and the backend, and the rules to keep when changing the game.

## What the game accepts from outside

| Input | Where it comes from | Protection |
|---|---|---|
| Challenge links (`#c-R-L-SCORE-CODE`, `skylance://challenge/...`) | Anyone can craft one | Strict pattern match (digits and a 6-character code only, length-capped); shown with `textContent`, never as HTML |
| Saved progress (`localStorage`) | Can be edited or corrupted on the device | `loadSave()` copies only known fields, checks types, caps numbers and drops unknown items |
| Install referrer | Google Play | Only a `ref=` code matching `[a-z0-9]{6}` is used |
| Supabase replies | Backend | Only `true` or a number between 0 and 50 is trusted |

## Browser and WebView protection

- A Content Security Policy in `www/index.html` allows scripts only from the game itself. Network requests can go only to the game's own files and the Supabase project, so injected code could not load outside scripts or send data elsewhere.
- No `eval`, no external scripts, no third-party SDKs, and no `innerHTML` with outside data.
- Android: WebView debugging is on only in debug builds, mixed content and plain-HTTP traffic are off, the file provider is not exported, and the only permission is Internet.

## Backend (Supabase)

- Tables have row-level security on, no policies, and no table grants: nobody can read or change them through the API.
- The public API is three functions: `register_player`, `claim_referral` and `collect_referral_rewards`. Each checks the player's secret and validates every argument.
- Rate limits:
  - at most 30 new players per network per hour
  - at most 5 accepted referrals per network per day
  - at most 10 referrals per inviter per day
  - a global brake of 3,000 new players per 10 minutes
- Networks are identified only by a salted SHA-256 hash of the IP address. Raw addresses are never stored, and the log is pruned after 2 days.
- The publishable key in the game is meant to be public. The service-role key and database password must never appear in this repository or the app.

## Rules to keep

1. Never put a secret key in `www/index.html` or the Android project. Anything shipped in the app can be read by anyone.
2. Never commit the release signing key (`*.jks`, `*.keystore`). Store it and its passwords in a safe place with a backup: losing it means you cannot update the game on Google Play. Enrolling in Play App Signing lets Google keep the app signing key.
3. Gems and progress live on the device, so players can edit them. That only affects their own game. If gems are ever sold for real money, verify every Google Play purchase on a server, and treat client-side gems as untrusted.
4. When adding UI that shows outside data, use `textContent`, not `innerHTML`.
5. Before each release, run `npm audit` and the Supabase security advisor.
