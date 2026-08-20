import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from config import DB_PATH


CONCEPTS = {
    "通信服务": [
        "VERIZON",
        "CHARTER COMMUNICATIONS",
        "COMCAST",
        "AT&T",
        "T-MOBILE",
        "TELECOM",
    ],
    "医疗器械": [
        "STRYKER",
        "MEDTRONIC",
        "BOSTON SCIENTIFIC",
        "INTUITIVE SURGICAL",
        "EDWARDS LIFESCIENCES",
        "DANAHER",
    ],
    "生命科学工具": [
        "THERMO FISHER",
        "AGILENT",
        "IDEXX",
        "ILLUMINA",
        "Mettler",
        "WATERS CORP",
    ],
    "生物医药": [
        "ALNYLAM",
        "AMGEN",
        "GILEAD",
        "BIOGEN",
        "MODERNA",
        "REGENERON",
        "VERTEX",
        "ELI LILLY",
        "MERCK",
        "PFIZER",
        "ABBVIE",
    ],
    "航空航天": [
        "TRANSDIGM",
        "BOEING",
        "RTX",
        "LOCKHEED",
        "NORTHROP",
        "GENERAL DYNAMICS",
        "HEICO",
        "CURTISS-WRIGHT",
    ],
    "广告科技/软件": [
        "CCC INTELLIGENT",
        "THE TRADE DESK",
        "ADOBE",
        "SALESFORCE",
        "SERVICENOW",
        "SNOWFLAKE",
        "DATADOG",
        "CROWDSTRIKE",
        "ATLASSIAN",
    ],
    "房地产/REIT": [
        "ALEXANDRIA REAL ESTATE",
        "REALTY INCOME",
        "PROLOGIS",
        "EQUINIX",
        "PUBLIC STORAGE",
        "REIT",
    ],
    "消费零售": [
        "ALBERTSONS",
        "COSTCO",
        "WALMART",
        "TARGET",
        "HOME DEPOT",
        "LOWE",
        "KROGER",
        "MCDONALD",
        "STARBUCKS",
    ],
    "咨询/IT服务": [
        "ACCENTURE",
        "GARTNER",
        "FISERV",
        "BROOKS AUTOMATION",
        "COGNIZANT",
        "IBM",
    ],
    "AI/半导体": [
        "NVIDIA",
        "BROADCOM",
        "ADVANCED MICRO DEVICES",
        "ADVANCED MICRO",
        "AMD",
        "DELL",
        "SUPER MICRO",
        "PALANTIR",
        "ORACLE",
        "MICROSOFT",
        "TEXAS INSTRUMENTS",
        "CADENCE",
        "SYNOPSYS",
        "APPLIED MATERIALS",
        "LAM RESEARCH",
        "KLA",
        "MICRON",
        "QUALCOMM",
        "INTEL",
    ],
    "大型科技": ["APPLE", "MICROSOFT", "AMAZON", "META", "ALPHABET", "GOOGLE", "NETFLIX", "TESLA"],
    "国防/安全": [
        "AXON",
        "MOTOROLA SOLUTIONS",
        "PALANTIR",
    ],
    "能源/电力": [
        "EXXON",
        "CHEVRON",
        "OCCIDENTAL",
        "CONOCOPHILLIPS",
        "VISTRA",
        "CONSTELLATION ENERGY",
        "GE VERNOVA",
        "EATON",
        "TRANE",
        "BLACK BELT ENERGY",
        "GAS",
    ],
    "金融服务": [
        "JPMORGAN",
        "GOLDMAN",
        "BANK OF AMERICA",
        "MORGAN STANLEY",
        "BLACKSTONE",
        "APOLLO",
        "INTERCONTINENTAL",
        "CME GROUP",
        "COINBASE",
        "ROBINHOOD",
        "MICROSTRATEGY",
    ],
    "制造业/基建": ["NUCOR", "STEEL DYNAMICS", "CATERPILLAR", "DEERE", "UNITED RENTALS", "3M", "ILLINOIS TOOL"],
    "市政债/公共项目": [" CNTY ", " COUNTY ", " ST ", " STATE ", " AUTH ", " REV ", " GO ", " MUD ", " SCH ", " UNIV ", " HSG "],
    "Trump 直接相关": ["TRUMP MEDIA", "TMTG", "DJT"],
}


OCR_TAIL_RE = re.compile(
    r"\s+\b(IPurchaso|lourchase|lourchaso|ourchase|ourchaso|nurchasc|Purchasc|Purchaso|purchase|sale|salo|purc|pur|our|lour)\b$",
    re.I,
)

