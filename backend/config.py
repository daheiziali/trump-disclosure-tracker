from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "disclosures.sqlite3"

USER_AGENT = "CabinetDisclosureMVP/0.1 contact: research@example.com"

SEC_COMPANIES = {
    "TMTG_DJT": "0001849635",
}

OGE_SEARCH_URL = (
    "https://www.oge.gov/web/oge.nsf/"
    "Officials%20Individual%20Disclosures%20Search%20Collection?OpenForm="
)

OGE_TARGETS = [
    "Trump",
    "Vance",
    "Bessent",
    "Lutnick",
    "Rubio",
    "Kennedy",
    "Hegseth",
    "Bondi",
    "Noem",
    "Burgum",
    "Wright",
    "Duffy",
]

