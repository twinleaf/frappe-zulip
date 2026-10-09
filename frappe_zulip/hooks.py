app_name = "frappe_zulip"
app_title = "Frappe Zulip"
app_publisher = "Tom Kornack"
app_description = "Send ERPNext notifications to Zulip"
app_email = "kornack@twinleaf.com"
app_license = "Proprietary"

required_apps = ["frappe"]

after_install = "frappe_zulip.install.after_install"
after_migrate = "frappe_zulip.install.setup"
before_uninstall = "frappe_zulip.install.before_uninstall"

doctype_js = {"Notification": "public/js/notification.js"}

extend_doctype_class = {"Notification": "frappe_zulip.notification.ZulipNotificationMixin"}

doc_events = {
	"Notification Log": {
		"after_insert": "frappe_zulip.notification_log.forward_to_zulip",
	},
}

scheduler_events = {
	"all": ["frappe_zulip.outbox.retry_pending"],
}

default_log_clearing_doctypes = {"Zulip Message": 30}

ignore_links_on_delete = ["Zulip Message"]
