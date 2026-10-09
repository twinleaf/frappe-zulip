# Frappe Zulip

A Frappe v16 app that sends ERPNext notifications to Zulip. It:

- adds a **Zulip** channel to Notification rules, which can post to a Zulip channel, DM each recipient, or both;
- copies bell-icon notifications (assignments, @mentions, shares) to the user as Zulip DMs;
- delivers every message in the background through a logged outbox, with retries.

See [PLAN.md](PLAN.md) for the design.

## Install

```bash
cd ~/frappe-bench
bench get-app <git-url-of-this-repo>
bench --site <site> install-app frappe_zulip
bench --site <site> migrate
```

The background workers and scheduler must be running (`bench doctor` shows them). Without them, messages stay Queued.

## Set up Zulip

1. In Zulip, go to **Personal settings → Bots** and add an **Incoming webhook** bot named "ERPNext". Note its email and API key.
2. General notifications go to the **ERPNext** channel, topic **Notifications**. If the channel is private, subscribe the bot to it. Add more channels later if some events need their own.
3. Check **Organization settings → Who can access user email addresses**. If it isn't "Everyone", DMs only work for users mapped by **Sync Users** (step 5 below).

## Configure ERPNext

1. Open **Zulip Settings**. Enter the bot email and API key, tick **Enabled**, and save.
2. Check **Default Channel** and **Default Topic** (ERPNext and Notifications). Rules that don't name their own channel or topic post there.
3. Click **Send Test Message**. It goes to the default channel, topic "ERPNext test", so it doesn't clutter Notifications.
4. Under **Forward These Notification Types**, pick the bell notifications to copy as DMs. Assignment, Mention and Share are preselected. Leave out Alert: Notification rules send those, and they have their own Zulip channel.
5. Click **Sync Users** and enter a Zulip admin's email and API key. Incoming webhook bots can't list users. The admin key is used for that one call and isn't saved. The sync stores each user's Zulip ID in **User → Zulip User ID**. Users it couldn't match are listed so you can fill in the ID by hand.

To try things out without sending anything, tick **Dry Run**. Messages are then recorded in the Message Log as Skipped.

## Notification rules

These rules are installed and enabled. Change or disable them under **Notification**:

- **Zulip: Task Created** posts to ERPNext › Notifications.
- **Zulip: Task Due Tomorrow** DMs the assignees.
- **Zulip: Task Overdue** posts to ERPNext › Notifications and @-mentions the assignees, then again every 7 days until the task is closed.
- **Zulip: Task Completed** posts to ERPNext › Notifications.
- **Zulip: ToDo Due Tomorrow** DMs the assignee of any open To Do with a due date of tomorrow. To Dos for Tasks and Asset Maintenance are left out because their own rules cover them.
- **Zulip: Asset Maintenance Due Tomorrow** DMs the assignee of a planned Asset Maintenance Log.
- **Zulip: Asset Maintenance Overdue** DMs the assignee the day after the due date, then every 7 days until the log is completed or cancelled.

The Task and Asset Maintenance rules are only installed when ERPNext is.

To add a rule, create a Notification and set **Channel** to Zulip. Then set:

- **Post to Zulip Channel**: on by default. Turn it off to only send DMs.
- **Zulip Channel**: leave empty for the default channel (ERPNext).
- **Zulip Topic**: a Jinja template. Leave empty for the default topic (Notifications). Use `{{ zulip.topic(doc.doctype, doc.name) }}` to give each document its own topic.
- **Direct Message Each Recipient**: DMs everyone in the Recipients table, or all assignees.
- **Mention Recipients in Channel Post**: @-mentions them in the channel post.
- **Repeat Every (Days)**: for Days After rules only. Sends the message again every this many days for as long as the condition holds, so the condition must stop matching once the document is done. 0 sends it once.

Write the **Message** in Zulip Markdown. A link to the document is appended automatically. Templates can use:

| Helper | Result |
|---|---|
| `{{ zulip.mention(doc.owner) }}` | `@**Jane Doe\|12**`, which notifies the user (their full name if they haven't been synced) |
| `{{ zulip.mention(doc.owner, silent=True) }}` | `@_**Jane Doe\|12**`, which names the user without notifying them |
| `{{ zulip.topic("Project", doc.project) }}` | `PROJ-0007: Gradiometer`, a document's standard topic |
| `{{ zulip.markdown(doc.description) }}` | The HTML of a text editor field as Zulip Markdown |

Users can turn off Zulip DMs under **My Settings → Notifications → Send Direct Messages to Zulip**.

## Message Log

**Zulip Settings → Message Log** lists every message with its status:

- **Queued**: waiting for delivery or for a retry. Timeouts, rate limits and 5xx errors are retried after 1, 5, 15 and 60 minutes.
- **Sent**: delivered; the Zulip message ID is recorded.
- **Failed**: Zulip rejected it, for example an unknown channel or user, or the retries ran out. The error is shown, and the **Retry** button sends it again.
- **Skipped**: dry run, or the integration was disabled.

Finished messages are deleted after 30 days. Change this under **Log Settings**.

## Tests

The formatting and HTTP client tests don't need a bench:

```bash
uv run --no-project --python 3.14 --with requests python -m unittest frappe_zulip.tests.test_formatting frappe_zulip.tests.test_zulip_client
```

The full suite runs on a test site:

```bash
bench --site <test-site> set-config allow_tests true
bench --site <test-site> run-tests --app frappe_zulip
```

## Uninstall

```bash
bench --site <site> uninstall-app frappe_zulip
```

This disables Zulip Notification rules and removes the custom fields and property setters.
