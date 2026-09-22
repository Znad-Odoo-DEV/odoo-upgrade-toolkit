"""Three more ministry lists: permit expiry, nationality, and the job on the card.

    odoo-bin shell -d <database> --no-http < tools/set_permits_other_companies.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_permits_other_companies.py

The Saud Shehatha list was done weeks ago. These are the other three
establishments, printed 23 August 2026: Malak Al Reem 15, Royal Arrow 68, Royal
Wooden Doors 25. A hundred and eight permits.

WHAT IS TAKEN

The permit expiry becomes the contract end date, which is what stops a payslip
being produced for somebody whose right to work has lapsed. The nationality
fills a field that is empty on seventy two active employees and is required on
a WPS file. The job on the card fills the job title where there is none.

Nothing is overwritten except the contract end date. A nationality or a job
already recorded is left alone - the ministry card is a snapshot, and the
record may have been corrected since it was printed.

WHAT IS NOT WRITTEN DOWN

The passport numbers. They are the strongest identifier a person has and have
no business living in a git repository, so each is reduced to the first twenty
characters of its SHA-256 and only the fingerprint is kept. It matches an
employee whose passport hashes to the same value and is useless for anything
else. The names are here because they are already in the database.

MATCHING

By fingerprint first, which is exact. Then by name with everything but letters
and digits stripped, which catches the ones whose passport in Odoo is a typo or
a placeholder. Whatever is still unmatched is printed with its establishment,
and that count is the honest measure of how far the two systems have drifted.
"""
import hashlib
import os
import re
from collections import Counter
from datetime import datetime

APPLY = os.environ.get('SSC_APPLY') == '1'

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Employee = env['hr.employee'].sudo()
Country = env['res.country'].sudo()

