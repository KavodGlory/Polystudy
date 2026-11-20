"""SQLite setup and seed data for quizzes and public institutional links."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name('study_guide.db')

def init_db():
    """Create application tables and seed quiz questions and official public links."""
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.executescript('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            language TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            lang_q TEXT NOT NULL,
            lang_a TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS university_faq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            title_en TEXT NOT NULL,
            body_en TEXT NOT NULL,
            title_sw TEXT NOT NULL,
            body_sw TEXT NOT NULL,
            icon TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS study_quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            question_en TEXT NOT NULL,
            question_sw TEXT NOT NULL,
            choices_en TEXT NOT NULL,
            choices_sw TEXT NOT NULL,
            answer_index INTEGER NOT NULL,
            explanation_en TEXT NOT NULL,
            explanation_sw TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS institution_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            title_sw TEXT NOT NULL,
            summary_sw TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            icon TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_cache (
            query TEXT NOT NULL,
            result_limit INTEGER NOT NULL,
            fetched_at REAL NOT NULL,
            results_json TEXT NOT NULL,
            PRIMARY KEY (query, result_limit)
        );
        ''')
        cur.executemany(
            "INSERT OR IGNORE INTO institution_resources "
            "(institution, category, title, summary, title_sw, summary_sw, url, icon) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("USIU-Africa", "Admissions", "How to apply",
                 "Review program details and admission requirements, then use the application form for your selected program. Check USIU-Africa's official page for current instructions.",
                 "Jinsi ya kutuma ombi",
                 "Kagua maelezo ya programu na masharti ya udahili, kisha tumia fomu ya programu uliyochagua. Angalia ukurasa rasmi wa USIU-Africa kwa maelekezo ya sasa.",
                 "https://www.usiu.ac.ke/how-to-apply/", "↗"),
                ("USIU-Africa", "Admissions", "Admission requirements",
                 "USIU-Africa publishes general and program-specific admission requirements. Confirm current requirements directly with the university.",
                 "Masharti ya udahili",
                 "USIU-Africa huchapisha masharti ya jumla na ya kila programu. Thibitisha masharti ya sasa moja kwa moja na chuo kikuu.",
                 "https://www.usiu.ac.ke/admission-requirements/", "✓"),
                ("USIU-Africa", "Fees", "Tuition and fees",
                 "The official page publishes the current fee schedule. Costs depend on program and student category; verify the latest figures before making payment.",
                 "Ada ya masomo na gharama",
                 "Ukurasa rasmi huchapisha ratiba ya sasa ya ada. Gharama hutegemea programu na kundi la mwanafunzi; thibitisha viwango vya karibuni kabla ya kulipa.",
                 "https://www.usiu.ac.ke/tuition-fees/", "▤"),
                ("USIU-Africa", "Housing", "Room and board application",
                 "Use the university's official housing application information and contact USIU-Africa for current availability and dates.",
                 "Ombi la malazi na chakula",
                 "Tumia maelezo rasmi ya chuo kuhusu maombi ya malazi na uwasiliane na USIU-Africa kuhusu nafasi na tarehe za sasa.",
                 "https://www.usiu.ac.ke/documents/room-and-board-housing-application-form/", "⌂"),
                ("USIU-Africa", "Student life", "Student life and campus activities",
                 "Official information about student clubs, sports, events, and campus activities.",
                 "Maisha ya wanafunzi na shughuli za chuoni",
                 "Maelezo rasmi kuhusu vilabu vya wanafunzi, michezo, matukio na shughuli za chuoni.",
                 "https://www.usiu.ac.ke/student-life/", "✳"),
                ("USIU-Africa", "Health", "Health and wellness",
                 "Find the university's published information about health services, counseling, and wellness support.",
                 "Afya na ustawi",
                 "Pata maelezo yaliyochapishwa na chuo kuhusu huduma za afya, ushauri nasaha na msaada wa ustawi.",
                 "https://www.usiu.ac.ke/health-wellness/", "＋"),
                ("USIU-Africa", "Accessibility", "Disability inclusion",
                 "The Disability Inclusion page explains the university's accessibility support and services.",
                 "Ujumuishaji wa watu wenye ulemavu",
                 "Ukurasa wa ujumuishaji wa watu wenye ulemavu unaeleza msaada na huduma za ufikivu za chuo.",
                 "https://www.usiu.ac.ke/disability-inclusion/", "◇"),
                ("USIU-Africa", "Academics", "Programs and schools",
                 "Browse official undergraduate, master's, and doctoral program information.",
                 "Programu na shule",
                 "Vinjari maelezo rasmi kuhusu programu za shahada ya kwanza, uzamili na uzamivu.",
                 "https://www.usiu.ac.ke/academics/our-programs/", "文"),
                ("USIU-Africa", "Events", "Upcoming events",
                 "Check the university's events page for current campus announcements; event listings can change.",
                 "Matukio yajayo",
                 "Angalia ukurasa wa matukio wa chuo kwa matangazo ya sasa; orodha ya matukio inaweza kubadilika.",
                 "https://www.usiu.ac.ke/upcoming-events/", "◷"),
                ("USIU-Africa", "General", "Official university FAQ",
                 "Browse USIU-Africa's published answers to general questions about programs and student support.",
                 "Maswali yanayoulizwa mara kwa mara",
                 "Vinjari majibu yaliyochapishwa na USIU-Africa kuhusu programu na msaada kwa wanafunzi.",
                 "https://www.usiu.ac.ke/about-us/faq/", "？"),
            ],
        )
        if cur.execute("SELECT COUNT(*) FROM study_quizzes").fetchone()[0] == 0:
            import json
            cur.executemany(
                "INSERT INTO study_quizzes "
                "(subject, question_en, question_sw, choices_en, choices_sw, answer_index, "
                "explanation_en, explanation_sw) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("Study skills", "Which habit is most effective for remembering material over time?",
                     "Ni tabia gani inayosaidia zaidi kukumbuka masomo kwa muda mrefu?",
                     json.dumps(["Rereading notes once", "Spaced practice", "Studying only the night before", "Highlighting every sentence"]),
                     json.dumps(["Kusoma tena maelezo mara moja", "Kujifunza kwa vipindi vilivyotenganishwa", "Kusoma usiku mmoja kabla tu", "Kupigia mstari kila sentensi"]),
                     1, "Spaced practice revisits information over time, strengthening recall.",
                     "Kujifunza kwa vipindi vilivyotenganishwa hurudia taarifa baada ya muda na kuimarisha kumbukumbu."),
                    ("Research", "Which source is usually strongest for a research paper?",
                     "Ni chanzo gani kwa kawaida kinafaa zaidi kwa makala ya utafiti?",
                     json.dumps(["An anonymous social post", "A peer-reviewed journal article", "An unsourced image", "A random comment"]),
                     json.dumps(["Chapisho lisilo na jina kwenye mitandao", "Makala ya jarida iliyopitiwa na wataalamu", "Picha isiyo na chanzo", "Maoni ya kawaida mtandaoni"]),
                     1, "Peer review adds an expert quality check; still assess the article's relevance and date.",
                     "Mapitio ya wataalamu huongeza ukaguzi wa ubora; bado tathmini umuhimu na tarehe ya makala."),
                    ("Digital literacy", "What should you do before opening an unexpected attachment?",
                     "Unapaswa kufanya nini kabla ya kufungua kiambatisho usichokitarajia?",
                     json.dumps(["Open it immediately", "Verify the sender and context", "Forward it to everyone", "Disable security settings"]),
                     json.dumps(["Kifungue mara moja", "Thibitisha mtumaji na muktadha", "Kitume kwa kila mtu", "Zima mipangilio ya usalama"]),
                     1, "Verify unexpected messages using a trusted channel before opening attachments.",
                     "Thibitisha ujumbe usiotarajiwa kupitia njia unayoamini kabla ya kufungua viambatisho."),
                    ("Academic writing", "What is the main purpose of citing a source?",
                     "Lengo kuu la kutaja chanzo ni nini?",
                     json.dumps(["Make the paper longer", "Credit ideas and help readers verify evidence", "Avoid explaining your argument", "Replace your conclusion"]),
                     json.dumps(["Kuongeza urefu wa makala", "Kutoa sifa kwa mawazo na kusaidia wasomaji kuthibitisha ushahidi", "Kuepuka kueleza hoja yako", "Kubadilisha hitimisho lako"]),
                     1, "Citations acknowledge others' work and let readers trace your evidence.",
                     "Marejeo hutambua kazi ya wengine na kuwawezesha wasomaji kufuatilia ushahidi wako."),
                ],
            )
        import json
        supplemental_quizzes = [
            ("Study skills", "What does active recall ask you to do?",
             "Kujikumbusha kwa bidii kunakutaka ufanye nini?",
             ["Retrieve ideas from memory before checking notes", "Copy a chapter repeatedly", "Read only highlighted text", "Study with several screens open"],
             ["Kutoa mawazo akilini kabla ya kuangalia maelezo", "Kunakili sura mara kwa mara", "Kusoma maandishi yaliyopigiwa mstari pekee", "Kusoma huku skrini nyingi zikiwa wazi"],
             0, "Active recall strengthens learning by making you retrieve information from memory.",
             "Kujikumbusha kwa bidii huimarisha kujifunza kwa kutoa taarifa kutoka kwenye kumbukumbu."),
            ("Study skills", "Why is it useful to mix related problem types during practice?",
             "Kwa nini ni muhimu kuchanganya aina za maswali zinazohusiana unapofanya mazoezi?",
             ["It helps you choose which method fits each problem", "It removes the need to review", "It guarantees every answer is correct", "It makes practice shorter automatically"],
             ["Hukusaidia kuchagua mbinu inayofaa kwa kila tatizo", "Huondoa hitaji la kurudia", "Huhakikisha kila jibu ni sahihi", "Hufupisha mazoezi moja kwa moja"],
             0, "Interleaving gives practice identifying the right strategy, not just repeating one pattern.",
             "Kuchanganya mazoezi hukusaidia kutambua mkakati unaofaa badala ya kurudia muundo mmoja."),
            ("Research", "What is a primary source for a study of a historical event?",
             "Chanzo cha msingi ni nini katika utafiti wa tukio la kihistoria?",
             ["A diary written by a witness at the time", "A recent textbook summary", "An encyclopedia entry", "A review of several books"],
             ["Shajara iliyoandikwa na shahidi wakati huo", "Muhtasari wa hivi karibuni wa kitabu cha kiada", "Makala ya ensaiklopidia", "Mapitio ya vitabu kadhaa"],
             0, "A primary source is direct evidence from the period or event being studied.",
             "Chanzo cha msingi ni ushahidi wa moja kwa moja kutoka kipindi au tukio linalochunguzwa."),
            ("Research", "What does the Boolean operator AND usually do in a database search?",
             "Kihusishi cha Boolean AND kwa kawaida hufanya nini katika utafutaji wa hifadhidata?",
             ["Returns results containing both search concepts", "Removes every result", "Searches only for synonyms", "Sorts results by date"],
             ["Hurejesha matokeo yenye dhana zote mbili za utafutaji", "Huondoa matokeo yote", "Hutafuta visawe pekee", "Hupanga matokeo kwa tarehe"],
             0, "AND narrows a search by requiring both concepts to appear.",
             "AND hupunguza matokeo kwa kuhitaji dhana zote mbili ziwepo."),
            ("Research", "Which detail is important when evaluating an academic source?",
             "Ni jambo gani muhimu unapotathmini chanzo cha kitaaluma?",
             ["Its author, evidence, publication date, and relevance", "The number of colors on its website", "Whether its title is very long", "How many advertisements appear beside it"],
             ["Mwandishi, ushahidi, tarehe ya uchapishaji na umuhimu wake", "Idadi ya rangi kwenye tovuti yake", "Ikiwa kichwa chake ni kirefu sana", "Idadi ya matangazo pembeni yake"],
             0, "Assess authorship, evidence, date, and relevance rather than relying on appearance.",
             "Tathmini mwandishi, ushahidi, tarehe na umuhimu badala ya kutegemea mwonekano."),
            ("Academic writing", "When should you cite an idea that you have paraphrased?",
             "Unapaswa kurejelea lini wazo ulilolieleza upya kwa maneno yako?",
             ["Whenever the idea came from a source", "Only when you copy the exact wording", "Only in the introduction", "Citations are never needed for paraphrases"],
             ["Kila mara wazo lilipotoka kwenye chanzo", "Unaponakili maneno halisi pekee", "Katika utangulizi pekee", "Marejeo hayahitajiki kwa maelezo upya"],
             0, "Paraphrasing changes wording, not ownership; cite the original source.",
             "Kueleza upya hubadilisha maneno, si umiliki wa wazo; taja chanzo cha awali."),
            ("Digital literacy", "What is the safest way to verify an unexpected university payment request?",
             "Njia salama zaidi ya kuthibitisha ombi lisilotarajiwa la malipo ya chuo ni ipi?",
             ["Contact the university using details from its official website", "Reply with your password", "Use the phone number in the suspicious message", "Pay immediately to avoid a warning"],
             ["Wasiliana na chuo kwa maelezo kutoka tovuti yake rasmi", "Jibu kwa kutuma nenosiri lako", "Tumia nambari iliyo kwenye ujumbe unaotia shaka", "Lipa mara moja ili kuepuka onyo"],
             0, "Verify payment requests through a trusted official channel before acting.",
             "Thibitisha maombi ya malipo kupitia njia rasmi unayoamini kabla ya kuchukua hatua."),
            ("Academic writing", "What is the purpose of a thesis statement?",
             "Madhumuni ya kauli kuu ya tasnifu ni nini?",
             ["State the central claim or argument of the work", "List every source used", "Replace all supporting evidence", "Summarize each paragraph separately"],
             ["Kueleza dai au hoja kuu ya kazi", "Kuorodhesha kila chanzo kilichotumika", "Kubadilisha ushahidi wote wa kuunga mkono", "Kufupisha kila aya kando"],
             0, "A thesis statement gives readers the central argument that the work will support.",
             "Kauli ya tasnifu huwapa wasomaji hoja kuu ambayo kazi itaunga mkono."),
        ]
        for item in supplemental_quizzes:
            subject, q_en, q_sw, choices_en, choices_sw, answer, exp_en, exp_sw = item
            exists = cur.execute(
                "SELECT 1 FROM study_quizzes WHERE question_en = ?", (q_en,)
            ).fetchone()
            if not exists:
                cur.execute(
                    "INSERT INTO study_quizzes "
                    "(subject, question_en, question_sw, choices_en, choices_sw, answer_index, "
                    "explanation_en, explanation_sw) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (subject, q_en, q_sw, json.dumps(choices_en, ensure_ascii=False),
                     json.dumps(choices_sw, ensure_ascii=False), answer, exp_en, exp_sw),
                )
        con.commit()

