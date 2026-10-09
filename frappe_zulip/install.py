import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.email.doctype.notification.notification import clear_notification_cache

CHANNEL = "Zulip"
DEFAULT_DM_TYPES = ("Assignment", "Mention", "Share")
# (fieldname, property) pairs on Notification that setup() overrides.
PROPERTY_SETTERS = (
	("channel", "options"),
	("recipients", "mandatory_depends_on"),
	("send_to_all_assignees", "depends_on"),
)

CUSTOM_FIELDS = {
	"Notification": [
		{
			"fieldname": "zulip_section",
			"fieldtype": "Section Break",
			"label": "Zulip",
			"depends_on": "eval:doc.channel=='Zulip'",
			"insert_after": "slack_webhook_url",
		},
		{
			"fieldname": "zulip_post_to_channel",
			"fieldtype": "Check",
			"label": "Post to Zulip Channel",
			"default": "1",
			"insert_after": "zulip_section",
		},
		{
			"fieldname": "zulip_stream",
			"fieldtype": "Data",
			"label": "Zulip Channel",
			"description": "Leave empty to use the default channel from Zulip Settings.",
			"depends_on": "zulip_post_to_channel",
			"insert_after": "zulip_post_to_channel",
		},
		{
			"fieldname": "zulip_topic",
			"fieldtype": "Data",
			"label": "Zulip Topic",
			"description": "Jinja template. Leave empty to use the default topic from Zulip Settings. "
			"For a topic per document, use {{ zulip.topic(doc.doctype, doc.name) }}.",
			"depends_on": "zulip_post_to_channel",
			"ignore_xss_filter": 1,
			"insert_after": "zulip_stream",
		},
		{
			"fieldname": "zulip_column",
			"fieldtype": "Column Break",
			"insert_after": "zulip_topic",
		},
		{
			"fieldname": "zulip_dm_recipients",
			"fieldtype": "Check",
			"label": "Direct Message Each Recipient",
			"insert_after": "zulip_column",
		},
		{
			"fieldname": "zulip_mention_recipients",
			"fieldtype": "Check",
			"label": "Mention Recipients in Channel Post",
			"depends_on": "zulip_post_to_channel",
			"insert_after": "zulip_dm_recipients",
		},
		{
			"fieldname": "zulip_repeat_days",
			"fieldtype": "Int",
			"label": "Repeat Every (Days)",
			"description": "Send again every this many days while the condition still holds. 0 sends once.",
			"depends_on": "eval:doc.event=='Days After'",
			"non_negative": 1,
			"insert_after": "zulip_mention_recipients",
		},
	],
	"User": [
		{
			"fieldname": "zulip_user_id",
			"fieldtype": "Int",
			"label": "Zulip User ID",
			"description": "Set by Sync Users in Zulip Settings.",
			"insert_after": "username",
		},
	],
	"Notification Settings": [
		{
			"fieldname": "enable_zulip_notifications",
			"fieldtype": "Check",
			"label": "Send Direct Messages to Zulip",
			"default": "1",
			"insert_after": "enable_email_share",
		},
	],
}


def setup():
	create_custom_fields(CUSTOM_FIELDS, update=True)

	# Rebuilt from core's options each migrate, so channels added upstream aren't lost.
	options = frappe.db.get_value("DocField", {"parent": "Notification", "fieldname": "channel"}, "options")
	make_property_setter("Notification", "channel", "options", f"{options}\n{CHANNEL}", "Text")
	make_property_setter(
		"Notification",
		"recipients",
		"mandatory_depends_on",
		"eval:!in_list(['Slack', 'Zulip'], doc.channel) && !doc.send_to_all_assignees",
		"Code",
	)
	make_property_setter(
		"Notification",
		"send_to_all_assignees",
		"depends_on",
		"eval:in_list(['Email', 'Zulip'], doc.channel)",
		"Code",
	)
	frappe.clear_cache(doctype="Notification")


def after_install():
	setup()

	settings = frappe.get_single("Zulip Settings")
	if not settings.dm_notification_types:
		for notification_type in DEFAULT_DM_TYPES:
			if frappe.db.exists("Notification Type", notification_type):
				settings.append("dm_notification_types", {"notification_type": notification_type})
		settings.save()

	insert_notifications()


def insert_notifications():
	"""Insert the built-in rules that don't exist yet. Existing rules are left as they are.

	Rules for a doctype that isn't installed (Task and Asset Maintenance Log come from ERPNext) are skipped.
	"""
	for notification in NOTIFICATIONS:
		if frappe.db.exists("DocType", notification["document_type"]) and not frappe.db.exists(
			"Notification", notification["name"]
		):
			frappe.get_doc({"doctype": "Notification", **notification}).insert()


def before_uninstall():
	for name in frappe.get_all("Notification", filters={"channel": CHANNEL}, pluck="name"):
		frappe.db.set_value("Notification", name, "enabled", 0)

	for doctype, fields in CUSTOM_FIELDS.items():
		for field in fields:
			frappe.delete_doc_if_exists("Custom Field", f"{doctype}-{field['fieldname']}")
	for fieldname, property in PROPERTY_SETTERS:
		frappe.db.delete(
			"Property Setter", {"doc_type": "Notification", "field_name": fieldname, "property": property}
		)
	frappe.clear_cache(doctype="Notification")
	clear_notification_cache()


