"""The currency travellers use in each country (ISO 3166 country code -> ISO 4217 currency code).

REST Countries, which used to give this, retired its free version (checked 14 Sep 2026), so the table lives here.
"""

from __future__ import annotations

from typing import Optional

_EURO = "AD AT AX BE BG BL CY DE EE ES FI FR GF GP GR HR IE IT LT LU LV MC ME MF MQ MT NL PM PT RE SI SK SM TF VA XK YT"
_US_DOLLAR = "AS BQ EC FM GU IO MH MP PA PR PW SV TC TL UM US VG VI ZW"

_OTHERS = {
    "AE": "AED", "AF": "AFN", "AG": "XCD", "AI": "XCD", "AL": "ALL", "AM": "AMD", "AO": "AOA", "AR": "ARS", "AU": "AUD", "AW": "AWG",
    "AZ": "AZN", "BA": "BAM", "BB": "BBD", "BD": "BDT", "BF": "XOF", "BH": "BHD", "BI": "BIF", "BJ": "XOF", "BM": "BMD", "BN": "BND",
    "BO": "BOB", "BR": "BRL", "BS": "BSD", "BT": "BTN", "BV": "NOK", "BW": "BWP", "BY": "BYN", "BZ": "BZD", "CA": "CAD", "CC": "AUD",
    "CD": "CDF", "CF": "XAF", "CG": "XAF", "CH": "CHF", "CI": "XOF", "CK": "NZD", "CL": "CLP", "CM": "XAF", "CN": "CNY", "CO": "COP",
    "CR": "CRC", "CU": "CUP", "CV": "CVE", "CW": "XCG", "CX": "AUD", "CZ": "CZK", "DJ": "DJF", "DK": "DKK", "DM": "XCD", "DO": "DOP",
    "DZ": "DZD", "EG": "EGP", "EH": "MAD", "ER": "ERN", "ET": "ETB", "FJ": "FJD", "FK": "FKP", "FO": "DKK", "GA": "XAF", "GB": "GBP",
    "GD": "XCD", "GE": "GEL", "GG": "GBP", "GH": "GHS", "GI": "GIP", "GL": "DKK", "GM": "GMD", "GN": "GNF", "GQ": "XAF", "GS": "GBP",
    "GT": "GTQ", "GW": "XOF", "GY": "GYD", "HK": "HKD", "HM": "AUD", "HN": "HNL", "HT": "HTG", "HU": "HUF", "ID": "IDR", "IL": "ILS",
    "IM": "GBP", "IN": "INR", "IQ": "IQD", "IR": "IRR", "IS": "ISK", "JE": "GBP", "JM": "JMD", "JO": "JOD", "JP": "JPY", "KE": "KES",
    "KG": "KGS", "KH": "KHR", "KI": "AUD", "KM": "KMF", "KN": "XCD", "KP": "KPW", "KR": "KRW", "KW": "KWD", "KY": "KYD", "KZ": "KZT",
    "LA": "LAK", "LB": "LBP", "LC": "XCD", "LI": "CHF", "LK": "LKR", "LR": "LRD", "LS": "LSL", "LY": "LYD", "MA": "MAD", "MD": "MDL",
    "MG": "MGA", "MK": "MKD", "ML": "XOF", "MM": "MMK", "MN": "MNT", "MO": "MOP", "MR": "MRU", "MS": "XCD", "MU": "MUR", "MV": "MVR",
    "MW": "MWK", "MX": "MXN", "MY": "MYR", "MZ": "MZN", "NA": "NAD", "NC": "XPF", "NE": "XOF", "NF": "AUD", "NG": "NGN", "NI": "NIO",
    "NO": "NOK", "NP": "NPR", "NR": "AUD", "NU": "NZD", "NZ": "NZD", "OM": "OMR", "PE": "PEN", "PF": "XPF", "PG": "PGK", "PH": "PHP",
    "PK": "PKR", "PL": "PLN", "PN": "NZD", "PS": "ILS", "PY": "PYG", "QA": "QAR", "RO": "RON", "RS": "RSD", "RU": "RUB", "RW": "RWF",
    "SA": "SAR", "SB": "SBD", "SC": "SCR", "SD": "SDG", "SE": "SEK", "SG": "SGD", "SH": "SHP", "SJ": "NOK", "SL": "SLE", "SN": "XOF",
    "SO": "SOS", "SR": "SRD", "SS": "SSP", "ST": "STN", "SX": "XCG", "SY": "SYP", "SZ": "SZL", "TD": "XAF", "TG": "XOF", "TH": "THB",
    "TJ": "TJS", "TK": "NZD", "TM": "TMT", "TN": "TND", "TO": "TOP", "TR": "TRY", "TT": "TTD", "TV": "AUD", "TW": "TWD", "TZ": "TZS",
    "UA": "UAH", "UG": "UGX", "UY": "UYU", "UZ": "UZS", "VC": "XCD", "VE": "VES", "VN": "VND", "VU": "VUV", "WF": "XPF", "WS": "WST",
    "YE": "YER", "ZA": "ZAR", "ZM": "ZMW",
}

COUNTRY_CURRENCY = {**{code: "EUR" for code in _EURO.split()}, **{code: "USD" for code in _US_DOLLAR.split()}, **_OTHERS}


def currency_for_country(country_code: str) -> Optional[str]:
    return COUNTRY_CURRENCY.get((country_code or "").upper())