COMPANY_TICKERS = {
    "CCC INTELLIGENT": "CCC",
    "3M": "MMM",
    "VERIZON COMMUNICATIONS": "VZ",
    "TRANSDIGM GROUP": "TDG",
    "THERMO FISHER SCIENTIFIC": "TMO",
    "THE TRADE DESK": "TTD",
    "STRYKER": "SYK",
    "CHARTER COMMUNICATIONS": "CHTR",
    "ALNYLAM PHARMACEUTICALS": "ALNY",
    "ALEXANDRIA REAL ESTATE": "ARE",
    "ALBERTSONS": "ACI",
    "ALBERTSONS CO SHS": "ACI",
    "ALBERTSONS COMPANIES": "ACI",
    "ADVANCED MICRO": "AMD",
    "AMD": "AMD",
    "ACCENTURE": "ACN",
    "APPLIED MATLS": "AMAT",
    "APPLIED MATERIALS": "AMAT",
    "AMAZON": "AMZN",
    "TESLA": "TSLA",
    "NVIDIA": "NVDA",
    "ALPHABET INC CLASS C": "GOOG",
    "ALPHABET INC CL C": "GOOG",
    "ALPHABET INC CL-C": "GOOG",
    "ALPHABET INC CLASS A": "GOOGL",
    "ALPHABET INC CL A": "GOOGL",
    "ALPHABET INC CL-A": "GOOGL",
    "ALPHABET": "GOOGL",
    "APPLE": "AAPL",
    "MICROSOFT": "MSFT",
    "INTEL": "INTC",
    "RTX CORP": "RTX",
    "RTX CORPORATION": "RTX",
    "H2O AMERICA": "HTO",
    "AES CORP VA": "AES",
    "AES CORP": "AES",
    "SANDISK CORP DE": "SNDK",
    "SANDISK": "SNDK",
    "LENNOX INTERNATIONAL": "LII",
    "AXOS FINL": "AX",
    "AXOS FINANCIAL": "AX",
    "COMFORT SYS USA": "FIX",
    "COMFORT SYSTEMS USA": "FIX",
    "CORCEPT THERAPEUTICS": "CORT",
    "TERADATA": "TDC",
    "MONOLITHIC POWER SYSTEMS": "MPWR",
    "WELLTOWER": "WELL",
    "RADNET": "RDNT",
    "LINCOLN NATL": "LNC",
    "LINCOLN NATIONAL": "LNC",
    "WAYSTAR": "WAY",
    "SKYWEST": "SKYW",
    "COINBASE GLOBAL": "COIN",
    "ENPRO": "NPO",
    "FB FINL": "FBK",
    "FB FINANCIAL": "FBK",
    "ESSENTIAL UTILS": "WTRG",
    "ESSENTIAL UTILITIES": "WTRG",
    "IDEXX LABORATORIES": "IDXX",
    "ALKERMES": "ALKS",
    "CORE NAT RES": "CNR",
    "CORE NATURAL RESOURCES": "CNR",
    "PACKAGING CORP AMER": "PKG",
    "PACKAGING CORPORATION OF AMERICA": "PKG",
    "INTERCONTINENTALEXCHANGE": "ICE",
    "INTERCONTINENTAL EXCHANGE": "ICE",
    "WAL MART STORES": "WMT",
    "WALMART": "WMT",
    "XYLEM INC NY": "XYL",
    "XYLEM": "XYL",
    "SAFETY INS": "SAFT",
    "SAFETY INSURANCE": "SAFT",
    "GLOBAL PMTS": "GPN",
    "GLOBAL PAYMENTS": "GPN",
    "WILLIS TOWERS WATSON": "WTW",
    "PERDOCEO ED": "PRDO",
    "PERDOCEO EDUCATION": "PRDO",
    "HARTFORD INS": "HIG",
    "HARTFORD INSURANCE": "HIG",
    "GOOSEHEAD INS": "GSHD",
    "GOOSEHEAD INSURANCE": "GSHD",
    "BANC CALIF": "BANC",
    "BANC OF CALIFORNIA": "BANC",
    "BLACKSTONE MTG TR": "BXMT",
    "BLACKSTONE MORTGAGE TRUST": "BXMT",
    "UNITED DOMINION REALTY TRUST": "UDR",
    "UDR": "UDR",
    "SEACOAST BKG CORP FLA": "SBCF",
    "SEACOAST BANKING": "SBCF",
    "COMSTOCK RES": "CRK",
    "COMSTOCK RESOURCES": "CRK",
    "CSG SYS INTL": "CSGS",
    "CSG SYSTEMS INTERNATIONAL": "CSGS",
    "V.F. CORP": "VFC",
    "VF CORP": "VFC",
    "ALEXANDER BALDWIN": "ALEX",
    "ALEXANDER & BALDWIN": "ALEX",
    "ADTALEM GLOBAL ED": "ATGE",
    "ADTALEM GLOBAL EDUCATION": "ATGE",
    "AMERICAN WOODMARK": "AMWD",
    "SELECT MED HLDGS": "SEM",
    "SELECT MEDICAL HOLDINGS": "SEM",
    "CARTERS": "CRI",
    "CARTER'S": "CRI",
    "SAUL CTRS": "BFS",
    "SAUL CENTERS": "BFS",
    "MISTER CAR WASH": "MCW",
    "SHIFT4 PMTS": "FOUR",
    "SHIFT4 PAYMENTS": "FOUR",
    "STERIS": "STE",
    "FORTIVE": "FTV",
    "TEGNA": "TGNA",
    "VERITEX HLDGS": "VBTX",
    "VERITEX HOLDINGS": "VBTX",
    "CENTURY CMNTYS": "CCS",
    "CENTURY COMMUNITIES": "CCS",
    "AVANOS MED": "AVNS",
    "AVANOS MEDICAL": "AVNS",
    "MR COOPER": "COOP",
    "AMENTUM HLDGS": "AMTM",
    "AMENTUM HOLDINGS": "AMTM",
    "ITRON": "ITRI",
    "GOLDEN ENTMT": "GDEN",
    "GOLDEN ENTERTAINMENT": "GDEN",
    "VEECO INSTRS": "VECO",
    "VEECO INSTRUMENTS": "VECO",
    "ARES MGMT": "ARES",
    "ARES MANAGEMENT": "ARES",
    "PNC BANK": "PNC",
    "PNC FINANCIAL": "PNC",
    "NEWMONT MINING": "NEM",
    "GMS INC": "GMS",
    "STELLAR BANCORP": "STEL",
    "KAISER ALUM": "KALU",
    "KAISER ALUMINUM": "KALU",
    "ALLEGION PUBLIC LIMITED COMPANY": "ALLE",
    "ALLEGION": "ALLE",
    "KENNEDY WILSON HLDGS": "KW",
    "KENNEDY-WILSON HLDGS": "KW",
    "KENNEDY WILSON HOLDINGS": "KW",
    "GREENBRIER COS": "GBX",
    "GREENBRIER COMPANIES": "GBX",
    "COHERENT": "COHR",
    "BOOKING HLDGS": "BKNG",
    "BOOKING HOLDINGS": "BKNG",
    "IAC INC": "PPLI",
    "ARMADA HOFFLER PPTYS": "AHRT",
    "ARMADA HOFFLER PROPERTIES": "AHRT",
    "BLACKROCK LARGE CAP FOCUS GROWTH FUND": "MAFOX",
    "NEWMONT": "NEM",
    "MASTEC": "MTZ",
    "NORWEGIAN CRUISE": "NCLH",
    "PHILIP MORRIS": "PM",
    "MCDONALDS": "MCD",
    "MCDONALD": "MCD",
    "MARTIN MARIETTA": "MLM",
    "KURA SUSHI": "KRUS",
    "TRUIST": "TFC",
    "BERKSHIRE HATHAWAY CLASS CLASS B": "BRK.B",
    "BERKSHIRE HATHAWAY INC DEL CL B": "BRK.B",
    "BERKSHIRE HATHAWAY INC CL B": "BRK.B",
    "BERKSHIRE HATHAWAY": "BRK.B",
    "COREWEAVE": "CRWV",
    "GENERAL MTRS": "GM",
    "GENERAL MOTORS": "GM",
    "NEWELL RUBBERMAID": "NWL",
    "NEWELL BRANDS": "NWL",
    "GENERAL ELEC": "GE",
    "GE AEROSPACE": "GE",
    "KKR": "KKR",
    "LINDE": "LIN",
    "CME GROUP": "CME",
    "HONEYWELL INTL": "HON",
    "HONEYWELL INTERNATIONAL": "HON",
    "APPLOVIN": "APP",
    "KRATOS DEFENSE": "KTOS",
    "IBM": "IBM",
    "MASTERCARD": "MA",
    "TRANE TECHNOLOGIES": "TT",
    "CSX": "CSX",
    "NVR": "NVR",
    "MEDTRONIC": "MDT",
    "PRO LOGIS": "PLD",
    "PROLOGIS": "PLD",
    "TEXAS INSTRS": "TXN",
    "TEXAS INSTRUMENTS": "TXN",
    "MERIT MED SYS": "MMSI",
    "REPUBLIC SVCS": "RSG",
    "CAPITAL ONE FINL": "COF",
    "CAPITAL ONE FINANCIAL": "COF",
    "WASTE MGMT": "WM",
    "WASTE MANAGEMENT": "WM",
    "MOODYS": "MCO",
    "MOODY'S": "MCO",
    "ILLINOIS TOOL WKS": "ITW",
    "ILLINOIS TOOL WORKS": "ITW",
    "TJX": "TJX",
    "CENCORA": "COR",
    "PROGRESSIVE": "PGR",
    "FACEBOOK": "META",
    "GOLDMAN SACHS GROUP": "GS",
    "PPG": "PPG",
    "GE HEALTHCARE": "GEHC",
    "BLUE OWL CAP": "OBDC",
    "BRINKER INTL": "EAT",
    "BADGER METER": "BMI",
    "MONDELEZ": "MDLZ",
    "APOLLO GLOBAL MANAGEMENT": "APO",
    "ACI WORLDWIDE": "ACIW",
    "CSW INDUSTRIALS": "CSWI",
    "INNOSPEC": "IOSP",
    "PG&E": "PCG",
    "SPS COMM": "SPSC",
    "LAM RESH": "LRCX",
    "LAM RESEARCH": "LRCX",
    "HARTFORD INSURANCE": "HIG",
    "CITIZENS FINL": "CFG",
    "CITIZENS FINANCIAL": "CFG",
    "GATES INDL": "GTES",
    "ABM INDS": "ABM",
    "STRIDE": "LRN",
    "AVALONBAY": "AVB",
    "NATWEST": "NWG",
    "CHARLES SCHWAB": "SCHW",
    "AON": "AON",
    "SL GREEN": "SLG",
    "ARMSTRONG WORLD": "AWI",
    "CAL MAINE": "CALM",
    "WATSCO": "WSO",
    "SANMINA": "SANM",
    "AIR PRODS": "APD",
    "AIR PRODUCTS": "APD",
    "UNITED PARCEL SVC": "UPS",
    "UNITED PARCEL SERVICE": "UPS",
    "CAVCO": "CVCO",
    "CAESARS ENTMT": "CZR",
    "CAESARS ENTERTAINMENT": "CZR",
    "FLUTTER ENTMT": "FLUT",
    "FLUTTER ENTERTAINMENT": "FLUT",
    "DOMINOS PIZZA": "DPZ",
    "DOMINO'S PIZZA": "DPZ",
    "EQT": "EQT",
    "GROUP 1 AUTOMOTIVE": "GPI",
    "BALCHEM": "BCPC",
    "STEPSTONE": "STEP",
    "FOUR CORNERS PPTY": "FCPT",
    "FOUR CORNERS PROPERTY": "FCPT",
    "FEDERAL SIGNAL": "FSS",
    "INSPIRE MED SYS": "INSP",
    "INSPIRE MEDICAL SYSTEMS": "INSP",
    "WSFS FINL": "WSFS",
    "WSFS FINANCIAL": "WSFS",
    "HENRY JACK": "JKHY",
    "JACK HENRY": "JKHY",
    "JBT MAREL": "JBTM",
    "COMMUNITY FINL SYS": "CBU",
    "COMMUNITY FINANCIAL SYSTEM": "CBU",
    "NORTHERN OIL": "NOG",
    "SIX FLAGS ENTMT": "FUN",
    "SIX FLAGS ENTERTAINMENT": "FUN",
    "KONTOOR": "KTB",
    "APOLLO GLOBAL MGMT": "APO",
    "PHILLIPS EDISON": "PECO",
    "LKQ": "LKQ",
    "ARCHROCK": "AROC",
    "VERALTO": "VLTO",
    "FULTON FINL": "FULT",
    "FULTON FINANCIAL": "FULT",
    "LABCORP": "LH",
    "CHAMPION HOMES": "SKY",
    "HIGHWOODS PPTYS": "HIW",
    "HIGHWOODS PROPERTIES": "HIW",
    "INSTALLED BLDG PRODS": "IBP",
    "INSTALLED BUILDING PRODUCTS": "IBP",
    "CORVEL": "CRVL",
    "DIGITALOCEAN": "DOCN",
    "TARGET": "TGT",
    "BOEING": "BA",
    "COSTCO": "COST",
    "NETFLIX": "NFLX",
    "META PLATFORMS": "META",
    "JPMORGAN": "JPM",
    "VISA": "V",
    "WALMART": "WMT",
    "HOME DEPOT": "HD",
    "LOWE": "LOW",
    "ADOBE": "ADBE",
    "SALESFORCE": "CRM",
    "SERVICENOW": "NOW",
    "AXON": "AXON",
    "SYNOPSYS": "SNPS",
    "TEXAS INSTRUMENTS": "TXN",
    "QUALCOMM": "QCOM",
    "MICRON": "MU",
    "APPLIED MATERIALS": "AMAT",
    "LAM RESEARCH": "LRCX",
    "KLA": "KLAC",
    "PALANTIR": "PLTR",
    "ORACLE": "ORCL",
    "BROADCOM": "AVGO",
    "MOTOROLA SOLUTIONS": "MSI",
    "QNITY ELECTRONICS": "Q",
    "JOHNSON CONTROLS INTL": "JCI",
    "JOHNSON CONTROLS INTERNATIONAL": "JCI",
    "Q2 HLDGS": "QTWO",
    "Q2 HOLDINGS": "QTWO",
    "INVESCO LTD": "IVZ",
    "ZOOMINFO TECHNOLOGIES": "GTM",
    "ZOOMINFO": "GTM",
    "VERRA MOBILITY": "VRRM",
    "PHIBRO ANIMAL HEALTH": "PAHC",
    "COGENT COMMUNICATIONS HL": "CCOI",
    "COGENT COMMUNICATIONS HOLDINGS": "CCOI",
    "COHU": "COHU",
    "CLEAR SECURE": "YOU",
    "CITIGROUP": "C",
    "CINEMARK HLDGS": "CNK",
    "CINEMARK HOLDINGS": "CNK",
    "CHESAPEAKE UTILS": "CPK",
    "CHESAPEAKE UTILITIES": "CPK",
    "CERTARA": "CERT",
}

