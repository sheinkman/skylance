# Selling gems and showing videos: setup guide

The game code is ready. Gem packs, free-gem videos, the age question and server-side purchase checks are all built. Until the steps below are done, the app shows Google's test ads, and the gem packs say "Gem packs are not switched on yet."

Do the steps in order. Steps 1–5 are needed before anything can be sold.

## How it works

| Piece | What it does |
|---|---|
| Age question | Shown once, on first launch. Keeps only the age group (under 13, 13–15, 16+), never the birth year. |
| Free gems video | Hangar, Gems tab: +40 gems per video, up to 5 a day. Ads appear nowhere else. |
| Ads for under 13 | Child-directed, rated G, never personalised (Google Play Families policy). No consent pop-up. |
| Ads for 13+ | Google's consent pop-up in Europe, then normal AdMob rewarded ads, rated PG at most. |
| Gem packs | Google Play Billing. Each purchase is sent to the `verify-purchase` server function, which asks Google whether it is real, records it once, and only then are gems added. Purchases interrupted by a crash or a slow payment finish on the next launch. |

Gem packs (the product IDs must match exactly):

| Product ID | Gems | Suggested price |
|---|---|---|
| `gems_300` | 300 | $0.99 |
| `gems_1000` | 1,000 | $2.99 |
| `gems_2200` | 2,200 | $5.99 |
| `gems_5000` | 5,000 | $11.99 |

The prices shown in the game come from Google Play, in each player's own currency. You set them in Play Console and can change them any time without a new app version. To change gem amounts, update both `PACKS` in `www/index.html` and `PACKS` in `supabase/functions/verify-purchase/index.ts`.

## 1. Google Play Console account

1. Sign up at [play.google.com/console](https://play.google.com/console). It costs $25 once, and Google verifies your identity.
2. **Important for new personal accounts:** before you can publish to everyone, Google requires a closed test with at least 12 testers who keep the app installed for 14 days. Start recruiting testers (family, friends, your son's friends' parents) early.

## 2. Payments profile

In Play Console go to **Settings → Payments profile** and create a merchant account. Fill in your bank details and tax information. Without this you cannot create paid products.

## 3. Create the app and a release key

1. **Create app**: name Skylance, type Game, Free. The package name is `com.skylance.game`.
2. Ask me to set up a **release build**. I will add the signing configuration and produce an `.aab` file, which is what Play Console accepts. You create the signing key and keep it, with its password, somewhere safe with a backup.
3. Accept **Play App Signing** when uploading the first build. Google then keeps the key that signs what players download, so a lost upload key can be replaced.

## 4. App content (Play Console → Policy → App content)

- **Privacy policy:** https://claude.ai/artifact/QBBvPTK3PFijCaoPGZkYQ4. First open it, choose **Share** and set it to anyone with the link, so Google can read it. The policy tells people to contact you through the developer email on your Play listing, so set that email.
- **Target audience:** select the age groups including under 13, plus 13–15, 16–17 and 18+. This puts the app in the **Families** program. Answer that the app has an age screen (it does: the birth-year question).
- **Ads:** Yes, the app contains ads.
- **Content rating:** fill in the questionnaire honestly (fantasy combat with insects, no blood, in-app purchases, no chat). Expect an Everyone or Everyone 10+ type rating.
- **Data safety:** use these answers.

  | Question | Answer |
  |---|---|
  | Collects or shares data? | Yes |
  | Encrypted in transit? | Yes |
  | Users can request deletion? | Yes (via the developer email) |
  | Device or other IDs | Collected and shared: advertising ID, by AdMob, for 13+ players only. Purpose: advertising. Also a random player code: collected, app functionality |
  | Purchase history | Collected: app functionality (verifying purchases) |
  | App activity, diagnostics | Shared with AdMob for ads and fraud prevention (13+) |
  | Location, personal info, contacts, photos, messages | Not collected |

## 5. Gem products

1. Play Console → **Monetize → Products → In-app products → Create product**.
2. Create the four products above with exactly those IDs, a name (for example "Satchel of Gems"), a short description and a price. Activate each one.

## 6. Test purchases for free

1. Play Console → **Settings → License testing**: add your own Gmail address (and your son's, if he has one).
2. Upload the release `.aab` to **Testing → Internal testing**, add yourself as a tester, and install the app from the test link.
3. Buy a pack: license testers see "Test card, always approves" and are not charged.

Purchases still say "not switched on" until step 7 is done.

## 7. Let the server check purchases with Google

This gives the `verify-purchase` function read-only permission to look up your app's orders.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project (any name, for example "skylance-billing").
2. **APIs & Services → Library**: enable **Google Play Android Developer API**.
3. **IAM & Admin → Service accounts → Create service account** (name: `skylance-verify`). Skip the optional roles.
4. Open the new service account → **Keys → Add key → JSON**. A `.json` file downloads. Treat it like a password: never email it, commit it or paste it into a chat.
5. In Play Console → **Users and permissions → Invite new users**: paste the service account's email (it ends in `iam.gserviceaccount.com`). Under **App permissions** add Skylance with **View financial data** and **Manage orders and subscriptions**. Send the invite (service accounts accept automatically).
6. In [Supabase](https://supabase.com/dashboard) → project **skylance** → **Edge Functions → Secrets**: add a secret named `GOOGLE_PLAY_SERVICE_ACCOUNT` and paste the entire contents of the JSON file as its value.

Google can take up to 24–36 hours to activate a new service account's Play access. Until then, purchases may fail verification; they finish automatically on a later launch.

## 8. AdMob

1. Sign up at [admob.google.com](https://admob.google.com) with the same Google account and add your payment details.
2. **Apps → Add app → Android**, and link it to the Play listing once it exists.
3. **Ad units → Add ad unit → Rewarded**. Name it "Free gems", reward 40, item "gems".
4. **Privacy & messaging → GDPR → Create message**: select the app and publish. This is the consent pop-up shown to 13+ players in Europe.
5. In the app's **Blocking controls**, set the maximum ad content rating to **PG**. Child requests are already limited to G by the game.
6. Send me two IDs: the **App ID** (`ca-app-pub-…~…`) and the **Rewarded ad unit ID** (`ca-app-pub-…/…`). These are not secret. I will put them in `android/app/build.gradle` (`admobAppId`) and `www/index.html` (`AD_REWARD_ID`), and switch `AD_TEST` to `false`.

While testing on your own phone, keep using test ads. Tapping your own real ads can get an AdMob account banned.

## Before each release

- `AD_TEST = false` and real AdMob IDs (step 8).
- Version number raised in `android/app/build.gradle` (`versionCode` and `versionName`).
- `npm audit` and the Supabase security advisor show nothing new.
- A test purchase works on the internal testing track.