# fingerprint, name, permit expiry, nationality, job, establishment
DATA = [
    ("aee27791ee1fe4e14a9a", "MOHAMMAD SHABAN KHAN MOHAMMAD TAHIR KHAN", "27/12/2026", "IN", "Building Labourer", "MALAK AL REEM"),
    ("2fe8720915c1e511a6d6", "FARID KIBERU", "25/08/2027", "UG", "Carpenter", "MALAK AL REEM"),
    ("bb6cf26516daa69bcfb2", "AHMED HASSAN HASSAN DARWISH", "04/02/2028", "EG", "Chief Executive Officer", "MALAK AL REEM"),
    ("4990b90913e8dc6947e4", "ANNA KHAFIZOVA", "05/07/2027", "RU", "Sales Officer", "MALAK AL REEM"),
    ("7ff895c0ce2a4b93f9cc", "MOHAMED HAKKEEM HAJANAJUMUTHEEN ABDUL HAKKEM", "15/10/2026", "IN", "Security Guard", "MALAK AL REEM"),
    ("313ccdb212dd2975405c", "JASIYA MUHAMMED ASHRAF VALIYIL ABOOBACKER", "04/08/2028", "IN", "Accountant", "MALAK AL REEM"),
    ("0da8b931ae118b463b15", "MOHAMED AHMED ABDELRAOUF ALI", "16/11/2027", "EG", "Accountant", "MALAK AL REEM"),
    ("afe5a1a6031ff1194c95", "MARY GRACE ANN ALVEZ BALISTOY", "04/10/2027", "PH", "Administrative Supervisor", "MALAK AL REEM"),
    ("6822a678b24bb808fcda", "TAMIRU GUTA GOBANA", "18/09/2026", "ET", "Building Labourer", "MALAK AL REEM"),
    ("1845174359a96921dec0", "ZARINA KHANAM BINTI WAZIR MOHAMAD KHAN", "21/09/2027", "MY", "Business Service Manager", "MALAK AL REEM"),
    ("1bb8dc97bf4bfa7bff6c", "KELECHI MONDAY AGUORU", "31/01/2027", "NG", "Filing Clerk", "MALAK AL REEM"),
    ("c6d0f04ab953fc48398f", "ASGER ALI ABDUL MAJID", "21/11/2026", "IN", "Messenger", "MALAK AL REEM"),
    ("279df0a83cabdc40dd52", "NANTHINI KEERTHI ASAITHAMBI", "03/10/2027", "IN", "Messenger", "MALAK AL REEM"),
    ("9b6710722a0090d9508e", "BORIS NUYIT DOHBIT", "22/11/2026", "CM", "Office Cleaner", "MALAK AL REEM"),
    ("4294aaf32f51ad60ee60", "APRIL JOY RONQUILLO CARIAGA", "09/09/2027", "PH", "Sales Officer", "MALAK AL REEM"),
    ("b27d1ae0a7e688d12726", "ISMAIL IBRAHIM ABDELRAZEK MOHAMED", "12/12/2026", "EG", "Building Exterior Cleaner", "ROYAL ARROW"),
    ("0f0adb13bb667e8c5253", "HEBA EYAD MOHAMED SALEM ALHADHRAMI", "30/11/2026", "AE", "Correspondence Clerk", "ROYAL ARROW"),
    ("b232b5b609e58506d580", "MARYAM SAIF SALEM ALI ALKALBANI", "31/05/2027", "AE", "Information Clerk", "ROYAL ARROW"),
    ("41b45ff07261b552e366", "RAUDA AHMED SAIF RASHED ALSHAMSI", "14/06/2027", "AE", "Information Clerk", "ROYAL ARROW"),
    ("9242d059a4065a738d71", "MAITHA SAIF SALEM ALI ALKALBANI", "02/06/2028", "AE", "Correspondence Clerk", "ROYAL ARROW"),
    ("39c989296e1998cd11bc", "LAMBODAR MAHUNTA BISHNU CHARAN MAHUNTA", "15/04/2027", "IN", "Air Conditioning Assistant", "ROYAL ARROW"),
    ("54b94968f358a569bb3b", "MD MARFOT ALI ROSTOM ALI", "29/10/2026", "BD", "Air Conditioning Assistant", "ROYAL ARROW"),
    ("f2b3f22f7e2e3597ca9a", "ABDALELAH JAMAL ALMASRI", "27/04/2028", "SY", "Building Painter", "ROYAL ARROW"),
    ("b7d8a27d0c843f3e02a2", "SHAMSHER SINGH HARPAL SINGH", "27/04/2028", "IN", "Bus Driver", "ROYAL ARROW"),
    ("d9e224ab198c8ffacc56", "ABDUL ELAH HAMDAN ALKABIRI", "18/04/2027", "SY", "Carpenter", "ROYAL ARROW"),
    ("13f1bfef9256413296a3", "AHMED MANSOUR ELSAYED MANSOUR AMER", "15/01/2028", "EG", "Carpenter", "ROYAL ARROW"),
    ("090791b7e83d2c3cae15", "AJEET KUMAR JAGADISH PRASAD", "11/03/2027", "IN", "Carpenter", "ROYAL ARROW"),
    ("ecd95dc76ff534b9f59b", "FIKRE TEGENU EJERSA", "29/04/2027", "ET", "Carpenter", "ROYAL ARROW"),
    ("0a027031d09b0a8ec41d", "MOHAMMAD RIPON MIA MD MIZAN", "08/12/2026", "BD", "Carpenter", "ROYAL ARROW"),
    ("ed6952ffdebb61de6934", "RAJESH VADEKKEKANDY MAKKOTHA VADEKKEKANDY", "11/11/2026", "IN", "Electrical Mechanic", "ROYAL ARROW"),
    ("1c6da960ec95307d20b6", "EZAT MOSSAD RASHAD ELSAID ABOUAMOU", "18/12/2026", "EG", "Electrician", "ROYAL ARROW"),
    ("114f43853cd7e76cfc0b", "MAIN UDDIN HUMAUN KABIR", "05/01/2027", "BD", "Electrician", "ROYAL ARROW"),
    ("5490489ae2ef73d3f80c", "MOHAMED ELSAYED IBRAHIM IBRAHIM HASSAN", "19/12/2026", "EG", "Electrician", "ROYAL ARROW"),
    ("36d9ae3156f213edb6ae", "JAMES WEAVER", "28/08/2027", "SL", "Electrician Assistant", "ROYAL ARROW"),
    ("c9573255010d634544c0", "PRASHANTH KHAMUNI CHANDRAM KHAMUNI", "01/10/2026", "IN", "Electrician Assistant", "ROYAL ARROW"),
    ("3d0b47af1dba142c26e4", "AHMAD ALI SAMEU", "31/07/2026", "SY", "Plumber", "ROYAL ARROW"),
    ("7d00394e02b1c1ba1655", "KHALIL HUSSEIN MOHAMED KHALIL", "07/10/2027", "EG", "Plumber", "ROYAL ARROW"),
    ("097ef220f4b0e7dd0b6d", "MD SHANTI MIA MD GIAS UDDIN", "29/10/2026", "BD", "Plumber", "ROYAL ARROW"),
    ("5a6f3138e09b821130fa", "SARWAR BEG ANWER BEG", "08/12/2026", "IN", "Plumber", "ROYAL ARROW"),
    ("02ec699ba5749f08aba9", "MOHAMED TAHA ABDELGHANI MOHAMED", "19/12/2026", "EG", "Plumber Assistant", "ROYAL ARROW"),
    ("35de55f60b8d640ba6d2", "BASHARI ABDELRADI BASHARI MOHAMED", "18/04/2027", "EG", "Printer", "ROYAL ARROW"),
    ("1bf653984af33c86bc07", "MD AHSAN HOSSAIN SOLAYMAN BAPARY", "29/10/2026", "BD", "Steel Fixer", "ROYAL ARROW"),
    ("260a02c1e4524013805a", "RIYAS ABOOBAKAR ABOOBAKER", "08/12/2026", "IN", "Steel Fixer", "ROYAL ARROW"),
    ("16f7f5657b0f19f2e354", "SHEIKH MASLUDDIN AHMAD SHEIKH MASTAKIM", "30/11/2026", "IN", "Steel Fixer", "ROYAL ARROW"),
    ("d5b45b6a69b7544f3b8d", "YOUSEF MUNIR AL RIFAI", "08/02/2027", "SY", "Stone Carver", "ROYAL ARROW"),
    ("32e204ab234295ac7f9c", "BENARD ANYAMBA ENGOKE", "10/12/2027", "KE", "Wood Carver", "ROYAL ARROW"),
    ("68a6a24b5f039f53c908", "SHAHRUKH KHURSHID", "22/12/2027", "IN", "Wood Carver", "ROYAL ARROW"),
    ("c3ae27c8b4cade603340", "ARUNKUMAR GANESAN GANESAN", "24/05/2027", "IN", "Air Conditioning Assistant", "ROYAL ARROW"),
    ("0758c5dd74aee0c49966", "IJAZ KHAN MADI SUBKHAN", "02/05/2027", "PK", "Air Conditioning Assistant", "ROYAL ARROW"),
    ("dc44dd48c804958daa1a", "MD ABDUR RAHIM MD HOSSEN AHMED", "08/01/2027", "BD", "Air Conditioning Assistant", "ROYAL ARROW"),
    ("bc45433f1a73642bdc40", "MOHD ERSHAD ANSARI", "03/02/2027", "IN", "Air Conditioning Mechanic", "ROYAL ARROW"),
    ("c596ac8d3efeea7e5003", "BADRAN MOHAMED REZK ELSHAFEY ELSHAFEY", "19/10/2026", "EG", "Carpenter", "ROYAL ARROW"),
    ("b1d5d6a32540011d3f8e", "SUKHDEV PAL JOGINDER", "22/06/2027", "IN", "Carpenter", "ROYAL ARROW"),
    ("3967532ce633e1dab3d4", "HAREESH KUMAR KURUNTHIL", "07/03/2028", "IN", "Electrical Engineer", "ROYAL ARROW"),
    ("04f538efe752203cc8d0", "ABHISHEK BIJU SALINI BIJU SURENDRAN", "23/07/2028", "IN", "Electrician", "ROYAL ARROW"),
    ("b446f80021f1afed9e31", "FAIJUL HASAN IBNE HASAN", "02/07/2028", "IN", "Electrician", "ROYAL ARROW"),
    ("003a4a90137863d6543c", "RAJASEKARAN RAJENDRAN RAJENDRAN", "04/10/2027", "IN", "Electrician", "ROYAL ARROW"),
    ("131ab73a054d270bf087", "SHAKIR VALIYIL ABOOBACKER VALIYIL", "04/04/2028", "IN", "Electrician", "ROYAL ARROW"),
    ("4cdae12620d8af8be062", "ABU AHMED FAZAL AHMED", "05/01/2027", "BD", "Electrician Assistant", "ROYAL ARROW"),
    ("d0385125da89d7d97db1", "IRSHAD ALI ANWAR ALI", "04/01/2027", "IN", "Electrician Assistant", "ROYAL ARROW"),
    ("2074f7fae54e7af8c899", "MADAN RANABHAT", "04/08/2026", "NP", "Electrician Assistant", "ROYAL ARROW"),
    ("1c503ca7cdde15d38928", "PRASHANTH KYAMA RAJULU KYAMA", "03/10/2027", "IN", "Electrician Assistant", "ROYAL ARROW"),
    ("0fa3e789b26fba3104e8", "RAGESH PEETHAMBARAN SUJATHA", "06/10/2026", "IN", "Electrician Assistant", "ROYAL ARROW"),
    ("2d231d8cb2e6acb08740", "RAMACHANDRAN LAKSHMANAN", "12/06/2027", "IN", "Electrician Assistant", "ROYAL ARROW"),
    ("f55c72a263e3baf7c4f5", "SHAJI SUNDARESAN KUNJIRAMAN SUNDARESAN", "25/07/2028", "IN", "Electrician Assistant", "ROYAL ARROW"),
    ("5840fa35b82a92401f62", "SHAMEER SHERAFUDEEN SHERAFUDEEN", "08/06/2026", "IN", "Electrician Assistant", "ROYAL ARROW"),
    ("c0b6c631561cee91f26e", "VISHVAJEET MAURYA KAILASH NATH MAURYA", "02/07/2028", "IN", "Electrician Assistant", "ROYAL ARROW"),
    ("d82edfa6080739bb0fcc", "BAIJU BABU DAMODARAN BABU", "08/12/2026", "IN", "Mechanic Assistant", "ROYAL ARROW"),
    ("a80745fdd83bcd4e9d30", "SUNESHKUMAR MOONAMKUTTY CHIRAYIL DINESAN", "02/11/2026", "IN", "Mechanic Assistant", "ROYAL ARROW"),
    ("4f3e02da7412ed8d708d", "MONU KIRAN DEV", "17/01/2028", "IN", "Mechanical Engineer", "ROYAL ARROW"),
    ("1138954ae6f1bc793475", "KALAIVANAN OLAIYUR KANNAPPAN", "07/03/2028", "IN", "Pipe Fitter", "ROYAL ARROW"),
    ("0bf38ae76a7a09239f62", "AMJAD HOSSAIN SENTU MIAH", "05/10/2026", "BD", "Plumber", "ROYAL ARROW"),
    ("91626443bd26ef132d23", "BECHAN CHAUHAN HANNOO CHAUHAN", "02/07/2028", "IN", "Plumber", "ROYAL ARROW"),
    ("951e3ab776ba2d65848d", "KAMLESH RAMKARAN", "28/07/2026", "IN", "Plumber", "ROYAL ARROW"),
    ("b4078b7c26c9d1c07d11", "MD ASLAM TALUKDER MD HABIB TALUKDER", "18/06/2027", "BD", "Plumber", "ROYAL ARROW"),
    ("fb2b9779b0fc61d27dd6", "MD SHORIFUL ISLAM MD MESER ALI", "18/06/2027", "BD", "Plumber", "ROYAL ARROW"),
    ("ee40679af2512c1a5cec", "PUSHPENDRAN OLIKALMELETHIL DIVAKARAN DIVAKARAN NAIR", "05/02/2027", "IN", "Plumber", "ROYAL ARROW"),
    ("c44effefde99c5b556e6", "RAJIV MUTHUDURAI MUTHUDURAI", "29/05/2028", "IN", "Plumber", "ROYAL ARROW"),
    ("324c20d877b449cb1db6", "SABUJ MIAH BILLAL HOSSAIN", "11/06/2028", "BD", "Plumber", "ROYAL ARROW"),
    ("a1d3a517bfa66a0cafec", "KASEM ABDULAZIZ ALHAJ AHMAD", "13/07/2028", "SY", "Plumber Assistant", "ROYAL ARROW"),
    ("bff0468aad7c849f14d1", "ABDULLAH KHAN RAST BAZ KHAN", "20/10/2026", "PK", "Steel Fixer", "ROYAL ARROW"),
    ("41ed20943da8b2b98f74", "GURINDER SINGH SATNAM SINGH", "13/07/2028", "IN", "Steel Fixer", "ROYAL ARROW"),
    ("12563187e1f9fe8754fd", "PARFAIT UWANSHUTI", "28/07/2026", "RW", "Stonemason", "ROYAL ARROW"),
    ("58b554f441ee82882fa0", "EMMANUEL BIMENYIMANA", "05/10/2026", "RW", "Carpenter", "ROYAL WOODEN"),
    ("7ba28cbf7ee51f98663c", "IRFAN ULLAH NOOR GUL", "25/08/2027", "PK", "Carpenter", "ROYAL WOODEN"),
    ("84508f77abc7163e0108", "MD JOAT ALI KHOKA MONDOL", "12/11/2026", "BD", "Carpenter", "ROYAL WOODEN"),
    ("9518c79ca93c62d4d744", "OLIVIER KWIZERA", "30/09/2026", "RW", "Carpenter", "ROYAL WOODEN"),
    ("22cd76251ab21de0baae", "BADAL HOSSAIN MD SAFI UDDIN", "12/11/2026", "BD", "Steel Fixer", "ROYAL WOODEN"),
    ("dc513457e071d17a1caf", "ROHIT KANNAUJIYA CHAUDHARI PRASAD", "18/04/2028", "IN", "Wood Processing Plant Operator", "ROYAL WOODEN"),
    ("56f4ecdae2fd1afedf72", "MAHMOUD AYMAN MORSY EWIS", "03/02/2028", "EG", "Wood Treater", "ROYAL WOODEN"),
    ("94e4d17ec7d9f8f324da", "DEEPAK RAKESH KUMAR", "28/11/2026", "IN", "Wood Turner", "ROYAL WOODEN"),
    ("646522efb846a078ae97", "MOHAMMAD LIMON MIAH USTAR MIAH", "12/11/2026", "BD", "Wood Turner", "ROYAL WOODEN"),
    ("58b3acd82b334e58f8fd", "MOKHTAR FAHMY YOUSSEF SAMRA", "27/07/2027", "EG", "Wood Turner", "ROYAL WOODEN"),
    ("ccdb4f2d7d18e574d98e", "SHAFFY AHMED UZAYISENGA", "05/10/2026", "RW", "Wood Turner", "ROYAL WOODEN"),
    ("ace97174ba1193ab4a78", "JEAN REONARD YIBUKIRO", "02/07/2026", "RW", "Carpenter", "ROYAL WOODEN"),
    ("07cb1805a69ef3c4d247", "APHRODICE TWIZEYUMUREMYI", "01/10/2026", "RW", "Steel Fixer", "ROYAL WOODEN"),
    ("dc620a73c15ddf8ebd10", "AYYANAR KARUPPAIAH KARUPPAIAH", "16/11/2027", "IN", "Brick Mason", "ROYAL WOODEN"),
    ("5d9737ab6eee8b07ad86", "GURDIAL SINGH GURBACHAN SINGH", "01/06/2028", "IN", "Carpenter", "ROYAL WOODEN"),
    ("739a9008e517052f1874", "JEAN BOSCO MUHIRE", "01/07/2028", "RW", "Carpenter", "ROYAL WOODEN"),
    ("d0a41d4510e66690f0dc", "MD LITON MIA ABDUL SATTAR", "06/05/2028", "BD", "Carpenter", "ROYAL WOODEN"),
    ("8d919840a8bcfbd1f603", "THILIPKUMAR KALIYAPERUMAL KALIYAPERUMAL", "18/11/2027", "IN", "Furniture Woodworker", "ROYAL WOODEN"),
    ("b9cedf5ea20ba6d5386e", "WALID SALAH ABDELDAYEM MABROUK", "11/03/2028", "EG", "Light Vehicle Driver", "ROYAL WOODEN"),
    ("c5268811c8b132e81250", "FELIX NIYONSENGA", "01/07/2028", "RW", "Steel Fixer", "ROYAL WOODEN"),
    ("d9cdac42ec15e4fe0986", "EMMANUEL TUYIZERE", "01/07/2028", "RW", "Tile Layer", "ROYAL WOODEN"),
    ("05b2e2889b5d85fb3073", "SUNIL CHAUDHARI RAJBALI CHAUDHARI", "15/11/2027", "IN", "Tile Layer", "ROYAL WOODEN"),
    ("530574b1c4b489e865f3", "AVTAR KISHAN SAGLI RAM", "17/04/2028", "IN", "Wood Turner", "ROYAL WOODEN"),
    ("86f366db55951564b7f2", "BILAL VONJOE", "29/02/2028", "SL", "Wood Turner", "ROYAL WOODEN"),
    ("999763cf7bc547a9a038", "JEAN CLAUDE MUGISHA", "01/07/2028", "RW", "Wood Turner", "ROYAL WOODEN"),
]