ETF_TICKERS = {
    "ISHARES SILVER SHARES": "SLV",
    "ISHARES U S REGIONAL BANKS": "IAT",
    "ISHARES U.S. REGIONAL BANKS": "IAT",
    "SELECT SECTOR SPDR TRUST STATE STREET FINANCIAL SELECT SECTOR SPDR": "XLF",
    "FINANCIAL SELECT SECTOR SPDR": "XLF",
    "STE STRT FINCL SLCT SECTOR SPDR": "XLF",
    "STATE STREET FINANCIAL SELECT SECTOR SPOR": "XLF",
    "VANGUARD FTSE EUROPE": "VGK",
    "ISHARES SELECT DIVIDEND": "DVY",
    "VANGUARD INDEX FUNDS SMALLCAP GROWTH": "VBK",
    "VANGUARD SMALL CAP GROWTH": "VBK",
    "ISHARES TR MSCI EAFE": "EFA",
    "ISHARES TR MSCL EAFE": "EFA",
    "ISHARES CORE MSCI EAFE": "IEFA",
    "ISHARES TR RUSSELL 2000": "IWM",
    "ISHARES RUSSELL 2000": "IWM",
    "ISHARES TR GLOBAL 100": "IOO",
    "WORLD GOLD TRUST SPDR GOLD MINISHARES": "GLDM",
    "SPDR GOLD MINISHARES": "GLDM",
    "VANGUARD SECTOR INDEX FDS VANGUARD CONSUMER DISCRETIONARY": "VCR",
    "VANGUARD CONSUMER DISCRETIONARY": "VCR",
    "VANGUARD RUSSELL 2000": "VTWO",
    "VANGUARD HIGH DIVIDEND YIELD": "VYM",
    "ISHARES RUSSELL MID CAP": "IWR",
    "VANGUARD INDEX FUNDS VANGUARD GROWTH": "VUG",
    "VANGUARD GROWTH ETF": "VUG",
    "COMMUNICATION SERVICES SELECT SECTOR SPDR": "XLC",
    "STE STRT COMTN SR SLCT SCTR SPDR": "XLC",
    "TECHNOLOGY SELECT SECTOR SPDR": "XLK",
    "STATE STRET TEC SELECT SEC SPDR": "XLK",
    "STATE STREET TECHNOLOGY SELECT SECTOR SPDR": "XLK",
    "ISHARES CORE MSCI INTERNATIONAL DEVELOPED MARKETS": "IDEV",
    "ISHARES CORE MSCI INTRL DVLP MKT": "IDEV",
    "HEALTH CARE SELECT SECTOR SPDR": "XLV",
    "STATE STRT HLTH CRE SLT SEC SPDR": "XLV",
    "STATE STREET HEALTH CARE SELECT SPDR": "XLV",
    "CONSUMER STAPLES SELECT SECTOR SPDR": "XLP",
    "STE SRT CNSR STPLS SLCT SEC SPDR": "XLP",
    "STATE STREET INDUSTRIAL SELECT SECTOR SPDR": "XLI",
    "STATE STRT INDSTL SLCT SPDR": "XLI",
    "STATE STREET INDUSTRIAL DISCRETIONARY SELECT SECTOR SPDR": "XLI",
    "SPDR PORTFOLIO HIGH YIELD BOND": "SPHY",
    "SPDR SERIES TRUST STATE STREET SPDR PORTFOLIO HIGH YIELD BOND": "SPHY",
    "VANGUARD MEGA CAP GROWTH": "MGK",
    "INVESCO SHORT TERM TREASURY": "TBLL",
    "ISHARES CORE S&P 500": "IVV",
    "ISHARES CORE S AND P 500": "IVV",
    "ISHARES GOLD TRUST": "IAU",
    "ISHARES GOLD ETF": "IAU",
    "VANGUARD TOTAL STOCK MARKET INDEX FUND": "VTI",
    "VANGUARD TOTAL STOCK MARKET": "VTI",
    "VANGUARD TOTAL STOCK MKT": "VTI",
    "ISHARES GSCI COMMODITY DYNAMIC ROLL STRATEGY": "COMT",
    "ISHR ETF GSCI CMD DYN STR": "COMT",
    "INVESCO QQQ TRUST": "QQQ",
    "INVSC QQQ TRUST": "QQQ",
    "INVESCO QQQ TR": "QQQ",
    "ISHARES US TREASURY BOND": "GOVT",
    "ISHARES U.S. TREASURY BOND": "GOVT",
    "ISHARES U.S. TREASURY": "GOVT",
    "ISHARES INTERNATIONAL TREASURY BOND": "IGOV",
    "ISHARES INTERNATIONAL TRSRY BND": "IGOV",
    "VANGUARD INDEX FDS VANGUARD MID CAP": "VO",
    "VANGUARD INDEX FDS VANGUARD MID-CAP": "VO",
    "VANGUARD MID CAP": "VO",
    "ISHARES MSCI JAPAN": "EWJ",
    "ISHARES CORE MSCI PACIFIC": "IPAC",
    "ISHARES CURRENCY HEDGED MSCI EUROZONE": "HEZU",
    "ISHARES CRRNCY HDG MSCI EURZN": "HEZU",
    "SPDR S&P GLOBAL NATURAL RESOURCES": "GNR",
    "SPDR S&P GLOBAL NATURAL RESOURCS": "GNR",
    "STATE STREET SPDR S&P GLOBAL NATURAL RESOURCES": "GNR",
    "STATE STREET SPDR S&P GLOBAL NATURAL RESOURCESETF": "GNR",
    "ENERGY SELECT SECTOR SPDR": "XLE",
    "STATE STRET ENRGY SLECT SEC SPDR": "XLE",
    "STATE STREET ENERGY SELECT SECTOR SPDR": "XLE",
    "ISHARES CORE MSCI EMERGING MARKETS": "IEMG",
    "VANGUARD INTERMEDIATE TERM CORPORATE BOND": "VCIT",
    "VANGUARD INTERMEDIATE TERM COR": "VCIT",
    "VANGUARD INTERMEDIATE-TERM CORPORATE BOND": "VCIT",
    "VANGUARD EUROPEAN STOCK INDEX FUND": "VGK",
    "ISHARES MSCI CANADA": "EWC",
    "VANGUARD INTERMEDIATE-TERM TREASURY": "VGIT",
    "VANGUARD TAX-EXEMPT BOND": "VTEB",
    "ISHARES S&P 500 GROWTH": "IVW",
    "ISHARES S AND P 500 GROWTH": "IVW",
    "ISHARES S&P 500 VALUE": "IVE",
    "ISHARES S AND P 500 VALUE": "IVE",
    "VANGUARD S&P 500": "VOO",
    "VANGUARD S AND P 500": "VOO",
    "ISHARES EXPANDED TECH SECTOR": "IGM",
    "ISHARES TRUST ISHARES EXPANDED TECH SECTOR": "IGM",
    "INVESCO S AND P 500 QUALITY": "SPHQ",
    "INVESCO S&P 500 QUALITY": "SPHQ",
    "INVESCO EXCHANGE TRADED FUND TRUST INVESCO S&P 500 QUALITY": "SPHQ",
    "SPDR SERIES TRUST STATE STREET SPDR PORTFOLIO S&P 500": "SPYM",
    "STATE STREET SPDR PORTFOLIO S&P 500": "SPYM",
    "SPDR PORTFOLIO S&P 500": "SPYM",
    "SPDR S&P 500 ETF": "SPY",
    "SPDR S AND P 500 ETF": "SPY",
    "SPDR S&P 500 ETF TRUST": "SPY",
    "STATE STREET SPDR S&P 500 TRUST": "SPY",
    "STATE STREET SPDR S&P": "SPY",
    "VANGUARD DIVIDEND APPRECIATION": "VIG",
    "VANGUARD DIVIDEND APPRECIATION INDEX FUND": "VIG",
    "CONSUMER DISCRETIONARY SELECT SECTOR SPDR": "XLY",
    "STATE STRT CONS DSRY SLT SE SP ETF": "XLY",
    "STATE STRT CONS DSRY SLTSE SP ETF": "XLY",
    "STATE STREET CONSUMER DISCRETIONARY SELECT SECTOR SPDR": "XLY",
}

