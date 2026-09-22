"""Set the work permit expiry and the contract end date from the MOHRE list.

    odoo-bin shell -d <database> --no-http < tools/set_work_permit_dates.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_work_permit_dates.py

Source: the ministry's "The List Of Employees" for establishment 823412,
SAUD SHEHATHA CONSTRUCTION L L C, printed 23/08/2026, 206 employees. 200 rows
were readable; six had their columns merged in the PDF and are left for a human.

WHY THIS IS NEEDED

102 employees had been working since 13 July on a contract Odoo considers
finished. With no contract running on the day, 19.0 writes no payslip at all
and counts every worked hour as overtime: 21,700 phantom hours in a month
against the 6,966 the payroll actually pays for. The genuine end date is the
work permit expiry, which for a Limited UAE contract is the contract period.

NO PASSPORT NUMBER IS STORED HERE

Employees are matched on a SHA-256 prefix of the passport, and the script
hashes hr.employee.passport_id the same way to find them. The repository never
holds a readable identifier, and the masked third column exists only so a
mismatch can be chased without exposing anything. passport_id is filled on all
326 active employees of that company, so the match is exact; nothing is matched
by name - the ministry writes ABDULLAH SHARIF ALASHKAR where Odoo holds
Abdullah Sharif Al ashkar, and guessing across that gap on payroll data is not
worth the risk.

WHAT IT WRITES

    hr.employee.work_permit_expiration_date  what the field is for.
    hr.version.contract_date_end             the same date, because payroll is
                                             what actually breaks without it.

A permit that has already lapsed is reported and its contract end is NOT
written. That is a renewal for HR to obtain, not a date for a script to invent,
and back-dating the contract would only keep the employee outside payroll.
"""
import hashlib
import os
import re
from datetime import date, datetime

APPLY = os.environ.get('SSC_APPLY') == '1'


def fingerprint(passport):
    """The same twenty hex characters the list was built with."""
    return hashlib.sha256((passport or '').strip().upper().encode()).hexdigest()[:20]


