# ERPNext → Zulip notifications: plan

Send ERPNext events to a Zulip server, either as posts in a channel, as direct messages (DMs) to the people responsible, or both.

## What I checked

**Zulip** (`/api/v1/server_settings`): version 12.2, feature level 500. Users sign in through SAML (JumpCloud). Bots use API keys, so SAML doesn't affect them.

- An **Incoming webhook** bot can call `POST /api/v1/messages`, for both channel posts and DMs, and nothing else. That's the least privilege we need.
- The Slack-compatible endpoint, `/api/v1/external/slack_incoming`, only posts to channels. It takes the topic from the URL `topic` parameter, or failing that from the payload's `channel` field.
- Topics can be at most 60 characters long.

**Frappe/ERPNext** (`version-15` branch source; check this against the installed version):

- `Notification` already supports conditions, Jinja templates, the events New, Save, Submit, Cancel, Value Change, Days Before/After and Method, and recipients chosen by field, role or assignee. Its channels are Email, Slack, System Notification and SMS. `send_notification_by_channel()` is a clean place to add a new channel.
- The built-in Slack channel calls `requests.post` synchronously, inside the save, with no timeout. If Zulip were slow, ERPNext saves would hang.
- The `Webhook` doctype runs as a background job after the database commit. Its URL and JSON body are Jinja templates, and every request is written to the Webhook Request Log, URL included.
- Every bell-icon notification (assignments, @mentions, shares, alerts) is stored as a `Notification Log` row with `for_user`, `from_user`, `type`, `subject`, `document_type` and `document_name`.

## Goals

1. **Channel posts** for business events (orders, production, quality, support), with one topic per document so all updates about a document stay in one thread.
2. **DMs** for personal events: a task assigned to you, an @mention, a task due soon or overdue.
3. **Configured in the ERPNext UI.** Adding a rule shouldn't require a deploy.
4. **ERPNext keeps working when Zulip is down.** A failed send must never block or fail a save in ERPNext.

## Options considered

| Approach | Channel | DM | Topic per doc | Code | Drawbacks |
|---|---|---|---|---|---|
| A. Notification (Slack channel) → `slack_incoming` | ✅ | ❌ | ❌ fixed per URL | none | Sends inside the save with no timeout |
| B. Webhook doctype → `slack_incoming` | ✅ | ❌ | ✅ via payload `channel` | none | API key sits in the URL and the request log; no Days Before/After or Value Change events |
| C. **Custom Frappe app → `POST /api/v1/messages`** | ✅ | ✅ | ✅ | small app | Needs an app install (self-hosted bench, or a Frappe Cloud private bench) |
| D. Server Script calling `frappe.make_post_request` | ✅ | ✅ | ✅ | Python in the UI | Sends inside the save; needs `server_script_enabled` |

**Recommendation: C.** It's the only option that does DMs, per-document topics, background sending and encrypted credential storage together, and it builds on the Notification UI admins already know. If a custom app can't be installed, use B for channel posts and D for DMs (see the fallback section at the end).

## Design: the `frappe_zulip` Frappe app

### 1. Zulip setup (Zulip admin, done once)
- Create an **Incoming webhook** bot named "ERPNext" and give it an ERPNext avatar.
- General notifications go to an **ERPNext** channel, topic **Notifications**. If it's private, subscribe the bot. Other channels, such as `#erp-sales` or a private `#erp-finance`, can be added later for events that need their own audience.
- **Check the email visibility setting** (Organization settings → "Who can access user email addresses"). If it is not "Everyone", users' API emails are placeholders like `user12@your-org.zulipchat.com`, so DMs have to be addressed by Zulip user ID (see §4).
- Optional: add a linkifier, for example `TASK-\d{4}-\d+` → `https://<erp-host>/desk/task/{id}`, so document IDs typed by hand in Zulip become links.

### 2. `Zulip Settings` (a single settings doctype in ERPNext)
- `enabled` (master kill switch), `server_url`, `bot_email`, `api_key` (a **Password** field, so it is encrypted at rest).
- `default_channel` and `default_topic` (ERPNext and Notifications): where rules post unless they set their own.
- `dry_run` (record what would be sent in the Zulip Message log instead of sending; for staging).
- `dm_notification_types`: which bell-notification types are copied to DMs (§6).
- Buttons: **Send test message** and **Sync Zulip users** (see §4).