OPEN_TASK = 'doc.status not in ("Completed", "Cancelled", "Template")'

# Days between repeated overdue reminders.
OVERDUE_REPEAT_DAYS = 7
OPEN_MAINTENANCE = 'doc.maintenance_status in ("Planned", "Overdue")'
MAINTENANCE_RECIPIENTS = [{"receiver_by_document_field": "task_assignee_email"}]

NOTIFICATIONS = [
	{
		"name": "Zulip: Task Created",
		"enabled": 1,
		"channel": CHANNEL,
		"document_type": "Task",
		"event": "New",
		"condition": 'doc.status != "Template"',
		"zulip_post_to_channel": 1,
		"message": ":new: {{ zulip.mention(doc.owner, silent=True) }} created **{{ doc.subject }}**",
	},
	{
		"name": "Zulip: Task Due Tomorrow",
		"enabled": 1,
		"channel": CHANNEL,
		"document_type": "Task",
		"event": "Days Before",
		"date_changed": "exp_end_date",
		"days_in_advance": 1,
		"condition": OPEN_TASK,
		"send_to_all_assignees": 1,
		"zulip_post_to_channel": 0,
		"zulip_dm_recipients": 1,
		"message": ":calendar: **Due tomorrow:** {{ doc.subject }}",
	},
	{
		"name": "Zulip: Task Overdue",
		"enabled": 1,
		"channel": CHANNEL,
		"document_type": "Task",
		"event": "Days After",
		"date_changed": "exp_end_date",
		"days_in_advance": 1,
		"condition": OPEN_TASK,
		"send_to_all_assignees": 1,
		"zulip_post_to_channel": 1,
		# The mention notifies the assignees, so no DM as well.
		"zulip_mention_recipients": 1,
		"zulip_repeat_days": OVERDUE_REPEAT_DAYS,
		"message": ":warning: **Overdue:** {{ doc.subject }} was due {{ doc.exp_end_date }}",
	},
	{
		"name": "Zulip: Task Completed",
		"enabled": 1,
		"channel": CHANNEL,
		"document_type": "Task",
		"event": "Value Change",
		"value_changed": "status",
		"condition": 'doc.status == "Completed"',
		"zulip_post_to_channel": 1,
		"message": ":check: {{ zulip.mention(doc.completed_by or doc.modified_by, silent=True) }} "
		"completed **{{ doc.subject }}**",
	},
	{
		# Task has its own rule on exp_end_date. Asset Maintenance keeps one ToDo per assignee
		# and doesn't move its date on, so the Asset Maintenance Log rules cover it instead.
		"name": "Zulip: ToDo Due Tomorrow",
		"enabled": 1,
		"channel": CHANNEL,
		"document_type": "ToDo",
		"event": "Days Before",
		"date_changed": "date",
		"days_in_advance": 1,
		"condition": 'doc.status == "Open" and doc.reference_type not in ("Task", "Asset Maintenance")',
		"recipients": [{"receiver_by_document_field": "allocated_to"}],
		"zulip_post_to_channel": 0,
		"zulip_dm_recipients": 1,
		"message": ":calendar: **Due tomorrow:** {{ zulip.markdown(doc.description) | truncate(200) }}"
		"{% if doc.reference_type and doc.reference_name %}\n\n"
		"[{{ _(doc.reference_type) }} {{ doc.reference_name }}]"
		"({{ frappe.utils.get_url_to_form(doc.reference_type, doc.reference_name) }}){% endif %}",
	},
	{
		"name": "Zulip: Asset Maintenance Due Tomorrow",
		"enabled": 1,
		"channel": CHANNEL,
		"document_type": "Asset Maintenance Log",
		"event": "Days Before",
		"date_changed": "due_date",
		"days_in_advance": 1,
		"condition": OPEN_MAINTENANCE,
		"recipients": MAINTENANCE_RECIPIENTS,
		"zulip_post_to_channel": 0,
		"zulip_dm_recipients": 1,
		"message": ":wrench: **Maintenance due tomorrow:** {{ doc.task_name }} on {{ doc.asset_name }}",
	},
	{
		"name": "Zulip: Asset Maintenance Overdue",
		"enabled": 1,
		"channel": CHANNEL,
		"document_type": "Asset Maintenance Log",
		"event": "Days After",
		"date_changed": "due_date",
		"days_in_advance": 1,
		"condition": OPEN_MAINTENANCE,
		"recipients": MAINTENANCE_RECIPIENTS,
		"zulip_post_to_channel": 0,
		"zulip_dm_recipients": 1,
		"zulip_repeat_days": OVERDUE_REPEAT_DAYS,
		"message": ":warning: **Maintenance overdue:** {{ doc.task_name }} on {{ doc.asset_name }} "
		"was due {{ doc.due_date }}",
	},
]