# passport fingerprint, permit expiry dd/mm/yyyy, masked passport for debugging
DATA = """
d11fe92b0df639592c9e  25/10/2026  AH*****62
9cb7935feaa09347df46  18/06/2027  R3*****47
cfdc9cea2afa104a18a9  03/11/2026  AA*****84
f518275a1036d5b454ed  03/05/2027  AA*****61
6e9dabc1423199a96634  14/03/2027  RR*****33
ec31b29259537945258a  19/12/2027  NZ*****30
79dd801b07d10a59fcdc  24/06/2028  AA*****80
4adc63ddb145e1ab5914  15/09/2026  N0*****72
3429223d1b9c22051d40  11/12/2026  P0****72
852d51f13dea80140d5d  15/12/2026  A3*****09
d159dfbbe279a4242adc  03/10/2026  SL*****59
4ab49590175729614043  07/08/2026  P7****94
6a05f8924f95e0923cdb  14/12/2027  PC****81
98501c211a18f885d96b  03/10/2026  A2*****33
0a93d957fc2d321d6d7e  03/10/2026  N0******67
5a40eaf81b5f1646eb1a  15/09/2026  N0******99
df2b684119fa6097b884  15/10/2027  A4*****57
1376343f5b68e86763a3  07/01/2027  N0*****20
4e3b45e6b2a755a6c085  09/12/2027  PC****30
61e5a6ab2a4ec1fda769  23/09/2027  T7****94
c93860369c41339c07f5  03/10/2026  A1*****97
8b12a5e6f8fa71dcd2c5  10/02/2027  A0*****91
9f28693bbe0c88bc161a  03/10/2026  EL*****48
c5f55662788abdae2253  10/09/2027  ER****18
add37d1e23608ecc931b  06/08/2026  N0*****53
04c582f8327ec2646c9b  31/12/2026  X9****22
865662769c692982db7b  13/01/2027  V8****05
9e6ba48fd64df9831e40  11/11/2027  T9****60
4b232cbea03d223badb8  20/10/2026  B0*****75
956b578211e602a71bf8  03/10/2026  A1*****69
90bd8b47033535ee505b  27/07/2027  V3****44
dcadf9f269846c773b5a  14/09/2026  A1*****10
e9cbabc9066028373e7b  07/11/2027  A4*****02
bd0ee435c7956d7f002b  13/01/2027  C1****88
ed52058b9d4233096daf  18/12/2026  X8****30
862fad35e97ba549b465  03/10/2026  A0*****94
265aa7978317ec13a3f8  03/10/2026  PC****24
1971b4da7c1deefa9f68  16/10/2026  X4****82
dcabbcf0620acd27c28a  04/01/2027  SL*****06
a1c56b49015889c10458  24/08/2027  BH*****12
e33722c6e7a4466d5a95  27/09/2027  N0******97
0fbeb117b4dc5547d5b5  19/03/2028  SL*****65
4adf02da87c2c34bd62d  18/06/2027  P1****77
98e439f8727e82d96237  17/09/2026  N0******79
e41a0e6987ca5b1da53c  25/08/2026  N0******89
c4fd487e5e374d96d9c0  13/12/2026  N1****93
db2fbaa6387955ada58e  09/12/2027  PC****93
874f5ec1e625faeff1cb  03/10/2026  A0*****53
7b8f907e213f3c4d0b7d  15/02/2028  A3*****27
e050aede5a3fa25de85f  15/10/2026  A2*****90
2bdf3728511befca8e85  03/08/2026  W0****44
5d0691add03a519b58ce  30/06/2027  CN*****65
5ed673b4763e950a92b3  11/01/2027  A1*****52
d9a73750b86933fc1eb1  03/10/2026  PC****74
e3dfac317abf8efafab1  17/09/2026  N0*****32
fea6869b997e70a63fe5  05/06/2027  A3*****16
f4f454c9abdaef1aa77c  27/10/2026  A1*****47
d04c0f5063a0eece5b97  23/09/2027  A3*****70
f45a633c15c39994f18a  15/09/2026  N0*****83
57caf05587ee9b4a1a39  09/10/2027  A4*****25
cf414a2b0c06b5d7d1fa  03/10/2026  A1*****70
ca86f6a6d7430d5ec7bf  24/12/2027  BX*****63
470780da951ca10216b2  21/09/2027  A4*****22
da32afd7259f1d7255db  29/10/2027  AB****60
ecb3ddfeff0430f5bbee  28/10/2027  A3*****52
b3d8071da41687660d50  21/09/2027  A3*****67
67a6540f973f1da47e19  05/02/2027  EG*****58
65c7054958e8054429cd  07/10/2027  A3*****01
cae13cb58803571a9dc1  30/12/2026  EM*****84
e3378506057de9a90e02  17/09/2027  SL*****96
b6aa61056ea39c2d01ca  14/11/2027  N0*****30
f160b0a6c474a2aa5f11  01/03/2027  N0*****55
19e1f931b56d4eadcf1e  27/04/2028  P7*****5A
47af5a4a92ce83fbdfcc  17/12/2027  PC****94
35ff492e758e91afb19e  24/02/2028  A4*****50
d74ea42624601a888cd6  19/10/2027  A4*****04
032882354f2b649455ff  27/12/2026  V1****57
7c7640be9f5317fc79db  03/10/2026  A0*****49
58b8e85addaf58654c65  07/10/2027  A4*****41
39c205caa1b12b0f8c0f  18/12/2026  A1*****55
c0379a5b194ee689d3e9  21/09/2027  A2*****63
21762c7e920a72c2d718  03/10/2026  A1*****56
2c24944a4dd8779b5e19  07/09/2026  S2****43
12ccc9fb199cdecf2222  18/10/2027  A2*****71
aceb4702aab7a3aed114  21/07/2027  A4*****73
6b86588f10f1f505cb55  27/09/2027  R5****07
42ecb8385e2c78a1c9cd  10/09/2027  SL*****65
268c9e94c80eb9fc41fd  27/02/2027  W8****81
f3ac39d2370f68112f12  28/11/2026  Y3****39
b6f4e0aca68f5696f555  28/11/2026  EM*****97
9fe4719b6bb8a438ad46  17/04/2028  A3*****21
a4986420f55056531d1d  30/12/2027  PA*****67
b45f99f9c3faa4525408  15/10/2027  A3*****02
5ef978029f1b6cb2c7b4  17/04/2028  A4*****59
de51902aa08427602914  13/01/2028  V7****81
6e35e21a11c08e9eb830  13/01/2028  R2****45
90a5c695ff79e1042dd8  06/08/2027  A4*****09
ebd7631f416526a860b7  04/10/2026  V9****07
d89e752cb4dd9a4643bd  20/09/2026  AH****26
df32a0cef04123e6dc92  24/12/2027  I0****55
9f5c631976a7322d8b5d  25/12/2027  BE*****73
eac5edbfe2b14d4f56aa  15/11/2026  A0*****82
a1c71d731554ac8756aa  28/08/2028  A2*****75
2b86e38cd158fbb9d30b  31/12/2026  A1*****81
8c34b6a7f91117d7fa27  03/04/2027  N9****39
d3841950a6b66387256f  12/12/2027  BC*****62
e507a5011aabd4d56887  12/12/2027  AC*****82
a62ad0b96c38acf18009  31/12/2026  A1*****28
48849310aaf00dba7b44  17/12/2026  EM*****09
49ecad05a8288506a1b4  23/12/2027  N1****67
6ff68e12e5b8fc93052a  24/08/2026  V9****56
fce5b6ada7e32b2138b8  02/08/2026  EL*****17
9b01a056e16bf04d7736  19/01/2028  N0****44
ed8f1cd8457567afd83b  15/11/2027  N0******63
191e0af09758fa8c2def  14/11/2026  A2*****44
556237f7e20702f661d3  07/02/2027  N0*****11
5e8915f726720df2beb8  02/07/2028  PC****37
6a38c086baa5d905d49f  12/02/2028  A3*****11
5d1315c889bf0dfdfb52  15/11/2026  A0*****90
d2b24ba966ad1a3a3ca4  10/07/2028  N0******20
b21a466844a1a297530a  20/11/2026  A1*****65
8da10970549a0bfa6a07  12/02/2028  N0*****18
b88469783122e951aa72  20/03/2028  V2****56
c15fac404647a9ea27f1  22/07/2027  AF*****94
824b079ea20a895ee243  24/08/2026  N6****88
70327b2fe74d573647dd  20/10/2027  Y5****26
08f2d90863e0ba82a69f  28/04/2027  P5****98
1771a73bb6aba4f3ff71  16/10/2027  N0******85
cd308acc352e8a8d8511  14/02/2027  C3****37
1c4a4429277f066c2722  24/12/2027  U4****26
4a7453c42ba98cd2ea2b  28/04/2027  X9****06
4bb3f91340c84d781d12  05/06/2028  M6****44
9bd5713b9274a01d65bc  28/05/2028  A0*****51
a79a7fc8fdc7ff576bb7  22/01/2027  A0*****06
c512f65d387eeaf97ddc  03/12/2027  A2*****57
b21c6c85fbed3c893074  24/12/2027  DP*****23
47ad58585a39ecfa5223  08/02/2027  M7****40
68781e54543f8b5939e8  16/01/2028  A0*****55
7b29c2b3921473e91023  12/11/2026  N0*****45
9089266af7852fadcf9e  04/01/2028  M1****56
c6054aa5a7b19b586f58  05/11/2027  R6****31
35ff6e0a61a217fcfe68  06/06/2027  EL*****62
aa8c09c09e2035827ac0  27/11/2027  V0****54
2d1cfbffe3f1d947c597  05/02/2028  A0*****72
a39e2b1a8847817a325d  04/07/2028  Y7****12
656c090bf0d45b248d6b  02/11/2026  N0*****76
129af619e5b56620a816  18/01/2028  M2****46
be378440a1b4e2564079  14/08/2027  N0******52
ec264453b35ab1205725  27/03/2027  EP*****03
016adea79d8347be9fdd  20/07/2028  T4****86
75c426aece1fec739a63  23/07/2028  A3*****74
2a5fa278d26f3a3e6a10  15/11/2027  N0******68
ab4865c94c3cf1d2f591  06/06/2027  A0*****59
afa3a9b05a18f6c1442c  06/06/2027  A0*****79
2e85dbda04b276a6fe91  03/02/2027  Y3****43
923577e6d91815957f16  28/12/2027  N0*****79
42a8340c99544fc5051d  08/03/2027  X5****73
b6d53cb1eb5b6789a798  26/07/2027  RR*****53
caf1c0bcf65cdf942cc8  24/06/2027  N0*****20
9db92176ba95331496b9  11/10/2027  B0*****22
39b79a920f37471370f8  26/08/2027  M4****40
7c360fedb5ab053683bc  15/11/2027  N0******75
d7fb19cdfa38e1f371e7  28/04/2027  N7****55
0c4afef6afaa59e04dfc  08/02/2027  R8****66
4baf984197ecb59a4e1c  12/09/2027  M9****77
a86862d5c2b7e9e1262c  05/08/2026  M7****39
5cd9fc7196d651f73a44  28/12/2027  16*****09
15abf8a970f52e8cbca8  10/04/2027  P3*****7B
51033ceb6cc4c281866d  24/12/2027  N0******80
ed02b213d5119f1f493a  22/08/2027  N0*****52
9856b7c36748d96673f7  14/08/2027  N0******02
efa3a616f94d62b7691d  17/11/2026  T9****12
ac18f2f3ba288df85919  02/05/2027  R8****93
e89f279a4c1f236a61d5  23/08/2027  N0******24
030420f68b50f66cfbb3  20/11/2026  A2*****29
0b62892b650649904054  16/09/2027  N0******12
d9538e8c5bc86b152942  31/12/2026  A2*****50
749d35d21ff936902c6c  15/08/2027  N0******10
4855e143f174b2fbb4b2  09/08/2027  L9****58
d18ab0f29fec8cf276a6  16/01/2028  A0*****76
396b76138df52f2cc788  19/01/2028  P4****59
2d4be297c0f8c5e85303  02/12/2027  T4****84
665790038ccf598d9c59  15/11/2026  A0*****46
30022b6fc8f227e5238d  16/01/2028  EK*****30
11b3aa47891dc01d0208  23/08/2026  N0******94
3d86ce124c5f4eb4e6bc  01/08/2026  N7****30
7977d092dc7917fb9785  27/12/2027  TQ*****82
899a4e16f9207dc7ae15  27/01/2028  JW*****52
9696cd6736bfc9038d2f  27/11/2027  U8****55
28652ffb9ddbea9fe365  16/01/2028  A0*****87
705af89d17475a60cc09  26/10/2027  R1****45
c5db7a4196f2d04eb2cc  01/08/2026  P7****15
c3dd1d82d6be64f455fc  29/11/2027  V0****45
db22e94375320bfb4ed2  02/11/2026  S1****96
1da7ee17ee8c4cb9724f  13/09/2027  R2****12
85735084f3b2023852e7  24/07/2028  A2*****28
b0f890e13d3735ca3874  23/09/2028  A3*****47
6e0c05ca6fbaff1d8262  14/08/2027  N0******85
711b844f5639dc7484dc  14/08/2027  N0******13
50cd394d4a99d8ad7012  22/08/2027  N0******28
"""

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
today = date.today()


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