### 3. Sending client (`frappe_zulip/zulip.py`)
- `send_channel_message(channel, topic, content)` and `send_direct_message(user_id, content)`. Both send a form-encoded `POST /api/v1/messages` with HTTP Basic auth and a 10-second timeout.
- **Messages go through an outbox.** Each one is saved as a `Zulip Message` record (Queued → Sent, Failed or Skipped) and delivered by `frappe.enqueue(..., queue="short", enqueue_after_commit=True)`. Nothing is sent for a rolled-back transaction, a slow or down Zulip never blocks a save, and every message is visible under Zulip Settings → Message Log with a Retry button.
- Topics are cut to 60 characters on a word boundary.
- Retries: a scheduler sweep (every few minutes) retries a 429, 5xx or timeout after 1, 5, 15 and 60 minutes (or `Retry-After`, if longer), 5 attempts in all. Any other 4xx (unknown channel or user) marks the message Failed with Zulip's error. A row lock stops the job and the sweep sending the same message twice. Finished messages are cleared after 30 days.
- Nothing is queued during install, migrate or patches, or during a data import with emails muted, so a bulk import can't flood Zulip.

### 4. Mapping ERPNext users to Zulip users
- Add a custom field `zulip_user_id` (Int) to `User`.
- **Sync Zulip users** calls `GET /api/v1/users` and matches each user on `delivery_email`. ERPNext and Zulip both sign in through JumpCloud, so the emails should match. An incoming webhook bot isn't allowed to call this endpoint, so the sync uses an admin's API key entered once and never saved (or a `bench execute` command). Unmatched users are listed so they can be fixed by hand.
- When sending, use the user ID if it is set. Otherwise address the DM by email, which only works if email visibility is "Everyone". If neither works, skip the DM and log it.
- Send DMs **one recipient at a time**. A single message to several users would create a group DM instead.

