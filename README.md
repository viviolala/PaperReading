# Daily literature briefing

**Status: prototype; no daily schedule is enabled.** The cloud smoke test on
2026-10-11 retrieved Crossref and bioRxiv candidates, but all sampled publisher
pages returned HTTP 403, and GitHub Models returned plain text rather than a
model response. No email was sent. The workflow is manual only while those
blockers are addressed. Do not treat this repository as an active briefing.

The intended schedule is approximately 08:00 Asia/Singapore every day. A
GitHub-hosted scheduled job would work while the computer is asleep or off,
but GitHub can start scheduled jobs late; the script calculates the search
window from the actual run time.

The workflow queries Crossref for new journal articles, checks accessible primary
publisher pages, and queries the official bioRxiv API for new or updated
preprints. GitHub Models drafts the Chinese analysis from those sources. A local
`state.json` records delivered DOI/version identifiers to reduce repeats. The
brief is sent from `violatsian@gmail.com` to the same address through Gmail SMTP.
The current prototype attempts to use GitHub Models without a separate OpenAI
API key. That attempt failed in the cloud test. A supported research model with
access to primary article pages is still needed, along with an email credential.

## One-time setup

**Do not configure an email secret or turn on daily scheduling yet.** First,
replace the failed model/source route and verify it using the manual dry run.
The likely route requires an OpenAI API key for the Responses API with web
search; API usage is billed separately from a ChatGPT subscription. After that
route passes its cloud test:

1. In the GitHub repository, open **Settings → Secrets and variables → Actions →
   New repository secret**. Add `GMAIL_APP_PASSWORD`, using a Google **app
   password** for `violatsian@gmail.com` (not the ordinary Gmail password).
   Google requires two-step verification for app passwords. Never paste the
   password into chat or a repository file.
2. Open **Actions → Daily literature brief → Run workflow** for a dry run.
   Read the job log: it should show the source checks and a report, and cannot
   send mail in the current workflow.
3. After the model/source route passes, update the workflow to enable sending
   and test delivery. Confirm receipt
   in Gmail, including **All Mail**, **Sent**, and **Spam**. The job logs only
   whether Gmail SMTP accepted the message; inbox arrival still needs checking.
4. Enable daily scheduling only after the cloud dry run and mail delivery both
   pass. Then disable the old local Codex automation to avoid duplicate or
   delayed reports when the computer wakes.

The Actions schedule runs only from the repository's default branch. GitHub may
disable scheduled workflows after a long period without repository activity;
check the Actions page if daily messages stop. Review any failed workflow run;
the program never labels an unverified day as a successful zero-paper day.

## Limits

Publisher and API records often expose only dates, not publication times. A
paper on a 24-hour window boundary is marked uncertain rather than assigned an
invented time. Inaccessible publisher pages are excluded. A zero-paper report
is still emailed when searches run successfully and no suitable records exist.
The failed GitHub Models route should not be assumed available to this repository.

This workflow does not post into the existing Codex conversation. Its durable
delivery channel is email. It also does not reuse the Personal Gmail connector:
that connector's authorization is not available inside GitHub Actions.
