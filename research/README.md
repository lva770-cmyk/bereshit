# בראשית (Bereshit)

מנוע **מסחר צללים** לסוללה בקנה מידה של רשת: ארביטראז' ביום-המחרת (Day-Ahead), כש-MW מסוימים שמורים לשירותי איזון.
המערכת מחליטה, מתעדת ומודדת – **היא לא שולחת פקודות לשום בורסה.**

## מה יש כאן
| מודול | תפקיד |
|---|---|
| `bereshit/data.py` | מחירי Day-Ahead וייצור/צריכה מ-Energy-Charts (Fraunhofer ISE) ברשת של 15 דקות |
| `bereshit/forecast.py` | תחזית מחירים ליום D שנעשית ב-D-1 לפני סגירת השער: `naive`, `blend`, `ridge` |
| `bereshit/optimizer.py` | תכנון ליניארי (HiGHS) ללוח טעינה/פריקה: הספק, קיבולת, יעילות 88%, תקרת מחזורים, בלאי |
| `bereshit/backtest.py` | בדיקה לאחור ללא הצצה לעתיד: תחזית → לוח קבוע → התחשבנות במחירים בפועל |
| `bereshit/shadow.py` | הפעלה יומית: `plan` (לפני 12:00 CET), `settle` (אחרי פרסום התוצאות), `report` |
| `deploy/` | הפעלה אוטומטית ב-Mac (launchd) |

## התקנה והרצה
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q tests                           # 5 בדיקות, כולל התאמה לנתוני הונגריה אמיתיים
python -m bereshit.backtest --zone HU --hours 4 --forecaster blend
python -m bereshit.shadow plan                      # לוח של מחר, נשמר ב-shadow_log/ ואי אפשר לדרוס אותו
python -m bereshit.shadow settle                    # התחשבנות אחרי שהמחירים יוצאים
python -m bereshit.shadow report
```

## תוצאות הבדיקה לאחור – הונגריה, 1.10.2025–28.9.2026 (361 ימים)
אחוז מהתקרה התיאורטית (ידיעה מושלמת מראש) שהושג בפועל, רק עם מידע שהיה זמין ב-D-1:

| משך | naive | blend | ridge | ridge + סף 10 € |
|---|---|---|---|---|
| 1h | 74.6% | **80.2%** | 76.1% | 76.0% |
| 2h | 79.9% | **84.8%** | 82.1% | 81.6% |
| 4h | 86.5% | **90.0%** | 88.2% | 87.2% |

פירוט: `results/hu_backtest_2025-10-01_2026-09-28.json`.

## מגבלות ידועות
- לוח קבוע (price-taker). בפועל מגישים עקומות מחיר-כמות, וסוללה של 80–100 MW יכולה להזיז מחיר בהונגריה – לא נמדד.
- אין כאן מסחר תוך-יומי ואין סימולציה של aFRR/FCR (אין נתונים ציבוריים להונגריה).
- `ridge_fund` (עם תחזית סולארית/רוח/צריכה) מוכן בקוד אך דורש מקור תחזיות אמיתי.
- ביצוע אמיתי דורש חברות בבורסה או Route-to-Market, BRP, והסמכת MAVIR – מחוץ לתוכנה.

Data: Energy-Charts / Fraunhofer ISE (CC BY 4.0).
