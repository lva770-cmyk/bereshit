# בראשית · מסחר חי (מדומה)

מסך מסחר לסוללה של **100 MW / 400 MWh** על מחירי ה-Day-Ahead האמיתיים של הבורסה ההונגרית (HUPX).
הקנייה והמכירה מדומות, ושום פקודה לא נשלחת לבורסה. המחירים, השעות והחישובים אמיתיים.

## איך זה רץ לבד
- `.github/workflows/update.yml` רץ כל 30 דקות ב-GitHub Actions: `python engine.py update`.
- המנוע פונה **ישירות** ל-API של Energy-Charts (Fraunhofer ISE). כל יום נקרא פעמיים ונקלט רק אם שתי הקריאות זהות. אם יום עוד לא פורסם, הוא פשוט מדלג, ואף נתון לא מומצא.
- לפני 12:00 CET (13:00 שעון ישראל) המנוע נועל לוח טעינה ופריקה למחר. לוח ננעל פעם אחת בלבד, ואי אפשר לשנות אותו בדיעבד.
- GitHub Pages מגיש את `index.html`. הדף מושך את `data.json` כל כמה דקות, ורץ לפי השעון גם כשאין רשת.

## הפעלה (פעם אחת)
1. Settings → Pages → Source: *Deploy from a branch* → Branch: `main` / `(root)` → Save.
2. Settings → Actions → General → Workflow permissions: *Read and write* → Save.
3. Actions → "בראשית – עדכון נתונים" → *Run workflow*, כדי לבדוק שהכול עובד.

## קבצים
| קובץ | תפקיד |
|---|---|
| `engine.py` | משיכת מחירים, אימות, תחזית (blend), תכנון ליניארי (HiGHS), התחשבנות |
| `data.json` | מצב המערכת: מחירים, לוחות נעולים, תוצאות וחותמות אימות |
| `index.html` | המסך החי |

נתונים: Energy-Charts / Fraunhofer ISE, ברישיון CC BY 4.0.

## research/
חבילת המחקר המלאה: תחזיות naive / blend / ridge, בדיקה לאחור על 361 ימים, בדיקות יחידה, ומסחר צללים מקומי (`python -m bereshit.shadow`).