STANDARD_TICKER_NAMES = {
    "AES": "AES Corp",
    "ALKS": "Alkermes plc",
    "ALEX": "Alexander & Baldwin Inc",
    "ALLE": "Allegion plc",
    "AMTM": "Amentum Holdings Inc",
    "AMWD": "American Woodmark Corporation",
    "ARES": "Ares Management Corporation",
    "ATGE": "Adtalem Global Education Inc",
    "AVNS": "Avanos Medical Inc",
    "AX": "Axos Financial Inc",
    "BANC": "Banc of California Inc",
    "BFS": "Saul Centers Inc",
    "BKNG": "Booking Holdings Inc",
    "BXMT": "Blackstone Mortgage Trust Inc",
    "CCS": "Century Communities Inc",
    "CNR": "Core Natural Resources Inc",
    "COIN": "Coinbase Global Inc",
    "COHR": "Coherent Corp",
    "COOP": "Mr. Cooper Group Inc",
    "CORT": "Corcept Therapeutics Inc",
    "CRI": "Carter's Inc",
    "CRK": "Comstock Resources Inc",
    "CSGS": "CSG Systems International Inc",
    "FBK": "FB Financial Corporation",
    "FIX": "Comfort Systems USA Inc",
    "FOUR": "Shift4 Payments Inc",
    "FTV": "Fortive Corporation",
    "GE": "GE Aerospace",
    "GBX": "The Greenbrier Companies Inc",
    "GDEN": "Golden Entertainment Inc",
    "GMS": "GMS Inc",
    "GPN": "Global Payments Inc",
    "GSHD": "Goosehead Insurance Inc",
    "HIG": "The Hartford Insurance Group Inc",
    "HTO": "H2O America",
    "ICE": "Intercontinental Exchange Inc",
    "IDXX": "IDEXX Laboratories Inc",
    "ITRI": "Itron Inc",
    "GOOG": "Alphabet Inc Class C",
    "PPLI": "People Inc",
    "AHRT": "AH Realty Trust Inc",
    "MAFOX": "BlackRock Large Cap Focus Growth Fund",
    "JCI": "Johnson Controls International plc",
    "KALU": "Kaiser Aluminum Corporation",
    "KW": "Kennedy-Wilson Holdings Inc",
    "LII": "Lennox International Inc",
    "LNC": "Lincoln National Corporation",
    "MCW": "Mister Car Wash Inc",
    "MPWR": "Monolithic Power Systems Inc",
    "MTZ": "MasTec Inc",
    "NCLH": "Norwegian Cruise Line Holdings Ltd",
    "NEM": "Newmont Corporation",
    "NPO": "Enpro Inc",
    "PKG": "Packaging Corporation of America",
    "PNC": "PNC Financial Services Group Inc",
    "PRDO": "Perdoceo Education Corporation",
    "QTWO": "Q2 Holdings Inc",
    "RDNT": "RadNet Inc",
    "RTX": "RTX Corporation",
    "SAFT": "Safety Insurance Group Inc",
    "SBCF": "Seacoast Banking Corporation of Florida",
    "SEM": "Select Medical Holdings Corporation",
    "SNDK": "SanDisk Corporation",
    "SKYW": "SkyWest Inc",
    "STEL": "Stellar Bancorp Inc",
    "STE": "STERIS plc",
    "TDC": "Teradata Corporation",
    "TGNA": "TEGNA Inc",
    "UDR": "UDR Inc",
    "VBTX": "Veritex Holdings Inc",
    "VECO": "Veeco Instruments Inc",
    "VFC": "VF Corporation",
    "WAY": "Waystar Holding Corp",
    "WELL": "Welltower Inc",
    "WMT": "Walmart Inc",
    "WTRG": "Essential Utilities Inc",
    "WTW": "Willis Towers Watson plc",
    "XYL": "Xylem Inc",
    "GOOGL": "Alphabet Inc Class A",
    "COMT": "iShares GSCI Commodity Dynamic Roll Strategy ETF",
    "DVY": "iShares Select Dividend ETF",
    "EFA": "iShares MSCI EAFE ETF",
    "EWC": "iShares MSCI Canada ETF",
    "EWJ": "iShares MSCI Japan ETF",
    "GLDM": "SPDR Gold MiniShares",
    "GNR": "State Street SPDR S&P Global Natural Resources ETF",
    "GOVT": "iShares U.S. Treasury Bond ETF",
    "HEZU": "iShares Currency Hedged MSCI Eurozone ETF",
    "IAT": "iShares U.S. Regional Banks ETF",
    "IAU": "iShares Gold Trust",
    "IDEV": "iShares Core MSCI International Developed Markets ETF",
    "IEFA": "iShares Core MSCI EAFE ETF",
    "IEMG": "iShares Core MSCI Emerging Markets ETF",
    "IGM": "iShares Expanded Tech Sector ETF",
    "IGOV": "iShares International Treasury Bond ETF",
    "IOO": "iShares Global 100 ETF",
    "IPAC": "iShares Core MSCI Pacific ETF",
    "IVE": "iShares S&P 500 Value ETF",
    "IVV": "iShares Core S&P 500 ETF",
    "IVW": "iShares S&P 500 Growth ETF",
    "IWM": "iShares Russell 2000 ETF",
    "IWR": "iShares Russell Mid-Cap ETF",
    "MGK": "Vanguard Mega Cap Growth ETF",
    "QQQ": "Invesco QQQ Trust",
    "SLV": "iShares Silver Trust",
    "SPHQ": "Invesco S&P 500 Quality ETF",
    "SPHY": "State Street SPDR Portfolio High Yield Bond ETF",
    "SPY": "State Street SPDR S&P 500 ETF Trust",
    "SPYM": "State Street SPDR Portfolio S&P 500 ETF",
    "TBLL": "Invesco Short Term Treasury ETF",
    "VBK": "Vanguard Small-Cap Growth ETF",
    "VCIT": "Vanguard Intermediate-Term Corporate Bond ETF",
    "VCR": "Vanguard Consumer Discretionary ETF",
    "VGIT": "Vanguard Intermediate-Term Treasury ETF",
    "VGK": "Vanguard FTSE Europe ETF",
    "VIG": "Vanguard Dividend Appreciation ETF",
    "VO": "Vanguard Mid-Cap ETF",
    "VOO": "Vanguard S&P 500 ETF",
    "VTEB": "Vanguard Tax-Exempt Bond ETF",
    "VTI": "Vanguard Total Stock Market ETF",
    "VTWO": "Vanguard Russell 2000 ETF",
    "VUG": "Vanguard Growth ETF",
    "VYM": "Vanguard High Dividend Yield ETF",
    "XLC": "State Street Communication Services Select Sector SPDR ETF",
    "XLE": "State Street Energy Select Sector SPDR ETF",
    "XLF": "State Street Financial Select Sector SPDR ETF",
    "XLI": "State Street Industrial Select Sector SPDR ETF",
    "XLK": "State Street Technology Select Sector SPDR ETF",
    "XLP": "State Street Consumer Staples Select Sector SPDR ETF",
    "XLV": "State Street Health Care Select Sector SPDR ETF",
    "XLY": "State Street Consumer Discretionary Select Sector SPDR ETF",
}

