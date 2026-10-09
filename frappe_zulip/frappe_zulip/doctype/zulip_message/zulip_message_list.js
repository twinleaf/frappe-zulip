const ZULIP_MESSAGE_COLORS = { Sent: "green", Queued: "orange", Failed: "red", Skipped: "gray" };

frappe.listview_settings["Zulip Message"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		return [__(doc.status), ZULIP_MESSAGE_COLORS[doc.status], `status,=,${doc.status}`];
	},
};