wanted = {}
masks = {}
for line in DATA.strip().splitlines():
    digest, raw, mask = line.split()
    wanted[digest] = datetime.strptime(raw, '%d/%m/%Y').date()
    masks[digest] = mask

Employee = env['hr.employee'].sudo()
Attendance = env['hr.attendance'].sudo()

candidates = {}
for emp in Employee.search([]):
    if emp.passport_id:
        candidates.setdefault(fingerprint(emp.passport_id), []).append(emp)


def rank(emp):
    """How much this record looks like the employee who actually works here.

    A passport lands on more than one record in two ways: an archived leftover
    from an older import, and a second live record created without a badge.
    Neither is the person payroll means. Still active, carries a badge, carries
    a wage, and has punches against it - in that order.
    """
    version = emp.current_version_id
    return (
        bool(emp.active),
        bool(emp.barcode),
        bool(getattr(version, 'wage', 0)),
        Attendance.search_count([('employee_id', '=', emp.id)]),
    )


# The date somebody was actually hired is not on hr.employee: date_version and
# create_date both say when the row was made in Odoo, which for most of these is
# June or July 2026. ssc.employee carries the real one, taken from the Studio
# master, and it is filled on 465 of 466 records.
Ssc = env['ssc.employee'].sudo() if 'ssc.employee' in env else None
joining_by_hr = {}
joining_by_badge = {}
joining_by_name = {}
if Ssc is not None:
    for rec in Ssc.with_context(active_test=False).search([]):
        if not rec.joining_date:
            continue
        if rec.hr_employee_id:
            joining_by_hr.setdefault(rec.hr_employee_id.id, rec.joining_date)
        badge = re.sub(r'[^A-Za-z0-9]', '', (rec.attendance_code or '').strip())[:18].upper()
        if badge:
            joining_by_badge.setdefault(badge, rec.joining_date)
        # A name is the only handle left for the 52 employees with no badge,
        # who therefore have no link and no badge to match on either. It is
        # only ever used to read a date, never to decide who somebody is, and a
        # name held by two people is dropped rather than guessed.
        key = re.sub(r'[^A-Z0-9]', '', (rec.name or '').upper())
        if key:
            joining_by_name.setdefault(key, []).append(rec.joining_date)