def title(text):
    print()
    print("=" * 98)
    print(text)
    print("=" * 98)


def fingerprint(passport):
    return hashlib.sha256((passport or '').strip().upper().encode()).hexdigest()[:20]


def flatten(name):
    return re.sub(r'[^A-Z0-9]', '', (name or '').upper())


active = Employee.with_context(active_test=True).search([])
everyone = Employee.search([])
gone = everyone - active

by_passport, by_name = {}, {}
for person in active:
    if person.passport_id:
        by_passport.setdefault(fingerprint(person.passport_id), []).append(person)
    by_name.setdefault(flatten(person.name), []).append(person)

# The same, over the people who have already left. A card that matches one of
# these is explained rather than missing, and nothing is written for them.
left_passport, left_name = {}, {}
for person in gone:
    if person.passport_id:
        left_passport.setdefault(fingerprint(person.passport_id), []).append(person)
    left_name.setdefault(flatten(person.name), []).append(person)


def by_prefix(name):
    """The card carries the full name and the record often carries less of it.

    'April Joy' against 'APRIL JOY RONQUILLO CARIAGA'. Only accepted when one
    name is the start of the other, it is at least ten characters in, and
    exactly one employee fits - a short prefix would match half the payroll.
    """
    flat = flatten(name)
    hits = [p for key, people in by_name.items() if len(key) >= 10
            and (key.startswith(flat) or flat.startswith(key))
            for p in people]
    return hits if len(hits) == 1 else []