STANDARD_TICKER_NAMES.update({
    "ACI": "Albertsons Companies Inc Class A",
    "AAPL": "Apple Inc",
    "ABBV": "AbbVie Inc",
    "ACN": "Accenture plc",
    "ADBE": "Adobe Inc",
    "AMD": "AMD",
    "AMZN": "Amazon.com Inc",
    "AVGO": "Broadcom Inc",
    "BAC": "Bank of America Corporation",
    "BX": "Blackstone Inc",
    "C": "Citigroup Inc",
    "CCOI": "Cogent Communications Holdings Inc",
    "CERT": "Certara Inc",
    "CHTR": "Charter Communications Inc",
    "CNK": "Cinemark Holdings Inc",
    "CMCSA": "Comcast Corp Class A",
    "COHU": "Cohu Inc",
    "COST": "Costco Wholesale Corp",
    "CPK": "Chesapeake Utilities Corp",
    "CSCO": "Cisco Systems Inc",
    "CVX": "Chevron Corporation",
    "DUK": "Duke Energy Corp",
    "EOG": "EOG Resources Inc",
    "GIS": "General Mills Inc",
    "GS": "Goldman Sachs Group Inc",
    "GTM": "ZoomInfo Technologies Inc",
    "HD": "Home Depot Inc",
    "JNJ": "Johnson & Johnson",
    "JPM": "JPMorgan Chase & Co",
    "MA": "Mastercard Inc Class A",
    "MDLZ": "Mondelez International Inc",
    "META": "Meta Platforms Inc Class A",
    "MRK": "Merck & Co Inc",
    "MSFT": "Microsoft Corp",
    "NFLX": "Netflix Inc",
    "NVDA": "NVIDIA Corp",
    "ORCL": "Oracle Corp",
    "PEP": "PepsiCo Inc",
    "PM": "Philip Morris International Inc",
    "SBUX": "Starbucks Corp",
    "T": "AT&T Inc",
    "TSLA": "Tesla Inc",
    "TXN": "Texas Instruments Inc",
    "UNH": "UnitedHealth Group Inc",
    "V": "Visa Inc Class A",
    "VZ": "Verizon Communications Inc",
    "WFC": "Wells Fargo & Co",
    "XOM": "Exxon Mobil Corp",
    "ADI": "Analog Devices Inc",
    "BA": "Boeing Co",
    "CRM": "Salesforce Inc",
    "DASH": "DoorDash Inc Class A",
    "DHR": "Danaher Corp",
    "INTU": "Intuit Inc",
    "ISRG": "Intuitive Surgical Inc",
    "KO": "Coca-Cola Co",
    "LIN": "Linde plc",
    "MCD": "McDonald's Corp",
    "MS": "Morgan Stanley",
    "NEE": "NextEra Energy Inc",
    "PANW": "Palo Alto Networks Inc",
    "PFE": "Pfizer Inc",
    "PG": "Procter & Gamble Co",
    "PAHC": "Phibro Animal Health Corp Class A",
    "PLTR": "Palantir Technologies Inc Class A",
    "QCOM": "Qualcomm Inc",
    "ROP": "Roper Technologies Inc",
    "SO": "Southern Co",
    "SYK": "Stryker Corp",
    "TMUS": "T-Mobile US Inc",
    "UBER": "Uber Technologies Inc",
    "UPS": "United Parcel Service Inc Class B",
    "VRTX": "Vertex Pharmaceuticals Inc",
    "VRRM": "Verra Mobility Corp Class A",
    "YOU": "Clear Secure Inc Class A",
    "ZTS": "Zoetis Inc",
})

