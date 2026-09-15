"""City names for common airports, and places that map to their nearest airports.

The full airport list (names and codes) comes from fli. This file only adds the
city people type, and regions or islands without their own airport name.
Codes that aren't in fli's list are ignored.
"""

CITY_OF: dict[str, str] = {
    # India
    "DEL": "New Delhi", "BOM": "Mumbai", "NMI": "Mumbai", "BLR": "Bengaluru", "MAA": "Chennai",
    "CCU": "Kolkata", "HYD": "Hyderabad", "AMD": "Ahmedabad", "PNQ": "Pune", "GOI": "Goa", "GOX": "Goa",
    "COK": "Kochi", "TRV": "Thiruvananthapuram", "CCJ": "Kozhikode", "JAI": "Jaipur", "UDR": "Udaipur",
    "JDH": "Jodhpur", "JSA": "Jaisalmer", "ATQ": "Amritsar", "IXC": "Chandigarh", "SXR": "Srinagar",
    "IXJ": "Jammu", "IXL": "Leh", "DED": "Dehradun", "VNS": "Varanasi", "LKO": "Lucknow", "AGR": "Agra",
    "IXB": "Bagdogra", "GAU": "Guwahati", "PAT": "Patna", "BBI": "Bhubaneswar", "IXZ": "Port Blair",
    "IXE": "Mangaluru", "TRZ": "Tiruchirappalli", "CJB": "Coimbatore", "IXM": "Madurai",
    "VTZ": "Visakhapatnam", "NAG": "Nagpur", "IDR": "Indore", "BHO": "Bhopal", "RPR": "Raipur",
    "IXR": "Ranchi", "KUU": "Kullu", "DHM": "Dharamshala", "GAY": "Gaya", "STV": "Surat",
    "BDQ": "Vadodara", "HSR": "Rajkot", "IXA": "Agartala", "IMF": "Imphal", "DIB": "Dibrugarh",
    "SHL": "Shillong", "VGA": "Vijayawada", "TIR": "Tirupati", "HBX": "Hubballi", "MYQ": "Mysuru",
    "AGX": "Agatti", "HJR": "Khajuraho", "BHJ": "Bhuj", "SLV": "Shimla", "PYG": "Gangtok",
    # Middle East
    "DXB": "Dubai", "DWC": "Dubai", "AUH": "Abu Dhabi", "SHJ": "Sharjah", "DOH": "Doha", "BAH": "Bahrain",
    "MCT": "Muscat", "RUH": "Riyadh", "JED": "Jeddah", "MED": "Medina", "KWI": "Kuwait City",
    # Asia
    "SIN": "Singapore", "KUL": "Kuala Lumpur", "LGK": "Langkawi", "BKK": "Bangkok", "DMK": "Bangkok",
    "HKT": "Phuket", "USM": "Koh Samui", "CNX": "Chiang Mai", "KBV": "Krabi", "DPS": "Denpasar",
    "CGK": "Jakarta", "SUB": "Surabaya", "MNL": "Manila", "SGN": "Ho Chi Minh City", "HAN": "Hanoi",
    "DAD": "Da Nang", "PNH": "Phnom Penh", "HKG": "Hong Kong", "MFM": "Macau", "TPE": "Taipei",
    "PEK": "Beijing", "PKX": "Beijing", "PVG": "Shanghai", "SHA": "Shanghai", "CAN": "Guangzhou",
    "ICN": "Seoul", "GMP": "Seoul", "NRT": "Tokyo", "HND": "Tokyo", "KIX": "Osaka", "ITM": "Osaka",
    "CTS": "Sapporo", "FUK": "Fukuoka", "OKA": "Okinawa", "CMB": "Colombo", "MLE": "Malé",
    "KTM": "Kathmandu", "DAC": "Dhaka", "PBH": "Paro",
    # Europe
    "LHR": "London", "LGW": "London", "STN": "London", "LTN": "London", "LCY": "London",
    "MAN": "Manchester", "EDI": "Edinburgh", "DUB": "Dublin", "CDG": "Paris", "ORY": "Paris",
    "NCE": "Nice", "AMS": "Amsterdam", "BRU": "Brussels", "FRA": "Frankfurt", "MUC": "Munich",
    "BER": "Berlin", "ZRH": "Zurich", "GVA": "Geneva", "VIE": "Vienna", "PRG": "Prague",
    "BUD": "Budapest", "WAW": "Warsaw", "CPH": "Copenhagen", "ARN": "Stockholm", "OSL": "Oslo",
    "HEL": "Helsinki", "RVN": "Rovaniemi", "KEF": "Reykjavik", "MAD": "Madrid", "BCN": "Barcelona",
    "LIS": "Lisbon", "OPO": "Porto", "FCO": "Rome", "CIA": "Rome", "MXP": "Milan", "LIN": "Milan",
    "VCE": "Venice", "FLR": "Florence", "PSA": "Pisa", "NAP": "Naples", "ATH": "Athens",
    "JTR": "Santorini", "JMK": "Mykonos", "IST": "Istanbul", "SAW": "Istanbul", "AYT": "Antalya",
    # Africa
    "CAI": "Cairo", "HRG": "Hurghada", "RAK": "Marrakesh", "CMN": "Casablanca", "NBO": "Nairobi",
    "JNB": "Johannesburg", "CPT": "Cape Town", "SEZ": "Mahé", "MRU": "Mauritius", "ZNZ": "Zanzibar",
    # Americas
    "JFK": "New York", "EWR": "New York", "LGA": "New York", "LAX": "Los Angeles", "SFO": "San Francisco",
    "ORD": "Chicago", "MIA": "Miami", "LAS": "Las Vegas", "SEA": "Seattle", "BOS": "Boston",
    "IAD": "Washington", "DCA": "Washington", "HNL": "Honolulu", "OGG": "Maui", "YYZ": "Toronto",
    "YVR": "Vancouver", "MEX": "Mexico City", "CUN": "Cancún", "GRU": "São Paulo",
    "EZE": "Buenos Aires", "LIM": "Lima", "CUZ": "Cusco",
    # Oceania
    "SYD": "Sydney", "MEL": "Melbourne", "BNE": "Brisbane", "PER": "Perth", "AKL": "Auckland",
    "ZQN": "Queenstown", "NAN": "Nadi",
}