countries = {c.code: c for c in Country.search([])}

# ---------------------------------------------------------------------------
title("1. matching the cards to the employees")

matched, unmatched, ambiguous, departed = [], [], [], []
for fp, name, expiry, code, job, establishment in DATA:
    people, how = by_passport.get(fp), 'passport'
    if not people:
        people, how = by_name.get(flatten(name)), 'name'
    if not people:
        people, how = by_prefix(name), 'shortened name'
    if not people:
        was = left_passport.get(fp) or left_name.get(flatten(name))
        if was:
            departed.append((name, expiry, establishment, was[0]))
        else:
            unmatched.append((name, expiry, establishment))
        continue
    if len(people) > 1:
        ambiguous.append((name, establishment, people))
        continue
    matched.append((people[0], name, expiry, code, job, establishment, how))

print(f"  cards on the three lists : {len(DATA)}")
print(f"  matched                  : {len(matched)}")
for how, number in Counter(row[6] for row in matched).most_common():
    print(f"      by {how:<10} {number}")
print(f"  more than one candidate  : {len(ambiguous)}")
print(f"  already left, left alone : {len(departed)}")
print(f"  no employee found        : {len(unmatched)}")

# ---------------------------------------------------------------------------
title("2. what changes")

plan = []
for person, name, expiry, code, job, establishment, how in matched:
    version = person.current_version_id
    end = datetime.strptime(expiry, '%d/%m/%Y').date()
    vals = {}
    if version and version.contract_date_start and version.contract_date_end != end:
        vals['contract_date_end'] = end
    country = countries.get(code)
    if country and version and not version.country_id:
        vals['country_id'] = country.id
    if job and not person.job_title:
        vals['job_title'] = job
    if vals:
        plan.append((person, version, vals, expiry, establishment))

