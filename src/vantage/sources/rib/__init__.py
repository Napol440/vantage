"""Rib.gg data source (Component 2).

Rib.gg does not publish an official public API. The endpoints implemented here
are the "classic" ones reverse-engineered by the community
(see ``tonyelhabr/valorantr`` and ``docs/RIB_REDISCOVERY.md``).

The backend host (``be-prod.rib.gg``) has been unreachable / DNS-dead on some
networks since ~2023, so everything in this package is **best-effort**: it is
enabled only when ``rib.enabled`` is true, logs clearly when it fails, and never
blocks the VLR.gg pipeline.
"""
