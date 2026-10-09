from frappe_zulip.install import insert_notifications


def execute():
	# Sites installed before Zulip: Task Created existed only have the original rules.
	insert_notifications()