print(f"  {len(plan)} employee(s) to touch")
print()
print(f"  {'employee':<36} {'permit ends':<12} what")
for person, _version, vals, expiry, establishment in sorted(plan,
                                                            key=lambda r: r[0].name):
    print(f"  {person.name[:36]:<36} {expiry:<12} {', '.join(sorted(vals))}")

no_start = [row for row in matched if row[0].current_version_id
            and not row[0].current_version_id.contract_date_start]
if no_start:
    print()
    print(f"  {len(no_start)} matched employee(s) have no contract start date, so no")
    print("  end date can be written - the database refuses one without the other")

# ---------------------------------------------------------------------------
if ambiguous:
    title("3. the same name on more than one live record")
    for name, establishment, people in ambiguous:
        print(f"  {name}   ({establishment})")
        for person in people:
            print(f"      id={person.id:<6} badge={(person.barcode or '-'):<10} "
                  f"{person.company_id.name[:34]}")

if departed:
    title("4. on a ministry list and already archived here - nothing written")
    for name, expiry, establishment, person in sorted(departed):
        print(f"  {name[:46]:<46} {expiry:<12} {establishment:<16} "
              f"left {person.departure_date or 'date unknown'}")

if unmatched:
    title("5. on a ministry list, not in Odoo at all")
    for establishment, number in Counter(row[2] for row in unmatched).most_common():
        print(f"  {establishment:<20} {number}")
    print()
    for name, expiry, establishment in sorted(unmatched):
        print(f"  {name[:52]:<52} {expiry:<12} {establishment}")

