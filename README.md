# סוכן בריאות ואימונים אישי (Garmin)

דשבורד Streamlit שמתחבר לחשבון ה-Garmin Connect שלך, מושך שינה / HRV / Body Battery /
סטרס / דופק מנוחה / Training Readiness / אימונים, ונותן **המלצת אימון יומית** +
שאלות חופשיות ("כדאי לי לרוץ היום?"). עלות הרצה: **₪0**.

נבנה ונבדק מול Garmin **Instinct 3 AMOLED** (עובד עם כל שעון שמסנכרן ל-Garmin Connect).

---

## מה זה כן ומה זה לא

* **כן:** נתונים "כמעט בזמן אמת" — טריים כמו הסנכרון האחרון בין השעון לטלפון (בדרך כלל דקות עד שעה).
* **לא:** דופק חי תוך כדי אימון. זה דורש אפליקציית Connect IQ על השעון — מתוכנן לשלב 2.
* שכבת הנתונים משתמשת ב-[`garminconnect`](https://github.com/cyberjunky/python-garminconnect),
  ספרייה **לא רשמית**. השימוש הוא לחשבון האישי שלך בלבד. אם תרצה API רשמי,
  צריך אישור מ-Garmin Connect Developer Program — ואז מחליפים רק את `garmin_client.py`.

---

## התקנה והרצה (מקומי)

```bash
cd "garmin-health-agent"
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt

copy .streamlit\secrets.toml.example .streamlit\secrets.toml
#  ← ערוך את secrets.toml: אימייל+סיסמה של Garmin, ואופציונלית מפתח Gemini חינמי

streamlit run app.py
```

בהתחברות הראשונה ייתכן שתתבקש קוד **MFA** (אימות דו־שלבי) — הזן אותו בשדה שיופיע.
לאחר מכן אסימון הגישה נשמר מקומית ב-`~/.garmin-health-agent/tokens` ואין צורך להתחבר שוב.

---

## משיכת הנתונים לתיקייה מקומית (`sync.py`)

מוריד את נתוני ה-Garmin שלך (אימונים + התאוששות) לקבצים בתיקיית `data/` על המחשב,
כדי שאפשר לקרוא אותם בכל רגע — גם בלי להריץ את הדשבורד. **קריאה בלבד** — שום דבר
לא נכתב בחזרה לחשבון Garmin.

```bash
sync.bat                 # 30 ימי התאוששות + 30 אימונים אחרונים
sync.bat --days 90       # היסטוריה ארוכה יותר
sync.bat --full          # לרענן גם ימים שכבר נשמרו
```

מבנה התיקייה:

| קובץ | תוכן |
|------|------|
| `data/latest.json` | תמונת מצב היום + 7 ימים אחרונים + אימונים אחרונים — **התחל כאן** |
| `data/wellness.csv` | שורה ליום: שינה, HRV, דופק מנוחה, Body Battery, סטרס, SpO2, מוכנוּת, עומס |
| `data/activities.csv` | שורה לאימון |
| `data/wellness/<תאריך>.json`, `data/activities/<id>.json` | פירוט מלא |

התיקייה `data/` ב-`.gitignore` — הנתונים האישיים לא עולים ל-git.

### סנכרון אוטומטי יומי (Windows)

```powershell
schtasks /create /tn "GarminHealthSync" /tr "'C:\Users\shust\OneDrive\שולחן העבודה\garmin-health-agent\sync.bat' --days 3" /sc daily /st 07:00 /f
```

מריץ את הסנכרון כל בוקר ב-07:00. אחרי ההתחברות הראשונה האסימון תקף לחודשים, אז זה
רץ לבד. אם פעם ייכשל — הרץ `sync.bat` ידנית פעם אחת כדי לחדש התחברות.

### הצפנה (AES-256)

הפרויקט יושב בתוך OneDrive, כלומר `data/` מסתנכרן לענן. כדי שהעותק הזה יהיה חסר
ערך בלי המפתח:

```bash
sync.bat --encrypt
```

מפעיל **AES-256-GCM**. בהרצה הראשונה נוצר מפתח אקראי חזק ונשמר ב-
`~/.garmin-health-agent/data-key` — **מחוץ** לתיקיית OneDrive, כך שהעותק המסונכרן
לא כולל אותו. מרגע זה כל הקבצים נשמרים כ-`<שם>.enc` וכל סנכרון (כולל המתוזמן)
מצפין אוטומטית.

**גיבוי המפתח:** העתק את `~/.garmin-health-agent/data-key` למקום בטוח. בלעדיו אי
אפשר לשחזר את הנתונים.

קריאת הנתונים המוצפנים:

```bash
python datatool.py status              # האם ההצפנה פעילה + מיקום המפתח
python datatool.py list                # רשימת הקבצים
python datatool.py cat latest.json     # הדפסת קובץ מפוענח
python datatool.py export ./plain      # פענוח הכל לתיקייה זמנית
```

### מפתח Gemini חינמי (מומלץ)

1. היכנס ל-<https://aistudio.google.com/apikey> וצור מפתח.
2. הדבק אותו ב-`secrets.toml` תחת `GEMINI_API_KEY`.
3. בלי מפתח — האפליקציה עדיין עובדת במצב `rules` (ניתוח מבוסס כללים, בלי טקסט חופשי).

---

## אבטחה ופרטיות

* האפליקציה **מתחברת לחשבון Garmin שלך** — הרץ אותה פרטית בלבד.
  אל תפרוס אותה בכתובת ציבורית עם ה-secrets בפנים.
* `secrets.toml` ותיקיית האסימונים נמצאים ב-`.gitignore` ולא נכנסים ל-git.
* לפריסה פרטית ב-Streamlit Community Cloud: הגדר את ה-repo כ-Private והזן את הערכים
  במסך ה-Secrets של Streamlit (לא בקוד).

---

## מבנה

| קובץ | תפקיד |
|------|-------|
| `app.py` | ממשק Streamlit |
| `garmin_client.py` | שכבת נתונים — כל מה שקשור ל-Garmin מבודד כאן |
| `analysis.py` | לוגיקת כללים טהורה (מוכנוּת, מגמות, חוב שינה, עומס) — נבדקת ב-pytest |
| `ai_agent.py` | מנוע AI מתחלף: `rules` / `gemini` / `claude` / `openai` / `ollama` |
| `config.py` | קריאת הגדרות מ-secrets / משתני סביבה |
| `tests/` | `pytest` |

```bash
pytest -q
```

---

## החלפת מנוע AI

בקובץ `secrets.toml`, `AI_PROVIDER`:

| ערך | דרישה | עלות |
|-----|--------|------|
| `rules` | — | חינם, בלי טקסט חופשי |
| `gemini` | `GEMINI_API_KEY` | חינם (מדרגה חינמית) |
| `claude` | `ANTHROPIC_API_KEY` + `pip install anthropic` | ~$2/חודש |
| `openai` | `OPENAI_API_KEY` + `pip install openai` | ~$1/חודש |
| `ollama` | Ollama מותקן ורץ מקומית | חינם, צריך חומרה |

---

## מפת דרכים

* **שלב 2 — דופק חי:** data field ב-Connect IQ (Monkey C) ששולח דופק/קצב לשרת קטן תוך אימון.
* התראות יזומות (חוב שינה / HRV יורד כמה ימים ברצף) דרך Telegram bot.
* מעבר ל-Garmin Health API הרשמי אם/כשיאושר.
