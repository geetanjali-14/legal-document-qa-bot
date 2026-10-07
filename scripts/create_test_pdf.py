import fitz  # PyMuPDF
from pathlib import Path


def create_synthetic_contract(output_path: Path) -> Path:
    """
    Creates a standard synthetic multi-page commercial legal contract for automated testing.
    Contains explicit clauses, section headings, numbers, and dates.
    """
    doc = fitz.open()

    # --- PAGE 1: PREAMBLE, PARTIES, TERM, AND TERMINATION ---
    page1 = doc.new_page()
    text_p1 = """MASTER SERVICES AGREEMENT

This Master Services Agreement ("Agreement") is made effective as of October 1, 2026 ("Effective Date"), by and between Nexus Enterprises LLC ("Client") and Apex Technology Solutions Inc. ("Vendor").

1. Term of Agreement
1.1 Initial Term. This Agreement shall commence on the Effective Date and shall remain in effect for an initial term of twenty-four (24) months.
1.2 Renewal. The Agreement automatically renews for successive 12-month periods unless either party provides written notice of non-renewal at least 60 days prior to the expiration of the current term.

2. Termination
2.1 Termination for Convenience. Either party may terminate this Agreement without cause by providing at least 30 days written notice to the other party.
2.2 Termination for Cause. Either party may terminate immediately if the other party breaches any material term and fails to cure such breach within 15 days of receiving written notice.
2.3 Effect of Termination. Upon termination, Client shall pay Vendor for all Services rendered up to the effective termination date within 10 business days.
"""
    rect = fitz.Rect(50, 50, 545, 750)
    page1.insert_textbox(rect, text_p1, fontsize=10, fontname="helv")

    # --- PAGE 2: PAYMENT, CONFIDENTIALITY, AND LIABILITY ---
    page2 = doc.new_page()
    text_p2 = """3. Fees and Payment Terms
3.1 Invoicing and Invoices. Vendor shall invoice Client on the first calendar day of each month for services rendered.
3.2 Payment Window. Client shall remit payment within 30 days of receipt of each undisputed invoice.
3.3 Late Payment Fee. Any overdue amount shall accrue interest at a rate of 1.5% per month or the maximum rate permitted by law.

4. Confidentiality
4.1 Definition. "Confidential Information" includes all proprietary technical, financial, and business data disclosed by either party.
4.2 Non-Disclosure Obligation. Each party agrees to hold Confidential Information in strict confidence for a period of five (5) years following the termination of this Agreement.
4.3 Exclusions. Obligations shall not apply to information that is publicly known through no breach of this Agreement.

5. Limitation of Liability
5.1 Liability Cap. In no event shall either party's aggregate cumulative liability arising under this Agreement exceed $100,000 USD or the total fees paid in the preceding six months, whichever is greater.
5.2 Consequential Damages. Neither party shall be liable for indirect, incidental, or consequential damages.
"""
    page2.insert_textbox(rect, text_p2, fontsize=10, fontname="helv")

    # --- PAGE 3: INTELLECTUAL PROPERTY, DISPUTE RESOLUTION, GOVERNING LAW ---
    page3 = doc.new_page()
    text_p3 = """6. Intellectual Property
6.1 Client Ownership. All custom deliverables developed specifically for Client shall be deemed "work made for hire" and shall belong solely to Client.
6.2 Vendor Tools. Vendor retains exclusive ownership of its pre-existing tools, libraries, and proprietary software.

7. Dispute Resolution and Governing Law
7.1 Governing Law. This Agreement shall be governed by and construed in accordance with the laws of the State of Delaware, without regard to conflicts of law principles.
7.2 Mandatory Arbitration. Any controversy or dispute arising out of this Agreement shall be resolved by binding arbitration in Wilmington, Delaware administered by the American Arbitration Association (AAA).

IN WITNESS WHEREOF, the authorized representatives have executed this Agreement.
For Nexus Enterprises LLC: Jane Doe, Chief Executive Officer
For Apex Technology Solutions Inc.: John Smith, Managing Director
"""
    page3.insert_textbox(rect, text_p3, fontsize=10, fontname="helv")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    doc.close()
    return output_path


if __name__ == "__main__":
    out = Path("documents/synthetic_contract.pdf")
    create_synthetic_contract(out)
    print(f"Created synthetic contract at {out}")