# ---------------------------------------------------------------------------
title("6. the company here against the establishment that issued the permit")

# A permit is issued to an establishment, and the company on the employee
# record decides which salary structure computes the payslip and which journal
# the entry lands in - and which WPS file the person appears on. When they
# disagree, all three go somewhere the ministry does not expect.
elsewhere = []
for person, name, expiry, code, job, establishment, how in matched:
    here = (person.company_id.name or '').upper()
    if establishment.split()[0] not in here:
        elsewhere.append((person, establishment))

print(f"  {len(matched)} matched, of whom {len(elsewhere)} are filed under a")
print("  company that did not issue their permit")
print()
pairs = Counter((p.company_id.name[:34], e) for p, e in elsewhere)
print(f"  {'company on the employee record':<36} {'permit issued by':<18} {'people'}")
for (company, establishment), number in pairs.most_common():
    print(f"  {company:<36} {establishment:<18} {number:>6}")
if elsewhere:
    print()
    for person, establishment in sorted(elsewhere, key=lambda r: r[0].name)[:25]:
        print(f"      {person.name[:38]:<38} here {person.company_id.name[:26]:<26} "
              f"permit {establishment}")
    if len(elsewhere) > 25:
        print(f"      ... and {len(elsewhere) - 25} more")

# ---------------------------------------------------------------------------
if APPLY:
    done, failed = 0, []
    for person, version, vals, _expiry, _establishment in plan:
        contract_vals = {k: v for k, v in vals.items() if k != 'job_title'}
        try:
            with env.cr.savepoint():
                if contract_vals and version:
                    version.write(contract_vals)
                if 'job_title' in vals:
                    person.job_title = vals['job_title']
            done += 1
        except Exception as error:
            failed.append((person.name, str(error).splitlines()[0][:70]))
    env.cr.commit()

    title("APPLIED")
    print(f"  written {done} | refused {len(failed)}")
    for name, message in failed:
        print(f"      {name[:32]:<32} {message}")
    still = Employee.with_context(active_test=True).search([]).filtered(
        lambda e: e.current_version_id and not e.current_version_id.country_id)
    print()
    print(f"  active employees still without a nationality: {len(still)}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
