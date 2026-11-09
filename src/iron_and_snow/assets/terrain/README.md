# Battlefield terrain props

These transparent ImageGen cutouts are placed over the shared Winterfell battlefield painting and paired with separate ground-level collision rectangles in `game.py`.

- `snow_boulder_cluster.png` — snow-capped rock cover; blocks movement and arrows.
- `fallen_pine.png` — a downed winter pine that forms a traversable-looking but solid barrier.

The visible sprites are depth-sorted against characters by their ground contact line. The painted forest and foreground shield clusters also have edge collision bounds so fighters cannot walk through them.