### 5. A "Zulip" channel on Notification (the main admin interface)
- A Property Setter adds `Zulip` to `Notification.channel`. Custom fields, shown only when the channel is Zulip:
  - `zulip_post_to_channel` (Check, on by default)
  - `zulip_stream` (Data, labelled "Zulip Channel"; defaults to the settings' default channel)
  - `zulip_topic` (a Jinja template; defaults to the settings' default topic; `zulip.topic(doctype, name)` gives a topic per document)
  - `zulip_dm_recipients` (Check): DM each person from the Recipients table
  - `zulip_mention_recipients` (Check): @-mention the recipients in the channel post, which also notifies them
- Templates get a `zulip` helper: `zulip.mention(user, silent=False)` and `zulip.topic(doctype, name)`.
- `extend_doctype_class = {"Notification": "frappe_zulip.notification.ZulipNotificationMixin"}` extends `validate()` and `send_notification_by_channel()`, so it composes with other apps' Notification extensions. For Zulip rules it:
  1. renders `message` (written in Zulip markdown) and `zulip_topic`, and appends a link to the document;
  2. queues the channel post if `zulip_post_to_channel` is on;
  3. if DMs are enabled, gets the recipients from the inherited `get_list_of_recipients()` (document fields, roles, "Send to All Assignees"), maps each to a Zulip user and queues one DM per person.
- Every Notification feature then works for Zulip with no extra code: conditions, Value Change, and the daily Days Before/After check.
- The Task rules in §7 are created **enabled** on install. Rules added later are inserted by a patch on migrate; existing rules are never overwritten. Admins can add their own in **Setup → Notification**.

### 6. Copying bell notifications to DMs
- `doc_events = {"Notification Log": {"after_insert": "frappe_zulip.notification_log.forward_to_zulip"}}` DMs `for_user` with the title, converted from HTML to markdown, a quoted excerpt, and a link to the document.
- This covers being assigned anything (including Tasks), @mentions in comments, and shared documents, with no per-doctype rules.
- Copied by default: `Assignment`, `Mention`, `Share`. Not copied: `Energy Point`, and `Alert`. Alerts come from Notification rules, which have their own Zulip channel, so copying them would send duplicates.
- Frappe already skips notifications to yourself. DMs are also skipped for disabled users and users who opted out: a custom field `enable_zulip_notifications` on `Notification Settings`, which each user can change under My Settings → Notifications.

### 7. Rules to ship first

| Event | Trigger | Where |
|---|---|---|
| Task created | New, status not Template | Post in ERPNext › Notifications |
| Task assigned | Notification Log copy | DM to assignee |
| Task due tomorrow | Days Before 1 on `exp_end_date`, status not Completed/Cancelled | DM to assignees |
| Task overdue | Days After 1 on `exp_end_date`, same condition, repeated every 7 days | Post in ERPNext › Notifications, @-mentioning the assignees |
| Task completed | Value Change on `status` → Completed | Post in ERPNext › Notifications |
| @mention in any comment | Notification Log copy | DM |
| To Do due tomorrow | Days Before 1 on ToDo `date`, status Open, not for Task or Asset Maintenance | DM to the assignee |
| Asset maintenance due tomorrow | Days Before 1 on Asset Maintenance Log `due_date`, status Planned or Overdue | DM to `task_assignee_email` |
| Asset maintenance overdue | Days After 1 on `due_date`, same condition, repeated every 7 days | DM to `task_assignee_email` |

Asset Maintenance creates one ToDo per assignee and leaves its date at the first due date after later cycles are logged. Each Asset Maintenance Log, by contrast, has the cycle's real due date and status, so the maintenance rules use the log.

Frappe's Days After fires only on the day that exactly matches. `zulip_repeat_days` on Notification makes a Zulip rule also match every N days after that. The mixin overrides `get_documents_for_today`, and the rule's condition decides when it stops.

Proposed next, to confirm with the team:
- Sales Order submitted → `#erp-sales`
- Delivery Note submitted → `#erp-sales`
- Purchase Order submitted → `#erp-purchasing`
- Purchase Receipt submitted → `#erp-purchasing`
- Material Request auto-created for reorder → `#erp-purchasing`
- Work Order completed → `#erp-production`
- Quality Inspection rejected → `#erp-production`
- Issue opened → `#erp-support`
- Payment Entry received → private `#erp-finance`

### 8. Message format

Example post in ERPNext › Notifications:

```
**Task completed** by @_**Jane Doe|12**
[TASK-2026-00042](https://<erp-host>/desk/task/TASK-2026-00042) · Project: PROJ-0007 · Due 2026-10-05
```

- Use silent mentions (`@_**Name|id**`) to name the person who acted without notifying them. Use regular mentions only where someone should be notified.
- Think about what each channel's audience may see. Amounts, customer names and HR data belong in private channels only.

## Security
- The API key is stored only in a Password field. It never goes into URLs, the Webhook Request Log or Error Log text.
- The Incoming webhook bot type can send messages but can't read them.
- Only System Managers can write templates. Notification is already restricted that way.
- Traffic is outbound HTTPS from ERPNext to Zulip only. If ERPNext is hosted outside your network, confirm it can reach your Zulip server.

## Testing
- Standalone unit tests (no bench needed) for the formatting helpers and the HTTP client's error handling.
- Bench integration tests with the client mocked: outbox delivery, retries and backoff, dry run, opt-out, the Notification channel, the Notification Log copy and user sync.
- Staging: try `dry_run`, or point the default channel at a test channel.
- End-to-end: create a Task, assign it, @mention someone in a comment, and set a due date of tomorrow. Then run `bench execute frappe.email.doctype.notification.notification.trigger_daily_alerts` and check every message in Zulip.

## Rollout
1. **Prerequisites:** create the Zulip bot and channels; check email visibility; confirm the ERPNext version and hosting.
2. **Base:** app skeleton, Zulip Settings, the sending client, the test button, the user sync.
3. **DMs:** the Notification Log copy (§6). This is the most useful piece for tasks, so ship it first.
4. **Channels:** the Zulip channel on Notification (§5), plus the Task rules.
5. **Business events:** add the other rules channel by channel, and cut noise based on feedback.
6. **Later, optional:**
   - a morning DM digest of open and overdue ToDos (a scheduler cron job), which may be quieter than one message per event;
   - two-way actions, such as a Zulip outgoing-webhook bot that marks a task done or creates one.

## Fallback if a custom app can't be installed
- **Channel posts:** use the Webhook doctype.
  - URL: `https://your-org.zulipchat.com/api/v1/external/slack_incoming?api_key=…&stream=erp-sales`
  - JSON body: `{"channel": {{ doc.name | tojson }}, "text": {{ ("**New order** " ~ doc.customer) | tojson }}}`. The payload `channel` becomes the topic. `tojson` is needed so quotes in field values don't break the JSON.
  - The API key ends up in the Webhook Request Log, so use a separate bot.
- **DMs:** a Server Script (DocType Event: Notification Log, After Insert) that calls `frappe.make_post_request(url, auth=(bot_email, api_key), data={...})`. It runs inside the save, so wrap it in `try/except` and keep the timeout short.

## Open questions
1. ~~How is ERPNext hosted, and which version?~~ Self-hosted bench, v16, so C is being built.
2. What is Zulip's email visibility setting? (§4)
3. ~~Which channels should exist?~~ ERPNext › Notifications for general notifications. Which events in §7 do people actually want?
4. What is the ERPNext hostname, for document links and linkifiers?
