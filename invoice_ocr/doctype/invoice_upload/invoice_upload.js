frappe.ui.form.on('Invoice Upload', {
    refresh: function(frm) {
        // Add direct navigation jump point if invoice generation completed successfully
        if (frm.doc.purchase_invoice) {
            frm.add_custom_button(__('View Purchase Invoice'), function() {
                frappe.set_route('Form', 'Purchase Invoice', frm.doc.purchase_invoice);
            }, __('Actions'));
        }
        
        // Show indicator flags alongside standard text blocks
        if (frm.doc.ocr_status === "Processing") {
            frm.set_intro(__('This invoice is currently being parsed via background workers. Please refresh shortly.'), 'orange');
        } else if (frm.doc.ocr_status === "Extracted") {
            frm.set_intro(__('Data successfully extracted and mapped to target Purchase Invoice ledger structure.'), 'green');
        }
    }
});