CORPORATE_SUFFIXES = {
    "A",
    "B",
    "C",
    "CL",
    "CLASS",
    "CO",
    "COM",
    "COMPANY",
    "CORP",
    "CORPORATION",
    "GROUP",
    "HLDGS",
    "HOLDING",
    "HOLDINGS",
    "INC",
    "LTD",
    "NEW",
    "ORD",
    "PLC",
    "REG",
    "SHS",
    "THE",
}

HSBC_CODES_PATH = Path(__file__).with_name("data") / "hsbc_us_stock_codes.json"

ETF_TERMS = (
    " ETF",
    "EXCHANGE-TRADED",
    "EXCHANGE TRADED",
    "SPDR",
    "ISHARES",
    "!SHARES",
    "VANGUARD",
    "SELECT SECTOR",
    "JPMORGAN BETABUILDERS",
    "QQQ TRUST",
)

FUND_TERMS = (
    " MUTUAL FUND",
    " GROWTH FUND",
    " FOCUS FUND",
    " LARGE CAP FOCUS",
)

CRYPTO_TERMS = (
    "BITCOIN",
    "ETHEREUM",
    "CRYPTO",
    "CRYPTOCURRENCY",
    "DIGITAL ASSET",
    "VIRTUAL CURRENCY",
    "TOKEN",
    "NFT",
    "MEME COIN",
    "SOLANA",
    "DOGECOIN",
    "TETHER",
    "USDC",
    "USDT",
    "XRP",
    "LITECOIN",
    "CARDANO",
    "WORLD LIBERTY",
    "WLFI",
    "BTC",
    "ETH",
)