def joining_date_of(emp):
    """When this person actually started, or nothing if we do not know."""
    found = joining_by_hr.get(emp.id)
    if not found and emp.barcode:
        key = re.sub(r'[^A-Za-z0-9]', '', emp.barcode.strip())[:18].upper()
        found = joining_by_badge.get(key)
    if not found:
        dates = joining_by_name.get(re.sub(r'[^A-Z0-9]', '', (emp.name or '').upper()), [])
        if len(set(dates)) == 1:
            found = dates[0]
    return found


def contract_start_for(emp, version):
    """A contract cannot end without starting - 19 enforces that in the table.

    hr_version_check_contract_start_date_defined refuses an end date on a row
    with no start. The joining date is the honest answer and it decides the end
    of service gratuity, so guessing here would quietly cost somebody money.
    The version date is only a last resort, and every employee that falls back
    to it is printed.
    """
    return (joining_date_of(emp)
            or version.date_version
            or version.create_date.date())


by_digest = {}
collisions = []
for digest, records in candidates.items():
    if len(records) == 1:
        by_digest[digest] = records[0]
        continue
    ordered = sorted(records, key=rank, reverse=True)
    by_digest[digest] = ordered[0]
    collisions.append((digest, ordered))

title("matching")
print(f"  rows read from the ministry list : {len(wanted)}")
print(f"  employees carrying a passport    : {len(by_digest)}")

