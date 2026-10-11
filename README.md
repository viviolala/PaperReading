# Daily literature briefing

This repository runs a literature briefing in GitHub Actions at approximately
08:00 Asia/Singapore every day. GitHub hosts the scheduled job, so the computer
can be asleep or off. GitHub scheduled jobs can start late; the script calculates
the search window from the actual run time.

The workflow queries Crossref for new journal articles, checks accessible primary
publisher pages, and queries the official bioRxiv API for new or updated
preprints. GitHub Models drafts the Chinese analysis from those sources. A local
`state.json` records delivered DOI/version identifiers to reduce repeats. The
brief is sent from `violatsian@gmail.com` to the same address through Gmail SMTP.
No ChatGPT subscription or separate OpenAI API key is used. GitHub Models access
and the Gmail app password must be available for the workflow to succeed.

## One-time setup

1. In the GitHub repository, open **Settings → Secrets and variables → Actions →
   New repository secret**. Add `GMAIL_APP_PASSWORD`, using a Google **app
   password** for `violatsian@gmail.com` (not the ordinary Gmail password).
   Google requires two-step verification for app passwords. Never paste the
   password into chat or a repository file.
2. Open **Actions → Daily literature brief → Run workflow**. Leave **dry_run**
   enabled for the first test. Read the job log: it should show the source checks
   and a report, and should not send mail. If GitHub Models is unavailable to
   this repository, the job will fail clearly before emailing.
3. Run the workflow again with **dry_run** off to test delivery. Confirm receipt
   in Gmail, including **All Mail**, **Sent**, and **Spam**. The job logs only
   whether Gmail SMTP accepted the message; inbox arrival still needs checking.
4. After the cloud run is verified, disable the old local Codex automation to
   avoid duplicate or delayed reports when the computer wakes.

The Actions schedule runs only from the repository's default branch. GitHub may
disable scheduled workflows after a long period without repository activity;
check the Actions page if daily messages stop. Review any failed workflow run;
the program never labels an unverified day as a successful zero-paper day.

## Limits

Publisher and API records often expose only dates, not publication times. A
paper on a 24-hour window boundary is marked uncertain rather than assigned an
invented time. Inaccessible publisher pages are excluded. A zero-paper report
is still emailed when searches run successfully and no suitable records exist.
GitHub Models availability and daily free usage limits depend on the repository.

This workflow does not post into the existing Codex conversation. Its durable
delivery channel is email. It also does not reuse the Personal Gmail connector:
that connector's authorization is not available inside GitHub Actions.
