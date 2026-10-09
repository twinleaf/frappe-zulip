frappe.ui.form.on("Zulip Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Send Test Message"), () => send_test_message(frm));
		frm.add_custom_button(__("Sync Users"), () => sync_users(frm));
		frm.add_custom_button(__("Message Log"), () => frappe.set_route("List", "Zulip Message"));
	},
});

function ensure_saved(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save Zulip Settings first."));
		return false;
	}
	return true;
}

function send_test_message(frm) {
	if (!ensure_saved(frm)) return;
	frappe.prompt(
		[
			{
				fieldname: "channel",
				fieldtype: "Data",
				label: __("Zulip Channel"),
				default: frm.doc.default_channel,
				reqd: 1,
			},
			{
				fieldname: "topic",
				fieldtype: "Data",
				label: __("Topic"),
				default: "ERPNext test",
				reqd: 1,
			},
		],
		({ channel, topic }) =>
			frm
				.call("send_test_message", { channel, topic })
				.then(() =>
					frappe.show_alert({ message: __("Test message sent"), indicator: "green" })
				),
		__("Send Test Message"),
		__("Send")
	);
}

function sync_users(frm) {
	if (!ensure_saved(frm)) return;
	const dialog = new frappe.ui.Dialog({
		title: __("Sync Zulip Users"),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted">${__(
					"Matches ERPNext users to Zulip accounts by email. Incoming webhook bots can't list users, so enter a Zulip admin's email and API key. They are used for this sync only and not saved."
				)}</p>`,
			},
			{ fieldname: "admin_email", fieldtype: "Data", options: "Email", label: __("Admin Email") },
			{ fieldname: "admin_api_key", fieldtype: "Password", label: __("Admin API Key") },
		],
		primary_action_label: __("Sync"),
		primary_action(values) {
			dialog.hide();
			frm.call("sync_users", values).then(({ message }) => show_sync_result(message));
		},
	});
	dialog.show();
}

function show_sync_result({ zulip_users, matched, unmatched }) {
	let html = `<p>${__("Matched {0} ERPNext users to {1} Zulip accounts.", [
		matched,
		zulip_users,
	])}</p>`;
	if (unmatched.length) {
		const list = unmatched.map((user) => `<li>${frappe.utils.escape_html(user)}</li>`).join("");
		html += `<p>${__(
			"No Zulip account found for these users. Set Zulip User ID on their User record by hand:"
		)}</p><ul>${list}</ul>`;
	}
	frappe.msgprint({ title: __("Zulip Users Synced"), message: html });
}