missing = sorted(set(wanted) - set(by_digest))
print(f"  on the list but not in Odoo      : {len(missing)}")
for digest in missing:
    print(f"    {masks[digest]}  ->  {wanted[digest]}")

matched = {d: by_digest[d] for d in wanted if d in by_digest}
print(f"  matched                          : {len(matched)}")

relevant = [(d, recs) for d, recs in collisions if d in wanted]
if relevant:
    title("one passport, several records - the first line is the one taken")
    for digest, recs in relevant:
        print(f"  {masks.get(digest, digest)}")
        for emp in recs:
            version = emp.current_version_id
            print(f"      id={emp.id:<6} active={str(emp.active):<5} "
                  f"badge={(emp.barcode or '-'):<9} "
                  f"wage={getattr(version, 'wage', 0) or 0:<8.0f} co={emp.company_id.id}")

lapsed = []
permit_writes = []
contract_writes = []
unchanged = 0

for digest, emp in matched.items():
    end = wanted[digest]
    if emp.work_permit_expiration_date != end:
        permit_writes.append((emp, emp.work_permit_expiration_date, end))
    version = emp.current_version_id if 'current_version_id' in emp._fields else None
    if end < today:
        lapsed.append((emp, end))
        continue
    if version and version.contract_date_end != end:
        contract_writes.append((emp, version, version.contract_date_end, end))
    else:
        unchanged += 1