# Other names people type, and places without their own airport, mapped to the nearest airports.
PLACES: dict[str, list[str]] = {
    # India: other city names
    "delhi": ["DEL"], "gurgaon": ["DEL"], "gurugram": ["DEL"], "noida": ["DEL"], "bombay": ["BOM", "NMI"],
    "navi mumbai": ["NMI", "BOM"], "bangalore": ["BLR"], "madras": ["MAA"], "calcutta": ["CCU"],
    "cochin": ["COK"], "trivandrum": ["TRV"], "calicut": ["CCJ"], "mangalore": ["IXE"], "mysore": ["MYQ"],
    "vizag": ["VTZ"], "hubli": ["HBX"], "baroda": ["BDQ"], "banaras": ["VNS"], "benares": ["VNS"],
    "pondicherry": ["MAA"], "puducherry": ["MAA"],
    # India: regions, hill stations, islands
    "goa": ["GOI", "GOX"], "kerala": ["COK", "TRV", "CCJ"], "munnar": ["COK"], "alleppey": ["COK"],
    "alappuzha": ["COK"], "kovalam": ["TRV"], "varkala": ["TRV"], "wayanad": ["CCJ"], "coorg": ["IXE"],
    "ooty": ["CJB"], "kodaikanal": ["IXM"], "hampi": ["HBX"], "ladakh": ["IXL"], "kashmir": ["SXR"],
    "gulmarg": ["SXR"], "pahalgam": ["SXR"], "manali": ["KUU"], "himachal": ["KUU", "DHM"],
    "mcleodganj": ["DHM"], "rishikesh": ["DED"], "haridwar": ["DED"], "mussoorie": ["DED"],
    "uttarakhand": ["DED"], "nainital": ["DED"], "darjeeling": ["IXB"], "sikkim": ["IXB", "PYG"],
    "andaman": ["IXZ"], "andaman and nicobar": ["IXZ"], "havelock": ["IXZ"], "lakshadweep": ["AGX"],
    "rajasthan": ["JAI", "UDR", "JDH"], "taj mahal": ["AGR", "DEL"], "kutch": ["BHJ"],
    "rann of kutch": ["BHJ"], "bodh gaya": ["GAY"], "meghalaya": ["SHL", "GAU"], "assam": ["GAU"],
    "puri": ["BBI"], "odisha": ["BBI"], "punjab": ["ATQ", "IXC"], "gujarat": ["AMD"],
    "tamil nadu": ["MAA"], "karnataka": ["BLR"], "telangana": ["HYD"], "maharashtra": ["BOM"],
    # Nearby countries
    "sri lanka": ["CMB"], "maldives": ["MLE"], "male": ["MLE"], "nepal": ["KTM"], "bhutan": ["PBH"],
    "bangladesh": ["DAC"],
    # Asia and the Middle East
    "bali": ["DPS"], "ubud": ["DPS"], "seminyak": ["DPS"], "kuta": ["DPS"], "indonesia": ["CGK", "DPS"],
    "thailand": ["BKK", "HKT"], "samui": ["USM"], "pattaya": ["BKK"], "malaysia": ["KUL"],
    "vietnam": ["SGN", "HAN"], "saigon": ["SGN"], "cambodia": ["PNH"], "siem reap": ["PNH"],
    "philippines": ["MNL"], "japan": ["HND", "NRT"], "kyoto": ["KIX", "ITM"], "korea": ["ICN"],
    "south korea": ["ICN"], "china": ["PEK", "PVG"], "taiwan": ["TPE"], "uae": ["DXB", "AUH"],
    "qatar": ["DOH"], "oman": ["MCT"], "saudi arabia": ["RUH", "JED"], "mecca": ["JED"],
    "makkah": ["JED"], "madinah": ["MED"], "turkey": ["IST"], "cappadocia": ["IST"],
    # Europe
    "england": ["LHR", "LGW"], "uk": ["LHR", "LGW"], "united kingdom": ["LHR", "LGW"],
    "scotland": ["EDI"], "ireland": ["DUB"], "france": ["CDG", "ORY"], "netherlands": ["AMS"],
    "holland": ["AMS"], "belgium": ["BRU"], "germany": ["FRA", "MUC"], "switzerland": ["ZRH", "GVA"],
    "swiss alps": ["ZRH", "GVA"], "interlaken": ["ZRH"], "zermatt": ["GVA", "ZRH"], "austria": ["VIE"],
    "czech republic": ["PRG"], "czechia": ["PRG"], "hungary": ["BUD"], "poland": ["WAW"],
    "denmark": ["CPH"], "sweden": ["ARN"], "norway": ["OSL"], "finland": ["HEL"], "lapland": ["RVN"],
    "iceland": ["KEF"], "spain": ["MAD", "BCN"], "portugal": ["LIS"], "italy": ["FCO", "MXP"],
    "amalfi": ["NAP"], "amalfi coast": ["NAP"], "tuscany": ["FLR", "PSA"], "greece": ["ATH"],
    # Africa, Americas, Oceania
    "egypt": ["CAI"], "morocco": ["RAK", "CMN"], "kenya": ["NBO"], "south africa": ["JNB", "CPT"],
    "seychelles": ["SEZ"], "usa": ["JFK", "LAX"], "united states": ["JFK", "LAX"], "america": ["JFK", "LAX"],
    "nyc": ["JFK", "EWR", "LGA"], "new york city": ["JFK", "EWR", "LGA"], "manhattan": ["JFK", "EWR", "LGA"],
    "hawaii": ["HNL", "OGG"], "canada": ["YYZ", "YVR"], "mexico": ["MEX", "CUN"], "brazil": ["GRU"],
    "argentina": ["EZE"], "peru": ["LIM"], "machu picchu": ["CUZ"], "australia": ["SYD", "MEL"],
    "new zealand": ["AKL"], "fiji": ["NAN"],
}
