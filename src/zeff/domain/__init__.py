"""Domain layer: pure pydantic models, validation, and business invariants.

No DB / no framework imports here. The domain layer defines the shape of
nodes, facets, and search results; persistence lives in `zeff.db`.
"""
