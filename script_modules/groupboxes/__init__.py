"""
QGroupBox subclasses, one per UI concern.

Each module here owns a single cluster of related controls and follows the
same shape: ``_create_widgets`` / ``_setup_layout`` / ``_connect_signals``.
A groupbox owns only its widgets and their local state; it exposes Qt
Signals and lets the parent tab do the work, so the same control cluster
can be reused in a different tab without dragging application logic along.
"""
