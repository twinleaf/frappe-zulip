frappe.ui.form.on("Notification", {
	refresh: setup_zulip,
	document_type: setup_zulip,
	channel: setup_zulip,
});

function setup_zulip(frm) {
	if (frm.doc.channel !== "Zulip") return;
	set_zulip_example(frm);
	if (!frm.doc.document_type) return;
	// Core fills the receiver dropdown in its own with_doctype callback; run after it.
	frappe.model.with_doctype(frm.doc.document_type, () =>
		frappe.after_ajax(() => set_zulip_receiver_fields(frm))
	);
}

function set_zulip_receiver_fields(frm) {
	if (frm.doc.channel !== "Zulip") return;
	const is_receiver = (df) =>
		(df.fieldtype === "Link" && df.options === "User") ||
		(["Data", "Small Text"].includes(df.fieldtype) && df.options === "Email");
	const option = (df, parent) => ({
		value: parent ? `${df.fieldname},${parent}` : df.fieldname,
		label: `${parent ? `${parent} > ` : ""}${df.fieldname} (${__(df.label, null, df.parent)})`,
	});

	const options = [];
	for (const df of frappe.get_doc("DocType", frm.doc.document_type).fields) {
		if (frappe.model.table_fields.includes(df.fieldtype)) {
			for (const cdf of frappe.get_doc("DocType", df.options).fields) {
				if (is_receiver(cdf)) options.push(option(cdf, df.fieldname));
			}
		} else if (is_receiver(df)) {
			options.push(option(df));
		}
	}
	frm.fields_dict.recipients.grid.update_docfield_property(
		"receiver_by_document_field",
		"options",
		["", "owner", ...options]
	);
}

function set_zulip_example(frm) {
	frm.get_field("message_examples").html(`<h5>${__("Message Example")}</h5>
<pre>**{{ doc.subject }}** is overdue.

Assigned by {{ zulip.mention(doc.owner) }}
{% if comments %}
Last comment: {{ comments[-1].comment }} by {{ comments[-1].by }}
{% endif %}</pre>
<p class="text-muted">${__(
		"Write the message in Zulip Markdown. A link to the document is added automatically. Use {0} to @-mention a user, or {1} for a silent mention.",
		["<code>zulip.mention(user)</code>", "<code>zulip.mention(user, silent=True)</code>"]
	)}</p>`);
}
