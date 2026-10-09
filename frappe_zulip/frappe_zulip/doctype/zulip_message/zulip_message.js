frappe.ui.form.on("Zulip Message", {
	refresh(frm) {
		if (["Failed", "Skipped"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Retry"), () =>
				frm.call("retry").then(() => {
					frappe.show_alert({ message: __("Message queued"), indicator: "orange" });
					frm.reload_doc();
				})
			);
		}
	},
});
