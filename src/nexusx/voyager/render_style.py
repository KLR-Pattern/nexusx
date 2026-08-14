"""Style constants and configuration for rendering DOT graphs and HTML tables.

Migrated from fastapi-voyager, with framework-specific colors simplified.
"""
from dataclasses import dataclass, field

# Default primary color (used for all frameworks in this context)
DEFAULT_PRIMARY = '#009485'


def text_color_for(background: str, default: str = 'white') -> str:
    """Pick black or white text for a background color by luminance (W3C).

    Light fills (e.g. the pastel member colors recommended for
    ``ErManager(color=...)``) get dark text; dark fills keep white. Hex colors
    only (#RGB / #RRGGBB, case-insensitive) — named colors and anything
    unparseable fall back to ``default`` (the pre-existing behavior for
    theme colors like ``tomato``).
    """
    hex_part = background.strip().lstrip('#')
    if not hex_part or not background.strip().startswith('#'):
        return default
    if len(hex_part) == 3:
        hex_part = ''.join(c * 2 for c in hex_part)
    if len(hex_part) != 6:
        return default
    try:
        r, g, b = (int(hex_part[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return '#000' if luminance > 0.6 else default


@dataclass
class ColorScheme:
    """Color scheme for graph visualization."""

    # Node colors
    primary: str = DEFAULT_PRIMARY
    highlight: str = 'tomato'

    # Pydantic-resolve metadata colors (kept for template compatibility)
    resolve: str = '#47a80f'
    post: str = '#427fa4'
    expose_as: str = '#895cb9'
    send_to: str = '#ca6d6d'
    collector: str = '#777'

    # GraphQL method colors
    query: str = '#47a80f'
    mutation: str = '#ca6d6d'

    # Link colors
    inherit: str = 'purple'
    subset: str = 'orange'

    # Border colors
    border: str = '#666'
    cluster_border: str = '#ccc'

    # Text colors
    text_gray: str = '#999'

    # Virtual entity (non-SQLModel root) styling — Contract 3 visual distinction.
    # Used for plain BaseModel classes registered via ErManager.add_virtual_entities().
    virtual_fill: str = '#FFF9C4'      # light yellow header fill
    virtual_cluster: str = '#E0E0E0'   # dashed cluster border for cluster_virtual


@dataclass
class GraphvizStyle:
    """Graphviz DOT style configuration."""

    # Font settings
    font: str = 'Helvetica,Arial,sans-serif'
    node_fontsize: str = '16'
    cluster_fontsize: str = '20'

    # Layout settings
    nodesep: str = '0.8'
    pad: str = '0.5'
    node_margin: str = '0.5,0.1'
    cluster_margin: str = '18'
    er_nodesep: str = '1.0'
    er_ranksep: str = '1.2'
    er_pad: str = '0.8'
    er_cluster_margin: str = '28'

    # Link styles configuration
    LINK_STYLES: dict[str, dict] = field(default_factory=lambda: {
        'tag_route': {
            'style': 'solid',
            'minlen': 3,
        },
        'route_to_schema': {
            'style': 'solid',
            'dir': 'back',
            'arrowtail': 'odot',
            'minlen': 3,
        },
        'schema': {
            'style': 'solid',
            'label': '',
            'dir': 'back',
            'minlen': 3,
            'arrowtail': 'odot',
        },
        'parent': {
            'style': 'solid,dashed',
            'dir': 'back',
            'minlen': 3,
            'taillabel': '< inherit >',
            'color': 'purple',
            'tailport': 'n',
        },
        'subset': {
            'style': 'solid,dashed',
            'dir': 'back',
            'minlen': 3,
            'taillabel': '< subset >',
            'color': 'orange',
            'tailport': 'n',
        },
        'tag_to_schema': {
            'style': 'solid',
            'minlen': 3,
        },
    })

    def get_link_attributes(self, link_type: str) -> dict:
        """Get link style attributes for a given link type."""
        return self.LINK_STYLES.get(link_type, {})


@dataclass
class RenderConfig:
    """Complete rendering configuration."""

    colors: ColorScheme = field(default_factory=ColorScheme)
    style: GraphvizStyle = field(default_factory=GraphvizStyle)

    # Field display settings
    max_type_length: int = 25
    type_suffix: str = '..'
