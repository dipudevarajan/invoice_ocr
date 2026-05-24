import frappe
from frappe.model.document import Document
import pytesseract
from PIL import Image
import json
import requests

class InvoiceUpload(Document):
    def validate(self):
        if self.file and self.ocr_status == "Pending":
            self.ocr_status = "Processing"
            self.save()
            frappe.enqueue(self.process_invoice, queue='long', timeout=300)

    def process_invoice(self):
        try:
            # 1. Fetch physical file path from attached file URL
            file_doc = frappe.get_doc("File", {"file_url": self.file})
            file_path = file_doc.get_full_path()

            # 2. Extract raw text from the image using Tesseract
            raw_text = pytesseract.image_to_string(Image.open(file_path))
            
            if not raw_text.strip():
                raise Exception("OCR failed to extract any readable text from the image.")

            # 3. Parse raw text into structured JSON data using your LLM/Extraction API
            parsed_data = self.extract_fields_via_llm(raw_text)
            self.extracted_data = json.dumps(parsed_data, indent=4)

            # 4. Create the Draft Purchase Invoice
            pi = frappe.new_doc("Purchase Invoice")
            
            # Resolve or create supplier
            supplier = self.get_or_create_supplier(parsed_data.get("supplier_name"))
            pi.supplier = supplier
            pi.bill_no = parsed_data.get("invoice_number")
            pi.posting_date = parsed_data.get("date")

            # Map extracted items into the Purchase Invoice Items child table
            for item in parsed_data.get("items", []):
                item_code = self.get_or_create_item(item.get("description"), item.get("rate"))
                pi.append("items", {
                    "item_code": item_code,
                    "qty": item.get("qty", 1),
                    "rate": item.get("rate", 0),
                    "expense_account": frappe.get_cached_value("Company", pi.company, "default_expense_account")
                })

            pi.insert(ignore_permissions=True)
            
            # Update current upload record state
            self.ocr_status = "Extracted"
            self.purchase_invoice = pi.name
            frappe.msgprint(f"Successfully generated draft Purchase Invoice: {pi.name}")

        except Exception as e:
            self.ocr_status = "Failed"
            frappe.log_error(message=frappe.get_traceback(), title="Invoice OCR Processing Failure")
        
        self.save()

    def extract_fields_via_llm(self, raw_text):
        """
        Sends extracted text block to an inference endpoint to organize into clean fields.
        """
        # Retrieve credentials securely from your custom system settings
        api_key = frappe.conf.get("openai_api_key") 
        if not api_key:
            raise Exception("Missing 'openai_api_key' entry in common_site_config.json")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        prompt = (
            "Extract the invoice details from this raw OCR text block. Return ONLY a valid JSON object "
            "with keys: 'supplier_name', 'invoice_number', 'date' (YYYY-MM-DD format), and an array 'items' "
            "where each item contains 'description', 'qty', and 'rate'. Text block:\n\n" + raw_text
        )

        payload = {
            "model": "gpt-4o-mini",
            "response_format": { "type": "json_object" },
            "messages": [{"role": "user", "content": prompt}]
        }

        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        res_json = response.json()
        
        return json.loads(res_json['choices'][0]['message']['content'])

    def get_or_create_supplier(self, name):
        if not name:
            return frappe.get_cached_value("Buying Settings", None, "default_supplier") or "Unknown Supplier"
        if frappe.db.exists("Supplier", name):
            return name
        else:
            sup = frappe.new_doc("Supplier")
            sup.supplier_name = name
            sup.supplier_group = "All Supplier Groups"
            sup.insert(ignore_permissions=True)
            return sup.name

    def get_or_create_item(self, description, rate):
        if not description:
            return "Miscellaneous Service"
        
        # Match description closely if it already exists
        existing_item = frappe.db.get_value("Item", {"item_name": description}, "name")
        if existing_item:
            return existing_item
            
        # Fallback layout: generate service item on-the-fly
        item = frappe.new_doc("Item")
        item.item_code = description[:60] # cap the length string boundary
        item.item_name = description
        item.item_group = "All Item Groups"
        item.stock_uom = "Nos"
        item.is_stock_item = 0 # Mark non-stock to prevent inventory reconciliation locks
        item.valuation_rate = rate
        item.insert(ignore_permissions=True)
        return item.name