title("1. work permit expiry to correct on hr.employee")
print(f"  {len(permit_writes)} employee(s)")
for emp, was, now in permit_writes[:20]:
    print(f"    {emp.name[:34]:<34} {str(was):<12} -> {now}")
if len(permit_writes) > 20:
    print(f"    ... and {len(permit_writes) - 20} more")

title("2. contract end to set on the current version")
needs_start = [c for c in contract_writes if not c[1].contract_date_start]
guessed = [c for c in needs_start if not joining_date_of(c[0])]
print(f"  {len(contract_writes)} version(s), {unchanged} already correct")
print(f"  of those, {len(needs_start)} have no start date and will be given one:")
print(f"      {len(needs_start) - len(guessed)} from the joining date on ssc.employee")
print(f"      {len(guessed)} with no joining date anywhere - version date used")
for emp, ver, _was, _now in guessed:
    print(f"        {emp.name[:34]:<34} badge={(emp.barcode or '-'):<9} "
          f"-> {ver.date_version}")
for emp, ver, was, now in contract_writes[:20]:
    print(f"    {emp.name[:30]:<30} ver={ver.id:<6} {str(was):<12} -> {now}")
if len(contract_writes) > 20:
    print(f"    ... and {len(contract_writes) - 20} more")

title("3. PERMITS ALREADY LAPSED - not written, HR must renew")
print(f"  {len(lapsed)} employee(s)")
for emp, end in sorted(lapsed, key=lambda x: x[1]):
    print(f"    {emp.name[:34]:<34} expired {end}  ({(today - end).days} day(s) ago)  "
          f"badge={emp.barcode or '-'}")

if APPLY:
    # One savepoint per employee. A contract period can collide with an older
    # version that was left open-ended, and one such collision must not throw
    # away the other hundred and fifty writes - it must name itself and let the
    # rest through.
    done_permits = 0
    done_contracts = 0
    failures = []

    for emp, _was, now in permit_writes:
        try:
            with env.cr.savepoint():
                emp.work_permit_expiration_date = now
            done_permits += 1
        except Exception as error:
            failures.append((emp, 'permit', str(error).splitlines()[0][:90]))

    for emp, ver, _was, now in contract_writes:
        vals = {'contract_date_end': now}
        if not ver.contract_date_start:
            vals['contract_date_start'] = contract_start_for(emp, ver)
        try:
            with env.cr.savepoint():
                ver.write(vals)
            done_contracts += 1
        except Exception as error:
            failures.append((emp, 'contract', str(error).splitlines()[0][:90]))

    env.cr.commit()
    title("APPLIED")
    print(f"  permit dates written   : {done_permits} / {len(permit_writes)}")
    print(f"  contract ends written  : {done_contracts} / {len(contract_writes)}")
    if failures:
        print(f"\n  {len(failures)} refused:")
        for emp, what, message in failures:
            print(f"    {emp.name[:32]:<32} {what:<9} {message}")
    print("\n  Recompute attendance overtime afterwards - the phantom hours came")
    print("  from these employees falling outside their own contract.")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
