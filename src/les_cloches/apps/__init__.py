"""Platform-specific application adapters.

Each adapter under `linux` or `windows` owns its accessibility-tree semantics
and satisfies `les_cloches.transport.DesktopAdapter` independently. They do
not share an adapter base class.
"""
