"""Flight search for Travel With Yori.

Sources are tried in order (gf-search, fli, swoop, then Travelpayouts when a
token is configured). Results are validated, normalised to one shape, cached
for 10 minutes and served by the routes in ``flights.api``.
"""
