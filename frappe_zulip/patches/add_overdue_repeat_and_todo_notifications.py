import frappe

from frappe_zulip.install import OVERDUE_REPEAT_DAYS, insert_notifications, setup


def execute():
	# after_migrate adds zulip_repeat_days, but only after patches run.
	setup()
	insert_notifications()

	# The field is new, so 0 here means unset rather than a choice to send once.
	for name in ("Zulip: Task Overdue", "Zulip: Asset Maintenance Overdue"):
		if frappe.db.get_value("Notification", name, "zulip_repeat_days") == 0:
			frappe.db.set_value("Notification", name, "zulip_repeat_days", OVERDUE_REPEAT_DAYS)
