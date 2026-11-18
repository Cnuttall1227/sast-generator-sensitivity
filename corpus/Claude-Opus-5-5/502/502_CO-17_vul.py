import os
import logging
from datetime import date

from bottle import Bottle, request, response, run, template

COOKIE_SECRET = os.environ.get("RECIPE_COOKIE_SECRET", "recipes-cookie-secret")
PREFS_COOKIE = "prefs"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
DIETS = ("none", "vegetarian", "vegan", "gluten-free", "dairy-free")
UNITS = ("metric", "us")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("recipe-site")

app = Bottle()

RECIPES = [
    {"id": 1, "title": "Weeknight dal", "diets": {"vegetarian", "vegan", "gluten-free", "dairy-free"},
     "minutes": 35, "grams_flour": 0},
    {"id": 2, "title": "Buttermilk pancakes", "diets": {"vegetarian"}, "minutes": 25, "grams_flour": 190},
    {"id": 3, "title": "Sheet-pan chicken and potatoes", "diets": {"gluten-free", "dairy-free"},
     "minutes": 50, "grams_flour": 0},
    {"id": 4, "title": "Mushroom risotto", "diets": {"vegetarian", "gluten-free"}, "minutes": 45, "grams_flour": 0},
    {"id": 5, "title": "Olive oil focaccia", "diets": {"vegetarian", "vegan", "dairy-free"},
     "minutes": 150, "grams_flour": 500},
]

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Recipes</title>
<style>body{font-family:sans-serif;max-width:40rem;margin:2rem auto}li{margin:.4rem 0}</style></head>
<body><h1>Recipes for {{diet if diet != 'none' else 'everyone'}}</h1>
<form method="post" action="/preferences">
<label>Diet <select name="diet">% for d in diets:
<option value="{{d}}" {{'selected' if d == diet else ''}}>{{d}}</option>% end
</select></label>
<label>Units <select name="units">% for u in units:
<option value="{{u}}" {{'selected' if u == unit else ''}}>{{u}}</option>% end
</select></label>
<label>Max minutes <input name="max_minutes" type="number" min="5" max="600" value="{{max_minutes}}"></label>
<button>Save</button></form>
<ul>% for r in recipes:
<li><strong>{{r['title']}}</strong> – {{r['minutes']}} min{{' · ' + r['flour'] if r['flour'] else ''}}</li>% end
</ul><p><small>{{today}}</small></p></body></html>"""


def default_preferences():
    return {"diet": "none", "units": "metric", "max_minutes": 90}


def load_preferences():
    stored = request.get_cookie(PREFS_COOKIE, secret=COOKIE_SECRET)
    if not isinstance(stored, dict):
        return default_preferences()
    prefs = default_preferences()
    if stored.get("diet") in DIETS:
        prefs["diet"] = stored["diet"]
    if stored.get("units") in UNITS:
        prefs["units"] = stored["units"]
    if isinstance(stored.get("max_minutes"), int) and 5 <= stored["max_minutes"] <= 600:
        prefs["max_minutes"] = stored["max_minutes"]
    return prefs


def save_preferences(prefs):
    response.set_cookie(PREFS_COOKIE, prefs, secret=COOKIE_SECRET, max_age=COOKIE_MAX_AGE,
                        httponly=True, samesite="lax", path="/")


def flour_label(grams, units):
    if not grams:
        return ""
    return f"{grams} g flour" if units == "metric" else f"{grams / 125:.1f} cups flour"


def matching_recipes(prefs):
    results = []
    for recipe in RECIPES:
        if prefs["diet"] != "none" and prefs["diet"] not in recipe["diets"]:
            continue
        if recipe["minutes"] > prefs["max_minutes"]:
            continue
        results.append({**recipe, "flour": flour_label(recipe["grams_flour"], prefs["units"])})
    return results


@app.get("/")
def home():
    prefs = load_preferences()
    return template(PAGE, diet=prefs["diet"], unit=prefs["units"], max_minutes=prefs["max_minutes"],
                    diets=DIETS, units=UNITS, recipes=matching_recipes(prefs), today=date.today().isoformat())


@app.post("/preferences")
def update_preferences():
    prefs = load_preferences()
    diet = request.forms.getunicode("diet", "")
    units = request.forms.getunicode("units", "")
    if diet in DIETS:
        prefs["diet"] = diet
    if units in UNITS:
        prefs["units"] = units
    try:
        prefs["max_minutes"] = max(5, min(600, int(request.forms.get("max_minutes", prefs["max_minutes"]))))
    except ValueError:
        pass
    save_preferences(prefs)
    log.info("Preferences updated: %s", prefs)
    response.status = 303
    response.set_header("Location", "/")
    return ""


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))