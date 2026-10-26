# Carl — Hosting Comparison

Status: **Research snapshot, 2026-10-25.** Free tiers change often. Re-verify the linked official pages before you sign up.
Legend: ✅ **Verified** (read on the provider's official page on 2026-10-25) · 🟡 **Reported** (secondary source or forum, not confirmed officially) · ⚪ **Assumption** (our estimate)

---

## 1. What Carl needs from a host

| Need | Why |
|---|---|
| **Always-on process** holding an outbound WebSocket to the Discord Gateway | discord.py bots are gateway clients. A sleeping process can't receive slash commands or send reminders. |
| Persistent disk for one SQLite file (+ backups, < 1 GB) | All state lives there |
| ~150 MB RAM, near-zero CPU | ⚪ discord.py with the GUILDS intent for one small server |
| Outbound HTTPS only; **no inbound ports** | Gateway bot, no webhook endpoint |
| Minimal egress | ⚪ Gateway heartbeats + a few hundred messages/month; estimated well under 100 MB/month. Measure in Phase 5. |

A platform that sleeps when there's no inbound HTTP traffic is unsuitable. A gateway bot gets no inbound HTTP, so it would sleep and never wake. Keep-alive pinging to defeat sleep is excluded on principle; at least one provider's staff calls it abuse (Render community).

## 2. Summary table

| Option | Always-on? | Persistent disk | Cost | Verdict |
|---|---|---|---|---|
| **Google Cloud e2-micro (Always Free)** | ✅ yes, a normal VM | ✅ 30 GB-month standard PD | $0 within limits; credit card required | **Recommended primary** |
| Oracle Cloud Always Free (A1 Arm / E2.1.Micro) | ✅ VM, **but** idle instances may be reclaimed | ✅ 200 GB block | $0; card required | Viable, with reclamation risk; second choice |
| Raspberry Pi at home | ✅ | ✅ SD/SSD | 🟡 one-time ~$45–$80 board + PSU/storage; electricity ⚪ ~$5–10/yr | **Recommended alternative** once you own a Pi |
| Low-cost VPS (e.g. Hetzner) | ✅ | ✅ | 🟡 ~€4.50–6/mo after 2026 increases | Paid fallback |
| AWS (new accounts, post-July-2025) | ✅ VM | ✅ | ✅ Free plan is credits ($100 + up to $100) and ends after 6 months | Not "free forever"; skip |
| Render free | ❌ web services spin down after 15 min idle; background workers not free | ❌ local FS lost on spin-down | $0 | Unsuitable |
| Koyeb free | ❌ scales to zero after 1 h without traffic; no worker services, no volumes | ❌ | $0 | Unsuitable |
| Fly.io | ✅ (machines) | ✅ volumes | ✅ No free allowance for new orgs (legacy only); one-time trial credit | Paid only for new users |
| Railway | ✅ | ✅ | ✅ Hobby $5/mo; trial one-time $5 | Paid only |
| Cloudflare Workers (HTTP interactions + Cron Triggers) | n/a (serverless) | D1 (not verified) | $0 within limits | Possible only with a full redesign; rejected (ADR-004) |
| GitHub Actions scheduled workflows | ❌ | ❌ | $0 | Unsuitable: schedule is best-effort, no gateway, no state |

## 3. Detailed findings

### 3.1 Google Cloud Free Tier — Compute Engine e2-micro ✅ (recommended)

From Google's Free Tier docs ([docs.cloud.google.com/free/docs/free-cloud-features](https://docs.cloud.google.com/free/docs/free-cloud-features)):
- ✅ "1 non-preemptible e2-micro VM instance per month" in **Oregon (us-west1), Iowa (us-central1), or South Carolina (us-east1)**.
- ✅ The limit is by time, not instance count: free up to the hours in the month, combined across those regions.
- ✅ **30 GB-months standard persistent disk.**
- ✅ **1 GB/month outbound** from North America (excluding China/Australia destinations).
- ✅ A billing account is required. The Free Tier has no end date, but Google may change it with 30 days' notice.
- 🟡 In-use external IPv4 addresses: a forum quote of Google's docs says in-use external IPs are free up to the month's hours. Google's VPC pricing page lists $0.005/hr for a standard VM's in-use IPv4 outside free usage. **Verify on your first bill.** The $1 budget alert catches it.
- 🟡 Community guides warn that balanced/SSD disks and disks over 30 GB are billed.
- ⚪ e2-micro has ~1 GB RAM and a shared, burstable CPU. That is plenty for Carl (≤ 150 MB) plus Docker; add 1 GB swap for safety.

**Pros:** a normal VM with no idle reclamation policy found in the docs; reliable network; x86 (amd64). **Cons:** credit card required and misconfiguration can cost money; 1 GB egress cap (Carl uses a small fraction ⚪); US regions only.

### 3.2 Oracle Cloud Infrastructure Always Free ✅ (second choice)

From [docs.oracle.com … FreeTier/resourceref.htm](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm):
- ✅ Ampere A1 (Arm): **1,500 OCPU-hours and 9,000 GB-hours per month**, "equivalent to 2 OCPUs and 12 GB of memory." This is half the older 4 OCPU / 24 GB allowance, as reported by [Linuxiac](https://linuxiac.com/?p=214114); the effective date is unclear 🟡.
- ✅ Up to two VM.Standard.E2.1.Micro (AMD, 1/8 OCPU, 1 GB RAM).
- ✅ 200 GB total block volume storage; 5 volume backups.
- ✅ Must be created in the tenancy's **home region**. "Out of host capacity" errors happen; retry or try another availability domain.
- ✅ **Idle reclamation:** an instance is idle if over 7 days the 95th-percentile CPU < 20%, network < 20%, and (A1 only) memory < 20%. **Carl will always look idle by this definition.**
- 🟡 Community reports say a Pay-As-You-Go upgrade exempts instances from idle reclamation, while Always Free resources stay free. This rests on a 2023 Oracle email ([51sec blog](https://blog.51sec.org/2023/02/oracle-cloud-cleaning-up-idle-compute.html)); not confirmed in current docs. Reported one-time verification holds on cards.
- ❌ **Do not** run synthetic load ("NeverIdle"/"lookbusy") to dodge reclamation. It works around the provider's policy, which this design excludes.

**Verdict:** more resources than GCP and arm64 works with our image. But on a free-only account, the documented reclamation rule makes it unreliable for an idle bot. Use it only after upgrading to PAYG and confirming the exemption with Oracle. Backups must be off-host either way.

### 3.3 Raspberry Pi at home 🟡

- 🟡 Prices rose in 2026 because of DRAM costs: Pi 5 2 GB reportedly **$77.50** from Oct 1 2026 ([OMG! Ubuntu](https://www.omgubuntu.co.uk/2026/10/raspberry-pi-2gb-costs-how-much-now)); Pi 5 1 GB reportedly still **$45** ([The Register](https://www.theregister.com/2026/02/02/raspberry_pi_ram_shortage_price_hike/)). Add PSU, case, and SSD/high-endurance SD.
- ⚪ Power ~3–5 W average → roughly 26–44 kWh/yr.
- **Pros:** no third-party account or card; full control; also hosts Pi-hole. **Cons:** home power or internet outages take the bot down; SD-card wear; you're the ops team. See `security-and-operations.md` §10.4.

### 3.4 Paid VPS fallback 🟡

- 🟡 Hetzner raised cloud prices in April and June 2026. Third-party trackers put the smallest shared plans around **€4.49–€5.99/mo**, with reported "currently not available" stock for the cheapest lines in Aug 2026 ([findstack](https://findstack.com/resources/hetzner-price-increase-2026), [privatedevops](https://privatedevops.com/news/hetzner-june-2026-cloud-price-increase-what-to-do)). Not verified on Hetzner's page.
- ⚪ Other small-VPS providers commonly list $4–6/mo plans (not researched in this pass). Any 1 vCPU / 512 MB–1 GB Linux VPS runs Carl unchanged.

### 3.5 Platforms that sleep or have no free tier

- **Render** ✅ ([render.com/docs/free](https://render.com/docs/free)): free web services spin down after 15 min with no inbound traffic, and local filesystem changes are lost on spin-down. Only web services, Postgres, and Key Value have free instances, so no free background workers. Free Postgres expires after 30 days. → Unsuitable.
- **Koyeb** ✅ ([koyeb.com/docs/run-and-scale/scale-to-zero](https://www.koyeb.com/docs/run-and-scale/scale-to-zero)): free instance scales to zero after 1 h without traffic. 🟡 No worker services or volumes on free; card verified with a hold ([pricing FAQ](https://www.koyeb.com/docs/faqs/pricing)). → Unsuitable.
- **Fly.io** ✅ ([fly.io/docs/about/discontinued-plans](https://fly.io/docs/about/discontinued-plans/)): legacy free allowances only for organizations that predate the change. New organizations get a one-time trial credit and pay per use. → Paid.
- **Railway** ✅ ([docs.railway.com/pricing/plans](https://docs.railway.com/pricing/plans)): Hobby $5/month including $5 usage; trial is a one-time $5 grant. → Paid.
- **AWS** ✅ ([AWS announcement, 2025-07](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/)): new accounts get up to $200 in credits, and the Free plan ends after 6 months or when credits are used up. → Not a long-term free host.

### 3.6 Serverless / scheduled architectures

- **Cloudflare Workers** ✅ ([limits](https://developers.cloudflare.com/workers/platform/limits/)): Free plan 100,000 requests/day, **10 ms CPU per invocation**, 128 MB memory, 5 Cron Triggers per account. A Discord bot can run as an HTTP *interactions endpoint* (no gateway) with cron for reminders. However: discord.py can't be used; the 10 ms CPU limit is tight for signature verification plus DB work; storage (D1, not verified here) and cron are vendor-specific; moving hosts means a rewrite. Rejected for v1 (ADR-004). Could be revisited if hosting becomes the blocker.
- **GitHub Actions cron**: documented as best-effort (delays and skipped runs under load) ⚪. No persistent state. Unsuitable for reminders.

## 4. Recommendation

1. **Start on Google Cloud e2-micro (Always Free)** in `us-central1`, `us-east1`, or `us-west1`, with a standard 30 GB disk, Debian, Docker Compose, and a **$1 budget alert**. It's the only verified free, always-on VM without an idle-reclamation rule that Carl would trip.
2. **Off-host backups from day one** (weekly pull to your PC).
3. **If you later buy a Pi**, move Carl there using the procedure in `security-and-operations.md` §10.5. The Pi-hole coexistence design is ready.
4. **If GCP ever charges or changes terms:** move to a ~€5/$5 VPS. Same compose file, same data file.
5. Oracle only if you're willing to upgrade to PAYG and confirm the idle-reclamation exemption with Oracle.

Portability check: every recommended option is a plain Linux box running the same multi-arch image with the same `.env` and `data/`. No core logic depends on the host.

## 5. Raspberry Pi sizing (if/when)

| Board | Verdict for Pi-hole + Carl |
|---|---|
| Pi 5 2 GB / Pi 4 2 GB+ | Comfortable; recommended |
| Pi 5 1 GB | Works ⚪ (≈ 400 MB headroom); keep Carl's 256 MB limit |
| Pi 3B+ / Zero 2 W (1 GB / 512 MB, arm64) | Possible but tight ⚪; slower Docker builds. Build the image on your PC with `docker buildx --platform linux/arm64` |

## Sources (accessed 2026-10-25)
- Google Cloud Free Tier: https://docs.cloud.google.com/free/docs/free-cloud-features
- Google VPC pricing (external IPs): https://cloud.google.com/vpc/pricing-announce-external-ips
- Oracle Always Free resources: https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm
- Linuxiac on Oracle A1 reduction: https://linuxiac.com/?p=214114
- 51sec on Oracle idle reclamation / PAYG: https://blog.51sec.org/2023/02/oracle-cloud-cleaning-up-idle-compute.html
- AWS Free Tier change: https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/
- Render free: https://render.com/docs/free
- Koyeb scale-to-zero: https://www.koyeb.com/docs/run-and-scale/scale-to-zero ; pricing FAQ: https://www.koyeb.com/docs/faqs/pricing
- Fly.io discontinued plans: https://fly.io/docs/about/discontinued-plans/
- Railway plans: https://docs.railway.com/pricing/plans
- Cloudflare Workers limits: https://developers.cloudflare.com/workers/platform/limits/
- Raspberry Pi prices: https://www.omgubuntu.co.uk/2026/10/raspberry-pi-2gb-costs-how-much-now ; https://www.theregister.com/2026/02/02/raspberry_pi_ram_shortage_price_hike/
- Hetzner 2026 prices: https://findstack.com/resources/hetzner-price-increase-2026 ; https://privatedevops.com/news/hetzner-june-2026-cloud-price-increase-what-to-do
- discord.py release (2.7.1, 2026-03-03): https://pypi.org/project/discord.py/
- Discord gateway intents: https://docs.discord.com/developers/events/gateway