DEBT_TERMS = (
    " TREAS BILLS",
    " TREASURY BILL",
    " T-BILL",
    " T BILL",
    " NOTE ",
    " NOTES ",
    " BOND ",
    " BONDS ",
    " DEBENTURE",
    " DEB ",
    " FUNDING ",
    " CAPITAL MARKETS",
    " PFD ",
    " PREFERRED",
    " PREFERENCE",
    " PERP ",
    " DP SH",
    " DEPOSITARY",
    " SUBORDINATED",
    " SENIOR UNSECURED",
    " SENIOR SECURED",
    " MTN ",
    "DTD ",
    " B/E",
    " B/ E",
    " B/E ",
    " DUE ",
    "% DUE",
    " REV ",
    " RFDG ",
    " GO ",
    " LTX ",
    " UTX ",
    " MUD ",
    " AUTH ",
    " CNTY ",
    " COUNTY ",
    " CMNTY ",
    " CLLG ",
    " SCH ",
    " SCHOOL ",
    " UNIV ",
    " HSG ",
    " HOUSING ",
    " PUB FIN ",
    " PUBLIC FIN ",
    " WATER ",
    " WTR ",
    " GAS DIST",
)

CASH_OR_PRIVATE_TERMS = (
    " CASH",
    "CHECKING",
    "SAVINGS",
    "MONEY MARKET",
    "BANK ACCOUNT",
    "CERTIFICATE OF DEPOSIT",
    "UNDERLYING ASSETS ARE NOT REPORTABLE",
    "SEE ENDNOTE",
    " LLC",
    " LP",
    " L.P.",
    "PARTNERSHIP",
    "REAL ESTATE",
    "HOTEL",
    "RESORT",
    "GOLF",
)

STOCK_TERMS = (
    " COM",
    " COMMON",
    " CLASS A",
    " CLASS B",
    " CLASS C",
    " CL A",
    " CL B",
    " ORD",
    " ADR",
    " PLC",
    " INC",
    " CORP",
    " CORPORATION",
    " COMPANY STOCK",
    " REIT",
    "-SBI",
)


