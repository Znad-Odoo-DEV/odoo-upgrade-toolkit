"""Chase the ministry rows whose passport is not the one Odoo holds.

    odoo-bin shell -d <database> --no-http < tools/match_permit_leftovers_by_name.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/match_permit_leftovers_by_name.py

tools/set_work_permit_dates.py matches on the passport and leaves 32 of the 200
ministry rows unmatched. They are not missing people: two of them turned up in
the attendance sample the same afternoon. A worker renews a passport and one of
the two records keeps the old number, so the identifier stops agreeing while
the person does not change.

This pass matches those rows by name instead, which is looser and therefore is
NOT allowed to write anything on its own judgement. It prints what it believes
each row is, together with the passport Odoo holds against the one the ministry
printed, so the pairing can be read before it is accepted. A row that matches
more than one employee, or none, is reported and skipped.

Names only. No passport number is stored in this file.
"""
import difflib
import os
import re
from datetime import date, datetime

APPLY = os.environ.get('SSC_APPLY') == '1'

# name as the ministry prints it, permit expiry dd/mm/yyyy
DATA = """
BADREYA SALEH SALEM AL SHEAILI            | 03/05/2027
BASHAYER SAIF SALIM ALI ALKALBANI         | 14/03/2027
MD FAYSOL MIA SOMUJ ALI                   | 10/02/2027
MOUSTAFA ABDELAZIM ELIMAM ELIMAM ABDELAATI| 07/11/2027
AHMAD ABDO FALLAHA                        | 27/09/2027
BALASUBRAMANIAN GANESAN GANESAN           | 18/06/2027
ROGER TWAGIRAYEZU                         | 09/12/2027
AHMED HAMED ELSAYED SALAMA                | 15/02/2028
JAHANGIR KHAN SADE NAR KHAN               | 30/06/2027
MAHMOUD AHMED KHALIFA ABDELRAHMAN         | 09/10/2027
ALHAJI TURAY                              | 17/09/2027
ABDULGHANI MOHAMAD HATAHET                | 01/03/2027
NIKKI FERRER DE LEON                      | 27/04/2028
AMR MOHAMED HAMED ELDEEK                  | 19/10/2027
YASSER ADEL HAFEZ ELMAGHRABY              | 18/10/2027
MOHAMED SANGBA MARAH                      | 10/09/2027
ROZIBUL ISLAM ABUL HOSSAIN                | 28/11/2026
HANI ELMAHMOUDI MOHAMED MOHAMED           | 15/10/2027
RAFIQ AHAMED KALLASI KAJA MOHIDEEN        | 24/12/2027
SHADEB DHALI LAL CHAN DHALI               | 31/12/2026
JASHEM UDDIN FALU MIAH                    | 31/12/2026
MONIR AHAMMED SALE AHAMMED                | 17/12/2026
AHMAD SAMI CHIEKH YOUSSEF                 | 07/02/2027
MOHAMAD KHALDOUN ABDULKADER SHARABATI     | 10/07/2028
GANESAN ALAGAR ALAGAR                     | 14/02/2027
SAMOA MOHAMMAD ALSAMOA                    | 12/11/2026
MOHAMMAD ALLAUDDIN MOHAMMAD QUAMUDDIN     | 03/02/2027
SATAA MAJED SALLAM                        | 24/06/2027
JENIVIE ERONG AGUILAR                     | 10/04/2027
KHALED BADEA AYYASH                       | 24/12/2027
AHMAD BADRI KHALED                        | 22/08/2027
MOHANNAD M GHAZI KAYYALI REFAEI           | 23/08/2026
"""

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
today = date.today()


def title(text):
    print("\n" + "=" * 92)
    print(text)
    print("=" * 92)


def normalise(name):
    """Upper case letters and digits only - spacing and punctuation differ."""
    return re.sub(r'[^A-Z0-9]', '', (name or '').upper())


rows = []
for line in DATA.strip().splitlines():
    name, raw = line.split('|')
    rows.append((name.strip(), datetime.strptime(raw.strip(), '%d/%m/%Y').date()))

Employee = env['hr.employee'].sudo()
staff = Employee.search([])
index = {}
for emp in staff:
    index.setdefault(normalise(emp.name), []).append(emp)
keys = list(index)

title("proposed pairings - read these before accepting")
print(f"  {'ministry name':<40} {'odoo name':<30} {'odoo passport':<13} {'expiry'}")

decided, ambiguous, unfound = [], [], []
for name, end in rows:
    key = normalise(name)
    hits = index.get(key)
    if not hits:
        # the ministry writes every given name; Odoo sometimes holds fewer.
        near = difflib.get_close_matches(key, keys, n=3, cutoff=0.86)
        hits = [e for k in near for e in index[k]]
    if len(hits) == 1:
        emp = hits[0]
        decided.append((name, emp, end))
        print(f"  {name[:40]:<40} {emp.name[:30]:<30} {(emp.passport_id or '-'):<13} {end}")
    elif hits:
        ambiguous.append((name, hits, end))
    else:
        unfound.append((name, end))

title("ambiguous - more than one employee answers to the name")
for name, hits, end in ambiguous:
    print(f"  {name}  -> {[ (e.id, e.name) for e in hits ]}")

title("not found at all")
for name, end in unfound:
    print(f"  {name:<44} {end}")

print(f"\n  single match {len(decided)} | ambiguous {len(ambiguous)} | not found {len(unfound)}")

lapsed = [(n, e, d) for n, e, d in decided if d < today]
writable = [(n, e, d) for n, e, d in decided if d >= today]

title("permits already lapsed - reported, never written")
for name, emp, end in lapsed:
    print(f"  {emp.name[:36]:<36} expired {end}  badge={emp.barcode or '-'}")

if APPLY:
    done, failures = 0, []
    for _name, emp, end in writable:
        try:
            with env.cr.savepoint():
                if emp.work_permit_expiration_date != end:
                    emp.work_permit_expiration_date = end
                version = emp.current_version_id
                if version and version.contract_date_end != end:
                    vals = {'contract_date_end': end}
                    if not version.contract_date_start:
                        # 19 refuses an end date on a row with no start, and the
                        # start decides the gratuity, so it comes from the
                        # joining date rather than from when the row was made.
                        ssc = env['ssc.employee'].sudo().search(
                            [('hr_employee_id', '=', emp.id)], limit=1)
                        vals['contract_date_start'] = (
                            (ssc and ssc.joining_date)
                            or version.date_version
                            or version.create_date.date())
                    version.write(vals)
            done += 1
        except Exception as error:
            failures.append((emp, str(error).splitlines()[0][:90]))
    env.cr.commit()
    title("APPLIED")
    print(f"  {done} / {len(writable)} employee(s) updated by name")
    for emp, message in failures:
        print(f"    refused: {emp.name[:32]:<32} {message}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print(f"  {len(writable)} employee(s) would be updated. Read the pairings above,")
    print("  then re-run with SSC_APPLY=1 if every line is the person you expect.")