def clean_asset_name(name: str | None) -> str:
    value = str(name or "")
    value = OCR_TAIL_RE.sub("", value)
    value = re.sub(r"^\*+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _ticker_from_text(asset_name: str | None) -> str | None:
    asset = clean_asset_name(asset_name).upper()
    match = re.search(r"\(([A-Z][A-Z0-9.\-]{0,8})\)", asset)
    if match:
        return match.group(1)
    return None


def _name_key(value: str | None) -> str:
    text = clean_asset_name(value).upper()
    text = text.replace("&", " AND ")
    replacements = {
        " INTL ": " INTERNATIONAL ",
        " SVC ": " SERVICE ",
        " SVCS ": " SERVICES ",
        " MATLS ": " MATERIALS ",
        " MTRS ": " MOTORS ",
        " FINL ": " FINANCIAL ",
        " WKS ": " WORKS ",
        " INDS ": " INDUSTRIES ",
        " MGMT ": " MANAGEMENT ",
        " COS ": " COMPANIES ",
        " INSTRS ": " INSTRUMENTS ",
        " RESH ": " RESEARCH ",
        " RLTY ": " REALTY ",
        " CMNTYS ": " COMMUNITIES ",
        " CAP ": " CAPITAL ",
        " TECH ": " TECHNOLOGIES ",
    }
    padded = f" {text} "
    for old, new in replacements.items():
        padded = padded.replace(old, new)
    text = padded.strip()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = []
    for token in text.split():
        if token in CORPORATE_SUFFIXES:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        tokens.append(token)
    return " ".join(tokens)


def _contains_name(haystack: str, needle: str) -> bool:
    target = needle.upper()
    if not target:
        return False
    start = haystack.find(target)
    while start != -1:
        before = haystack[start - 1] if start > 0 else " "
        after_index = start + len(target)
        after = haystack[after_index] if after_index < len(haystack) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        start = haystack.find(target, start + 1)
    return False


@lru_cache(maxsize=1)
def _ticker_override_index() -> dict[str, dict]:
    if not DB_PATH.exists():
        return {}
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT normalized_name, ticker, display_name, asset_type
                FROM ticker_overrides
                WHERE ticker IS NOT NULL AND trim(ticker) <> ''
                """
            ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(row["normalized_name"]): dict(row) for row in rows}


def clear_ticker_override_cache() -> None:
    _ticker_override_index.cache_clear()


def _ticker_override(asset_name: str | None) -> dict | None:
    key = _name_key(asset_name)
    if not key:
        return None
    return _ticker_override_index().get(key)


@lru_cache(maxsize=1)
def _hsbc_ticker_index() -> list[dict]:
    if not HSBC_CODES_PATH.exists():
        return []
    with HSBC_CODES_PATH.open("r", encoding="utf-8") as f:
        records = json.load(f)
    index = []
    for record in records:
        code = str(record.get("code") or "").strip().upper()
        english_name = record.get("english_name")
        if not code or not english_name:
            continue
        key = _name_key(english_name)
        if len(key) < 4:
            continue
        index.append({
            "code": code,
            "english_name": english_name,
            "chinese_name": record.get("chinese_name"),
            "industry": record.get("industry"),
            "key": key,
        })
    index.sort(key=lambda item: len(item["key"]), reverse=True)
    return index


def _infer_ticker_from_hsbc(asset_name: str | None) -> str | None:
    key = _name_key(asset_name)
    if not key:
        return None
    asset = f" {clean_asset_name(asset_name).upper()} "
    if any(term in asset for term in ETF_TERMS):
        return None
    for record in _hsbc_ticker_index():
        if key == record["key"]:
            return record["code"]
    for record in _hsbc_ticker_index():
        candidate = record["key"]
        candidate_tokens = candidate.split()
        if len(candidate_tokens) == 1:
            if key == candidate:
                return record["code"]
            continue
        if candidate in key or key in candidate:
            return record["code"]
    return None


def infer_ticker(asset_name: str | None, existing: str | None = None) -> str | None:
    override = _ticker_override(asset_name)
    if override:
        return str(override.get("ticker") or "").strip().upper() or None
    ticker = _ticker_from_text(asset_name)
    if ticker:
        return ticker
    asset = clean_asset_name(asset_name).upper()
    for needle, ticker in ETF_TICKERS.items():
        if needle in asset:
            return ticker
    for needle, ticker in COMPANY_TICKERS.items():
        if _contains_name(asset, needle):
            return ticker
    if existing:
        return existing
    ticker = _infer_ticker_from_hsbc(asset_name)
    if ticker:
        return ticker
    return None


def display_asset_name(asset_name: str | None, ticker: str | None = None) -> str:
    override = _ticker_override(asset_name)
    if override and override.get("display_name"):
        return str(override["display_name"]).strip()
    ticker_value = str(ticker or "").strip().upper() or str(infer_ticker(asset_name) or "").strip().upper()
    if ticker_value in STANDARD_TICKER_NAMES:
        return STANDARD_TICKER_NAMES[ticker_value]
    return clean_asset_name(asset_name)


def _is_yield_security(asset: str) -> bool:
    return bool(
        re.search(r"\bP[./\s-]?E\b.*\d(?:\.\d+)?\s*%", asset)
        or re.search(r"\bPF[./\s-]?[A-Z]?\b.*\d(?:\.\d+)?\s*%", asset)
        or re.search(r"\bPFD\b.*\d(?:\.\d+)?\s*%", asset)
        or re.search(r"\bPREFERRED\b.*\d(?:\.\d+)?\s*%", asset)
        or re.search(r"\bPERP\b.*\d(?:\.\d+)?\s*%", asset)
        or re.search(r"\d(?:\.\d+)?\s*%.*\b(?:DUE|12/31/49|12/31/2049)\b", asset)
        or re.search(r"\d{1,2}\.\d{2,4}\s*%", asset)
    )


def _is_crypto_asset(asset: str) -> bool:
    for term in CRYPTO_TERMS:
        needle = term.upper()
        if needle in {"BTC", "ETH"}:
            if re.search(rf"(?<![A-Z0-9]){needle}(?![A-Z0-9])", asset):
                return True
            continue
        if needle in asset:
            return True
    return False


def asset_category(asset_name: str | None, ticker: str | None = None) -> str:
    asset = f" {clean_asset_name(asset_name).upper()} "
    ticker_value = str(ticker or "").strip().upper()
    if _is_crypto_asset(asset):
        return "排除资产"
    if any(term in asset for term in ETF_TERMS):
        return "ETF"
    if ticker_value in {"MAFOX"} or any(term in asset for term in FUND_TERMS):
        return "基金"
    if _is_yield_security(asset):
        return "债券/票据"
    if any(term in asset for term in DEBT_TERMS):
        return "债券/票据"
    if ticker_value and ticker_value not in {"CASH", "N/A", "NA", "-"}:
        return "个股"
    if any(term in asset for term in STOCK_TERMS):
        return "个股"
    if any(term in asset for term in CASH_OR_PRIVATE_TERMS):
        return "非公开/现金类"
    return "其他"


def is_public_investable_asset(asset_name: str | None, ticker: str | None = None) -> bool:
    category = asset_category(asset_name, ticker)
    return category in {"个股", "ETF", "基金"}


def parse_amount_range(value: str | None) -> dict:
    text = str(value or "")
    if not re.fullmatch(
        r"\s*(Over\s+)?\$[\d,]+(?:\s*-\s*\$?[\d,]+)?\s*",
        text,
        flags=re.I,
    ):
        return {"low": 0, "high": 0, "mid": 0, "valid": False}
    normalized = text.replace(",", "")
    numbers = [int(n) for n in re.findall(r"\$?\s*(\d+)", normalized)]
    if not numbers:
        return {"low": 0, "high": 0, "mid": 0, "valid": False}
    if "over" in normalized.lower():
        low = numbers[0]
        high = int(low * 1.25)
    elif len(numbers) >= 2:
        low, high = numbers[0], numbers[1]
    else:
        low = high = numbers[0]
    valid = low > 0 and high >= low and high <= 50_000_000
    return {"low": low, "high": high, "mid": int((low + high) / 2), "valid": valid}


def classify_concept(asset_name: str | None) -> str:
    category = asset_category(asset_name)
    if category == "ETF":
        return category
    haystack = f" {clean_asset_name(asset_name).upper()} "
    for label, terms in CONCEPTS.items():
        if any(_concept_term_match(haystack, term) for term in terms):
            return label
    return "其他公司证券"


def _concept_term_match(haystack: str, term: str) -> bool:
    needle = term.upper()
    if needle.startswith(" ") or needle.endswith(" "):
        return needle in haystack
    return _contains_name(haystack, needle)


def public_trade_quality(row: dict) -> tuple[bool, list[str]]:
    reasons = []
    asset = clean_asset_name(row.get("asset_name"))
    amount = parse_amount_range(row.get("amount_range"))
    if row.get("review_state") not in {"parsed", "approved"}:
        reasons.append("not_reviewed")
    if not row.get("transaction_type"):
        reasons.append("missing_type")
    if not row.get("transaction_date"):
        reasons.append("missing_date")
    if not amount["valid"]:
        reasons.append("invalid_amount_range")
    if len(asset) > 160:
        reasons.append("asset_name_too_long")
    if len(re.findall(r"\bDue\b", asset, re.I)) >= 3:
        reasons.append("multiple_bond_rows_merged")
    if re.search(r"\$[\d,]+\s*-\s*\$?[\d,]{9,}", str(row.get("amount_range") or "")):
        reasons.append("suspicious_high_amount")
    if re.search(r"\b\d{7,8}\b", str(row.get("amount_range") or "")):
        reasons.append("amount_contains_date_like_token")
    if not is_public_investable_asset(asset, row.get("ticker")):
        reasons.append("not_public_investable_asset")
    return not reasons, reasons
